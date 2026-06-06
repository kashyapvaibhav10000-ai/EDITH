"""
EDITH Telegram Bot — Full intent routing + scheduled weekly briefings.
Turns your Telegram into a live EDITH terminal from your phone.

Features:
 1. Voice message transcription (faster-whisper)
 2. Document/file handling (PDF, CSV, TXT, code)
 3. Reminders (/remind in 30 minutes X)
 4. URL auto-detection and summarization
 5. Rate limit feedback (instead of silent drop)
 6. /menu with inline buttons
 7. Location awareness (weather + reverse geocoding)
 8. /search <query> shortcut
 9. /summarize <url> command
10. /todo command (persistent JSON)
11. /exec <command> with HITL confirm
12. Sticker/GIF reactions
13. /uptime command (CPU/RAM/disk/uptime)
14. Multi-step task chains ("do: X then Y then Z")
15. Daily morning briefing (8am)
16. /export conversation as .txt
17. /ask <model> and /model <name> switching
18. /run <code> + code block detection with HITL
19. /pin, /pins, /unpin context notes
20. Processing queue with position feedback
"""

import os
import io
import re
import sys
import json
import html
import queue as _queue_mod
import tempfile
import subprocess
import threading
import time
import vault
from collections import defaultdict
from datetime import datetime
from dotenv import load_dotenv
from config import get_logger
from smart_router import smart_call

try:
    import httpx as req
    _USE_HTTPX = True
except ImportError:
    import requests as req
    _USE_HTTPX = False


def _llm(prompt, intent="chat"):
    return smart_call(prompt, intent=intent)

def _llm_gen(prompt, intent="chat"):
    return smart_call(prompt, intent=intent)

load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))
log = get_logger("telegram")

try:
    from event_bus import bus, Topic

    @bus.subscribe(Topic.AGENT_DONE)
    def _on_agent_done(payload: dict):
        summary = payload.get("summary", "Task completed")
        task_id = payload.get("task_id", "")
        send_telegram(f"✅ Agent done [{task_id}]: {summary}")

    @bus.subscribe(Topic.AGENT_ERROR)
    def _on_agent_error(payload: dict):
        error = payload.get("error", "Unknown error")
        task_id = payload.get("task_id", "")
        send_telegram(f"⛔ Agent error [{task_id}]: {error}")

except Exception as _eb_err:
    log.warning(f"event_bus subscription failed: {_eb_err}")

def _get_token() -> str:
    env_val = os.environ.get("TELEGRAM_TOKEN", "")
    if env_val and len(env_val) > 10:
        return env_val
    try:
        vault_val = vault.get_secret("TELEGRAM_TOKEN", "")
        if vault_val and len(vault_val) > 10:
            return vault_val
    except Exception:
        pass
    return ""

def _get_chat_id() -> str:
    env_val = os.environ.get("TELEGRAM_CHAT_ID", "")
    if env_val:
        return env_val
    try:
        vault_val = vault.get_secret("TELEGRAM_CHAT_ID", "")
        if vault_val:
            return vault_val
    except Exception:
        pass
    return ""

TOKEN = _get_token()
CHAT_ID = _get_chat_id()

# Per-sender rate limit: max 10 messages per 60 seconds
_TG_RATE_LIMIT = 10
_TG_RATE_WINDOW = 60
_tg_rate_cache: dict = defaultdict(list)

# Module-level HITL state
_hitl_msg_id: int | None = None

# Bot start time for uptime
_BOT_START_TIME = time.time()

# ── Feature 10: TODO list ─────────────────────────────────────────────────────
_TODO_FILE = os.path.join(os.path.dirname(__file__), "data", "telegram_todos.json")
_todo_list: list = []

def _load_todos():
    global _todo_list
    try:
        os.makedirs(os.path.dirname(_TODO_FILE), exist_ok=True)
        if os.path.exists(_TODO_FILE):
            with open(_TODO_FILE, "r") as f:
                _todo_list = json.load(f)
    except Exception as e:
        log.warning(f"Could not load todos: {e}")
        _todo_list = []

def _save_todos():
    try:
        os.makedirs(os.path.dirname(_TODO_FILE), exist_ok=True)
        with open(_TODO_FILE, "w") as f:
            json.dump(_todo_list, f, indent=2)
    except Exception as e:
        log.warning(f"Could not save todos: {e}")

# ── Feature 3: Reminders ──────────────────────────────────────────────────────
_reminders: dict = {}

# ── Feature 19: Context pinning ───────────────────────────────────────────────
_PINS_FILE = os.path.join(os.path.dirname(__file__), "data", "pinned_notes.json")
_pinned_notes: list = []

def _load_pins():
    global _pinned_notes
    try:
        os.makedirs(os.path.dirname(_PINS_FILE), exist_ok=True)
        if os.path.exists(_PINS_FILE):
            with open(_PINS_FILE, "r") as f:
                _pinned_notes = json.load(f)
    except Exception as e:
        log.warning(f"Could not load pinned notes: {e}")
        _pinned_notes = []

def _save_pins():
    try:
        os.makedirs(os.path.dirname(_PINS_FILE), exist_ok=True)
        with open(_PINS_FILE, "w") as f:
            json.dump(_pinned_notes, f, indent=2)
    except Exception as e:
        log.warning(f"Could not save pinned notes: {e}")

# ── Feature 11/18: Pending HITL states ───────────────────────────────────────
_exec_confirm_pending: dict = {}
_shell_confirm_pending: dict = {}

# ── Feature 17: Model preference ──────────────────────────────────────────────
_model_preference: dict = {"provider": None}
_SUPPORTED_MODELS = {"groq", "gemini", "openai", "anthropic", "ollama", "auto"}

# ── Feature 20: Per-chat processing queues ────────────────────────────────────
_chat_queues: dict = {}
_chat_queue_lock = threading.Lock()
_chat_workers: dict = {}

# ── URL regex ─────────────────────────────────────────────────────────────────
_URL_RE = re.compile(r"https?://[^\s]+")
_CODE_BLOCK_RE = re.compile(r"```(?:python)?\s*\n(.*?)```", re.DOTALL)


def _tg_is_rate_limited(chat_id: str) -> bool:
    now = time.time()
    timestamps = _tg_rate_cache[chat_id]
    _tg_rate_cache[chat_id] = [t for t in timestamps if now - t < _TG_RATE_WINDOW]
    if len(_tg_rate_cache[chat_id]) >= _TG_RATE_LIMIT:
        try:
            send_telegram("⏳ Still processing previous message, please wait...")
        except Exception:
            pass
        return True
    _tg_rate_cache[chat_id].append(now)
    return False


def _edith_error(e: Exception, context_hint: str = "") -> str:
    log.error(f"EDITH error: {e}", exc_info=True)
    err = str(e)
    if len(err) > 120:
        err = err[:120] + "…"
    hint = f" ({context_hint})" if context_hint else ""
    return f"Hit a snag on my end{hint}, Boss. {err} Want me to try a different approach?"


def send_telegram_placeholder(text: str = "⏳ Thinking...") -> int | None:
    token = TOKEN or os.getenv("TELEGRAM_TOKEN", "")
    chat_id = CHAT_ID or os.getenv("TELEGRAM_CHAT_ID", "")
    if not token or not chat_id:
        return None
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    try:
        r = req.post(url, json={"chat_id": chat_id, "text": text}, timeout=10)
        if r.status_code == 200:
            return r.json().get("result", {}).get("message_id")
    except Exception as e:
        log.warning(f"Placeholder send failed: {e}")
    return None


def edit_telegram_message(message_id: int, text: str, parse_mode: str = None) -> bool:
    token = TOKEN or os.getenv("TELEGRAM_TOKEN", "")
    chat_id = CHAT_ID or os.getenv("TELEGRAM_CHAT_ID", "")
    if not token or not chat_id or not message_id:
        return False
    url = f"https://api.telegram.org/bot{token}/editMessageText"
    text = text[:4000]
    payload = {"chat_id": chat_id, "message_id": message_id, "text": text}
    if parse_mode:
        payload["parse_mode"] = parse_mode
    try:
        r = req.post(url, json=payload, timeout=10)
        if r.status_code == 200:
            return True
        if r.status_code == 400 and "not modified" in r.text:
            return True
        log.warning(f"Edit message failed: {r.status_code} {r.text[:100]}")
        return False
    except Exception as e:
        log.warning(f"Edit message error: {e}")
        return False


def send_telegram(message: str, parse_mode: str = "Markdown") -> bool:
    token = TOKEN or os.getenv("TELEGRAM_TOKEN", "")
    chat_id = CHAT_ID or os.getenv("TELEGRAM_CHAT_ID", "")
    if not token or not chat_id:
        log.error("TELEGRAM_TOKEN or TELEGRAM_CHAT_ID not set")
        return False
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    chunks = [message[i:i+4000] for i in range(0, len(message), 4000)]
    for chunk in chunks:
        payload = {"chat_id": chat_id, "text": chunk, "parse_mode": parse_mode}
        try:
            r = req.post(url, json=payload, timeout=10)
            if r.status_code != 200:
                log.error(f"Telegram send failed: {r.status_code} {r.text}")
                payload["parse_mode"] = None
                r2 = req.post(url, json=payload, timeout=10)
                if r2.status_code != 200:
                    log.error(f"Telegram retry failed: {r2.status_code} {r2.text}")
                    return False
        except Exception as e:
            log.error(f"Telegram send failed: {e}")
            return False
    return True


def _send_typing(chat_id: str) -> None:
    token = TOKEN or os.getenv("TELEGRAM_TOKEN", "")
    if not token or not chat_id:
        return
    url = f"https://api.telegram.org/bot{token}/sendChatAction"
    try:
        req.post(url, json={"chat_id": chat_id, "action": "typing"}, timeout=5)
    except Exception as e:
        log.warning(f"Typing indicator failed: {e}")


def _build_reply_context(msg: dict, user_input: str) -> str:
    reply_msg = msg.get("reply_to_message", {})
    quoted = reply_msg.get("text", "").strip()
    if not quoted:
        return user_input
    if len(quoted) > 200:
        quoted = quoted[:200]
    return f'[Replying to: "{quoted}"] {user_input}'


def _smart_call_with_preference(prompt: str, intent: str = "chat") -> str:
    provider = _model_preference.get("provider")
    if not provider:
        return smart_call(prompt, intent=intent)
    try:
        if provider == "groq":
            from smart_router import call_groq
            return call_groq(prompt)
        elif provider == "gemini":
            from smart_router import call_gemini
            return call_gemini(prompt)
        elif provider == "openai":
            from smart_router import call_openai
            return call_openai(prompt)
    except (ImportError, AttributeError):
        pass
    return smart_call(prompt, intent=intent)


def process_message(text: str, msg: dict = None) -> str:
    """Route a Telegram message through the full orchestrator.chat() pipeline."""
    from intent import detect_intent
    from life_os import add_open_loop, close_open_loop
    from orchestrator import chat

    intent = detect_intent(text)
    inp = text.lower()

    if "loop" in inp or "remember" in inp or "note" in inp:
        add_open_loop(text)
        return f"📝 Logged as open loop: {text}"
    if "close" in inp or "done" in inp or "resolved" in inp:
        close_open_loop(text)
        return f"✅ Attempting to close matching loop."

    augmented_text = _build_reply_context(msg or {}, text)

    # Feature 19: Prepend pinned notes
    if _pinned_notes:
        pins_prefix = "📌 Pinned context:\n" + "\n".join(f"- {p}" for p in _pinned_notes) + "\n\n"
        augmented_text = pins_prefix + augmented_text

    # Feature 17: Use preferred provider if set
    provider = _model_preference.get("provider")
    if provider and provider != "auto":
        return _smart_call_with_preference(augmented_text, intent=intent)

    return chat(augmented_text, intent=intent, source="telegram", device="telegram")


def send_weekly_briefing():
    from life_os import weekly_briefing
    from cognitive_profile import update_profile
    log.info("Generating weekly briefing for Telegram...")
    briefing = weekly_briefing()
    success = send_telegram(briefing, parse_mode=None)
    if success:
        update_profile("Weekly briefing sent via Telegram", "telegram")
        log.info("Weekly briefing sent successfully")
    return success


# ═══════════════════════════════════════════════════════════════════════════════
# FEATURE 1: Voice message transcription
# ═══════════════════════════════════════════════════════════════════════════════

def _handle_voice(msg: dict) -> str:
    token = TOKEN or os.getenv("TELEGRAM_TOKEN", "")
    voice = msg.get("voice") or msg.get("audio", {})
    file_id = voice.get("file_id", "")
    if not file_id:
        return "Couldn't find audio data in that message, Boss."

    try:
        r = req.get(f"https://api.telegram.org/bot{token}/getFile", params={"file_id": file_id}, timeout=10)
        file_path = r.json()["result"]["file_path"]
    except Exception as e:
        return f"Couldn't download that audio, Boss: {e}"

    ogg_path = None
    wav_path = None
    try:
        dl_url = f"https://api.telegram.org/file/bot{token}/{file_path}"
        audio_bytes = req.get(dl_url, timeout=30).content
        with tempfile.NamedTemporaryFile(delete=False, suffix=".ogg") as tmp:
            tmp.write(audio_bytes)
            ogg_path = tmp.name
    except Exception as e:
        return f"Couldn't download that audio, Boss: {e}"

    transcript = None
    try:
        from faster_whisper import WhisperModel
        wav_path = ogg_path.replace(".ogg", ".wav")
        result = subprocess.run(["ffmpeg", "-y", "-i", ogg_path, wav_path], capture_output=True, timeout=30)
        if result.returncode != 0:
            try:
                from pydub import AudioSegment
                AudioSegment.from_ogg(ogg_path).export(wav_path, format="wav")
            except Exception:
                return "Voice transcription unavailable — couldn't convert audio format."

        model = WhisperModel("base", device="cpu", compute_type="int8")
        segments, _ = model.transcribe(wav_path)
        transcript = " ".join(seg.text for seg in segments).strip()
    except ImportError:
        return "Voice transcription unavailable — faster-whisper not installed."
    except Exception as e:
        return f"Transcription failed, Boss: {e}"
    finally:
        for p in [ogg_path, wav_path]:
            if p:
                try:
                    os.unlink(p)
                except Exception:
                    pass

    if not transcript:
        return "Couldn't make out what was said, Boss."

    try:
        ai_response = process_message(f"[Voice transcription]: {transcript}", msg)
    except Exception as e:
        ai_response = _edith_error(e, "voice message processing")

    return f"🎙 *Transcribed:* {transcript}\n\n{ai_response}"


# ═══════════════════════════════════════════════════════════════════════════════
# FEATURE 2: Document / file handling
# ═══════════════════════════════════════════════════════════════════════════════

def _handle_document(msg: dict) -> str:
    token = TOKEN or os.getenv("TELEGRAM_TOKEN", "")
    doc = msg.get("document", {})
    file_id = doc.get("file_id", "")
    file_name = doc.get("file_name", "file")
    mime_type = doc.get("mime_type", "")

    if not file_id:
        return "Couldn't find document data in that message, Boss."

    try:
        r = req.get(f"https://api.telegram.org/bot{token}/getFile", params={"file_id": file_id}, timeout=10)
        file_path = r.json()["result"]["file_path"]
    except Exception as e:
        return f"Couldn't fetch that document, Boss: {e}"

    try:
        dl_url = f"https://api.telegram.org/file/bot{token}/{file_path}"
        file_bytes = req.get(dl_url, timeout=60).content
    except Exception as e:
        return f"Download failed, Boss: {e}"

    ext = os.path.splitext(file_name)[1].lower()
    content_text = ""

    try:
        if ext == ".pdf" or mime_type == "application/pdf":
            try:
                from pypdf import PdfReader
                reader = PdfReader(io.BytesIO(file_bytes))
                content_text = "\n".join(page.extract_text() or "" for page in reader.pages)[:8000]
            except ImportError:
                return "PDF reading unavailable — pypdf not installed."
        elif ext == ".csv" or mime_type == "text/csv":
            try:
                import pandas as pd
                df = pd.read_csv(io.BytesIO(file_bytes))
                content_text = f"CSV ({df.shape[0]} rows, {df.shape[1]} cols):\n{df.head(20).to_string()}"
            except ImportError:
                content_text = file_bytes.decode("utf-8", errors="replace")[:8000]
        else:
            content_text = file_bytes.decode("utf-8", errors="replace")[:8000]
    except Exception as e:
        return f"Couldn't process that file, Boss: {e}"

    caption = msg.get("caption", "").strip() or "Analyse this file."
    prompt = f"File: {file_name}\n\n{content_text}\n\n{caption}"
    try:
        response = process_message(prompt, msg)
    except Exception as e:
        response = _edith_error(e, "document analysis")

    return f"📄 *{file_name}*\n\n{response}"


# ═══════════════════════════════════════════════════════════════════════════════
# FEATURE 3: Reminders
# ═══════════════════════════════════════════════════════════════════════════════

def _parse_reminder_time(time_str: str) -> float | None:
    now = time.time()
    time_str = time_str.lower().strip()

    m = re.match(r"in\s+(\d+(?:\.\d+)?)\s+(second|minute|hour|day)s?", time_str)
    if m:
        amount = float(m.group(1))
        unit = m.group(2)
        multipliers = {"second": 1, "minute": 60, "hour": 3600, "day": 86400}
        return now + amount * multipliers[unit]

    m = re.match(r"at\s+(\d{1,2})(?::(\d{2}))?\s*(am|pm)?", time_str)
    if m:
        hour = int(m.group(1))
        minute = int(m.group(2)) if m.group(2) else 0
        meridiem = m.group(3)
        if meridiem == "pm" and hour != 12:
            hour += 12
        elif meridiem == "am" and hour == 12:
            hour = 0
        from datetime import datetime as _dt
        target = _dt.now().replace(hour=hour, minute=minute, second=0, microsecond=0)
        target_ts = target.timestamp()
        if target_ts <= now:
            target_ts += 86400
        return target_ts

    return None


def _handle_remind_cmd(args: str) -> str:
    if not args:
        return "Usage: `/remind in 30 minutes call the dentist`\nor `/remind at 5pm standup`"

    m = re.match(r"(in\s+\d+(?:\.\d+)?\s+\w+|at\s+\d{1,2}(?::\d{2})?\s*(?:am|pm)?)\s+(.*)", args, re.IGNORECASE)
    if not m:
        return "Couldn't parse that time. Try: `in 30 minutes`, `in 2 hours`, `at 5pm`"

    time_expr = m.group(1).strip()
    reminder_text = m.group(2).strip()

    fire_at = _parse_reminder_time(time_expr)
    if fire_at is None:
        return f"Couldn't understand the time '{time_expr}'. Try: `in 30 minutes`, `at 5pm`"

    delay = fire_at - time.time()
    if delay < 0:
        return "That time is in the past, Boss."

    reminder_id = str(int(time.time() * 1000))

    def _fire():
        send_telegram(f"⏰ *Reminder:* {reminder_text}")
        _reminders.pop(reminder_id, None)

    timer = threading.Timer(delay, _fire)
    timer.daemon = True
    timer.start()
    _reminders[reminder_id] = {"text": reminder_text, "fire_at": fire_at, "timer": timer}

    fire_str = datetime.fromtimestamp(fire_at).strftime("%H:%M:%S")
    return f"⏰ Reminder set for {fire_str}: _{reminder_text}_"


# ═══════════════════════════════════════════════════════════════════════════════
# FEATURE 4 & 9: URL summarization
# ═══════════════════════════════════════════════════════════════════════════════

def _fetch_and_summarize_url(url: str) -> str:
    try:
        resp = req.get(url, timeout=15, headers={"User-Agent": "Mozilla/5.0 EDITH-Bot/1.0"})
        resp.raise_for_status()
        raw_html = resp.text
    except Exception as e:
        return f"Couldn't fetch that URL, Boss: {e}"

    text = re.sub(r"<[^>]+>", " ", raw_html)
    text = html.unescape(text)
    text = re.sub(r"\s+", " ", text).strip()[:6000]

    if len(text) < 50:
        return "Page content was too short to summarize, Boss."

    try:
        summary = smart_call(f"Summarize this web page content concisely:\n\n{text}", intent="summarize")
    except Exception as e:
        summary = _edith_error(e, "URL summarization")

    return f"🔗 *Summary of* `{url[:80]}`\n\n{summary}"


def _handle_summarize_cmd(args: str) -> str:
    url = args.strip()
    if not url:
        return "Usage: `/summarize https://example.com`"
    if not url.startswith("http"):
        url = "https://" + url
    return _fetch_and_summarize_url(url)


# ═══════════════════════════════════════════════════════════════════════════════
# FEATURE 6: /menu with inline buttons
# ═══════════════════════════════════════════════════════════════════════════════

def _send_menu(chat_id: str) -> None:
    token = TOKEN or os.getenv("TELEGRAM_TOKEN", "")
    if not token or not chat_id:
        return
    reply_markup = {
        "inline_keyboard": [
            [
                {"text": "🔍 Search",   "callback_data": "menu_search"},
                {"text": "📋 Status",   "callback_data": "menu_status"},
                {"text": "⏰ Remind",   "callback_data": "menu_remind"},
            ],
            [
                {"text": "📰 Briefing", "callback_data": "menu_briefing"},
                {"text": "🗑 Clear",    "callback_data": "menu_clear"},
                {"text": "📜 History",  "callback_data": "menu_history"},
            ],
            [
                {"text": "💻 Uptime",   "callback_data": "menu_uptime"},
                {"text": "📌 Pins",     "callback_data": "menu_pins"},
                {"text": "✅ Todo",     "callback_data": "menu_todo"},
            ],
        ]
    }
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    try:
        req.post(url, json={
            "chat_id": chat_id,
            "text": "🤖 *EDITH Command Menu*\nChoose an action:",
            "parse_mode": "Markdown",
            "reply_markup": reply_markup,
        }, timeout=10)
    except Exception as e:
        log.warning(f"Menu send failed: {e}")


# ═══════════════════════════════════════════════════════════════════════════════
# FEATURE 7: Location awareness
# ═══════════════════════════════════════════════════════════════════════════════

def _handle_location(msg: dict) -> str:
    loc = msg.get("location", {})
    lat = loc.get("latitude")
    lon = loc.get("longitude")
    if lat is None or lon is None:
        return "Couldn't read location coordinates, Boss."

    lines = [f"📍 Location: `{lat:.4f}, {lon:.4f}`"]

    try:
        weather_url = f"https://wttr.in/{lat},{lon}?format=3"
        w = req.get(weather_url, timeout=10, headers={"User-Agent": "curl/7.0"})
        if w.status_code == 200:
            lines.append(f"🌤 *Weather:* {w.text.strip()}")
    except Exception as e:
        log.warning(f"wttr.in failed: {e}")

    try:
        nom_resp = req.get(
            "https://nominatim.openstreetmap.org/reverse",
            params={"lat": lat, "lon": lon, "format": "json"},
            headers={"User-Agent": "EDITH-Bot/1.0"},
            timeout=10
        )
        if nom_resp.status_code == 200:
            place = nom_resp.json().get("display_name", "Unknown place")
            lines.append(f"🗺 *Place:* {place[:200]}")
    except Exception as e:
        log.warning(f"Nominatim failed: {e}")

    return "\n".join(lines)


# ═══════════════════════════════════════════════════════════════════════════════
# FEATURE 8: /search shortcut
# ═══════════════════════════════════════════════════════════════════════════════

def _handle_search_cmd(query: str) -> str:
    if not query:
        return "Usage: `/search <your query>`"
    try:
        result = smart_call(f"Search the web for: {query}", intent="search")
        return f"🔍 *{query}*\n\n{result}"
    except Exception as e:
        return _edith_error(e, "web search")


# ═══════════════════════════════════════════════════════════════════════════════
# FEATURE 10: /todo command
# ═══════════════════════════════════════════════════════════════════════════════

def _handle_todo_cmd(args: str) -> str:
    parts = args.strip().split(" ", 1)
    sub = parts[0].lower() if parts else ""

    if sub == "add":
        item = parts[1].strip() if len(parts) > 1 else ""
        if not item:
            return "Usage: `/todo add <item>`"
        _todo_list.append({"text": item, "done": False})
        _save_todos()
        return f"✅ Added: _{item}_"

    elif sub == "list" or sub == "":
        if not _todo_list:
            return "Your todo list is empty, Boss."
        lines = []
        for i, item in enumerate(_todo_list, 1):
            mark = "✅" if item["done"] else "☐"
            lines.append(f"{i}. {mark} {item['text']}")
        return "📋 *Todo List*\n" + "\n".join(lines)

    elif sub == "done":
        num_str = parts[1].strip() if len(parts) > 1 else ""
        if not num_str.isdigit():
            return "Usage: `/todo done <number>`"
        idx = int(num_str) - 1
        if idx < 0 or idx >= len(_todo_list):
            return f"No item #{num_str}, Boss."
        _todo_list[idx]["done"] = True
        _save_todos()
        return f"✅ Marked done: _{_todo_list[idx]['text']}_"

    elif sub == "clear":
        _todo_list.clear()
        _save_todos()
        return "🗑 Todo list cleared, Boss."

    else:
        return "Usage: `/todo add <item>` | `/todo list` | `/todo done <num>` | `/todo clear`"


# ═══════════════════════════════════════════════════════════════════════════════
# FEATURE 11: /exec with HITL
# ═══════════════════════════════════════════════════════════════════════════════

def _handle_exec_cmd(cmd_str: str, chat_id: str) -> str:
    if not cmd_str:
        return "Usage: `/exec <shell command>`"

    token = TOKEN or os.getenv("TELEGRAM_TOKEN", "")
    tg_chat_id = CHAT_ID or os.getenv("TELEGRAM_CHAT_ID", "")
    reply_markup = {
        "inline_keyboard": [[
            {"text": "✅ Run it", "callback_data": "exec_confirm"},
            {"text": "❌ Cancel", "callback_data": "exec_cancel"},
        ]]
    }
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    try:
        r = req.post(url, json={
            "chat_id": tg_chat_id,
            "text": f"⚠️ *Execute this command?*\n\n`{cmd_str}`",
            "parse_mode": "Markdown",
            "reply_markup": reply_markup,
        }, timeout=10)
        pending_msg_id = r.json().get("result", {}).get("message_id")
        _shell_confirm_pending[chat_id] = {"cmd": cmd_str, "msg_id": pending_msg_id}
    except Exception as e:
        log.warning(f"exec confirm send failed: {e}")
    return ""


def _run_shell_cmd(cmd_str: str) -> str:
    try:
        result = subprocess.run(cmd_str, shell=True, capture_output=True, text=True, timeout=30)
        out = result.stdout.strip()
        err = result.stderr.strip()
        combined = ""
        if out:
            combined += f"```\n{out[:2000]}\n```"
        if err:
            combined += f"\n⚠️ stderr:\n```\n{err[:500]}\n```"
        if not combined:
            combined = f"Command finished (exit code {result.returncode})."
        return combined
    except subprocess.TimeoutExpired:
        return "⏱ Command timed out (30s limit)."
    except Exception as e:
        return f"Execution failed: {e}"


# ═══════════════════════════════════════════════════════════════════════════════
# FEATURE 12: Sticker reactions
# ═══════════════════════════════════════════════════════════════════════════════

def _handle_sticker(msg: dict) -> str:
    sticker = msg.get("sticker", {})
    emoji = sticker.get("emoji", "🎭")
    set_name = sticker.get("set_name", "unknown")
    try:
        response = process_message(f"User sent a [{emoji}] sticker (from set: {set_name})", msg)
    except Exception as e:
        response = _edith_error(e, "sticker context")
    return response


# ═══════════════════════════════════════════════════════════════════════════════
# FEATURE 13: /uptime command
# ═══════════════════════════════════════════════════════════════════════════════

def _handle_uptime_cmd() -> str:
    try:
        import psutil
        cpu = psutil.cpu_percent(interval=1)
        ram = psutil.virtual_memory()
        disk = psutil.disk_usage("/")
        uptime_secs = int(time.time() - psutil.boot_time())
        hours, rem = divmod(uptime_secs, 3600)
        minutes, seconds = divmod(rem, 60)

        b_secs = int(time.time() - _BOT_START_TIME)
        b_h, b_rem = divmod(b_secs, 3600)
        b_m, b_s = divmod(b_rem, 60)

        return (
            f"💻 *System Stats*\n"
            f"🖥 CPU: {cpu}%\n"
            f"🧠 RAM: {ram.percent}% ({ram.used // 1024 // 1024} MB / {ram.total // 1024 // 1024} MB)\n"
            f"💾 Disk: {disk.percent}% ({disk.used // 1024 // 1024 // 1024} GB / {disk.total // 1024 // 1024 // 1024} GB)\n"
            f"⏱ System uptime: {hours}h {minutes}m {seconds}s\n"
            f"🤖 Bot uptime: {b_h}h {b_m}m {b_s}s"
        )
    except ImportError:
        return "System stats unavailable — psutil not installed."
    except Exception as e:
        return f"Couldn't get system stats, Boss: {e}"


# ═══════════════════════════════════════════════════════════════════════════════
# FEATURE 14: Multi-step task chains
# ═══════════════════════════════════════════════════════════════════════════════

def _handle_task_chain(text: str, msg: dict, chat_id: str) -> None:
    if text.lower().startswith("do:"):
        steps_text = text[3:].strip()
    else:
        steps_text = text

    steps = [s.strip() for s in re.split(r"\s+then\s+", steps_text, flags=re.IGNORECASE) if s.strip()]
    if len(steps) < 2:
        return

    def _run_chain():
        send_telegram(f"⛓ *Task chain: {len(steps)} steps*", parse_mode="Markdown")
        for i, step in enumerate(steps, 1):
            send_telegram(f"🔄 Step {i}/{len(steps)}: _{step}_", parse_mode="Markdown")
            try:
                result = process_message(step, msg)
            except Exception as e:
                result = _edith_error(e, f"step {i}")
            send_telegram(f"✅ *Step {i} result:*\n{result}", parse_mode="Markdown")
        send_telegram("🏁 *All steps complete.*", parse_mode="Markdown")

    threading.Thread(target=_run_chain, daemon=True).start()


# ═══════════════════════════════════════════════════════════════════════════════
# FEATURE 15: Daily morning briefing
# ═══════════════════════════════════════════════════════════════════════════════

def send_daily_briefing():
    try:
        daily_summary = smart_call(
            "Generate a short, motivating daily focus summary for the morning. "
            "Suggest 2–3 priorities to tackle today. Keep it under 200 words.",
            intent="chat"
        )
    except Exception as e:
        daily_summary = f"System operational. Have a productive day! (LLM unavailable: {e})"
    send_telegram(f"🌅 Good morning, Boss!\n\n{daily_summary}")


# ═══════════════════════════════════════════════════════════════════════════════
# FEATURE 16: /export conversation
# ═══════════════════════════════════════════════════════════════════════════════

def _send_telegram_document(file_bytes: bytes, filename: str, caption: str = "") -> bool:
    token = TOKEN or os.getenv("TELEGRAM_TOKEN", "")
    chat_id = CHAT_ID or os.getenv("TELEGRAM_CHAT_ID", "")
    if not token or not chat_id:
        return False
    url = f"https://api.telegram.org/bot{token}/sendDocument"
    try:
        files = {"document": (filename, io.BytesIO(file_bytes), "text/plain")}
        r = req.post(url, data={"chat_id": chat_id, "caption": caption}, files=files, timeout=30)
        return r.status_code == 200
    except Exception as e:
        log.error(f"sendDocument failed: {e}")
        return False


def _handle_export_cmd() -> str:
    try:
        from orchestrator import _source_history
        turns = _source_history.get("telegram", [])
    except Exception as e:
        return f"Couldn't access conversation history, Boss: {e}"

    if not turns:
        return "No conversation history to export yet, Boss."

    lines = [f"EDITH Telegram Conversation Export — {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"]
    lines.append("=" * 60 + "\n")
    for entry in turns:
        role = entry.get("role", "unknown").upper()
        content = entry.get("content", "")
        lines.append(f"[{role}]\n{content}\n\n")

    file_bytes = "\n".join(lines).encode("utf-8")
    filename = f"edith_chat_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"

    success = _send_telegram_document(file_bytes, filename, caption="📜 Conversation export")
    if success:
        return ""
    return "Couldn't send the export file, Boss. Try /history instead."


# ═══════════════════════════════════════════════════════════════════════════════
# FEATURE 17: /model and /ask commands
# ═══════════════════════════════════════════════════════════════════════════════

def _handle_model_cmd(args: str) -> str:
    name = args.strip().lower()
    if not name:
        current = _model_preference.get("provider") or "auto (smart_router default)"
        return (
            f"🤖 *Current model:* `{current}`\n\n"
            f"Available: {', '.join(sorted(_SUPPORTED_MODELS))}\n\n"
            "Usage: `/model groq` or `/model auto` to reset"
        )
    if name not in _SUPPORTED_MODELS:
        return f"Unknown model `{name}`. Supported: {', '.join(sorted(_SUPPORTED_MODELS))}"
    if name == "auto":
        _model_preference["provider"] = None
        return "✅ Model preference reset — using smart_router default."
    _model_preference["provider"] = name
    return f"✅ Model switched to `{name}`. Use `/model auto` to reset."


def _handle_ask_cmd(args: str) -> str:
    parts = args.strip().split(" ", 1)
    if len(parts) < 2:
        return "Usage: `/ask <model> <question>`\nModels: `groq`, `gemini`, `openai`"

    model_name = parts[0].lower()
    question = parts[1].strip()

    old_pref = _model_preference.get("provider")
    _model_preference["provider"] = model_name
    try:
        result = _smart_call_with_preference(question, intent="chat")
    finally:
        _model_preference["provider"] = old_pref
    return result


# ═══════════════════════════════════════════════════════════════════════════════
# FEATURE 18: Code execution with HITL
# ═══════════════════════════════════════════════════════════════════════════════

def _handle_code_block(code: str, chat_id: str) -> str:
    token = TOKEN or os.getenv("TELEGRAM_TOKEN", "")
    tg_chat_id = CHAT_ID or os.getenv("TELEGRAM_CHAT_ID", "")
    reply_markup = {
        "inline_keyboard": [[
            {"text": "▶️ Run code", "callback_data": "code_confirm"},
            {"text": "❌ Skip",     "callback_data": "code_cancel"},
        ]]
    }
    preview = code[:500] + ("…" if len(code) > 500 else "")
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    try:
        r = req.post(url, json={
            "chat_id": tg_chat_id,
            "text": f"💻 *Run this Python code?*\n\n```python\n{preview}\n```",
            "parse_mode": "Markdown",
            "reply_markup": reply_markup,
        }, timeout=10)
        pending_msg_id = r.json().get("result", {}).get("message_id")
        _exec_confirm_pending[chat_id] = {"code": code, "msg_id": pending_msg_id}
    except Exception as e:
        log.warning(f"code confirm send failed: {e}")
    return ""


def _run_python_code(code: str) -> str:
    with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
        f.write(code)
        script_path = f.name
    try:
        result = subprocess.run(["python3", script_path], capture_output=True, text=True, timeout=30)
        out = result.stdout.strip()
        err = result.stderr.strip()
        combined = ""
        if out:
            combined += f"```\n{out[:2000]}\n```"
        if err:
            combined += f"\n⚠️ stderr:\n```\n{err[:500]}\n```"
        if not combined:
            combined = f"Code ran (exit code {result.returncode})."
        return combined
    except subprocess.TimeoutExpired:
        return "⏱ Code execution timed out (30s limit)."
    except Exception as e:
        return f"Execution failed: {e}"
    finally:
        try:
            os.unlink(script_path)
        except Exception:
            pass


def _handle_run_cmd(args: str, chat_id: str) -> str:
    code = args.strip()
    if not code:
        return "Usage: `/run print('hello')`\nOr send a code block with triple backticks."
    return _handle_code_block(code, chat_id)


# ═══════════════════════════════════════════════════════════════════════════════
# FEATURE 19: Context pinning
# ═══════════════════════════════════════════════════════════════════════════════

def _handle_pin_cmd(args: str) -> str:
    text = args.strip()
    if not text:
        return "Usage: `/pin <text to always remember>`"
    _pinned_notes.append(text)
    _save_pins()
    return f"📌 Pinned: _{text}_\n\nThis will be injected into every message context."


def _handle_pins_cmd() -> str:
    if not _pinned_notes:
        return "No pinned notes yet, Boss. Use `/pin <text>` to add one."
    lines = [f"{i+1}. {p}" for i, p in enumerate(_pinned_notes)]
    return "📌 *Pinned Notes*\n" + "\n".join(lines)


def _handle_unpin_cmd(args: str) -> str:
    if not args.strip().isdigit():
        return "Usage: `/unpin <number>` — see `/pins` for the list."
    idx = int(args.strip()) - 1
    if idx < 0 or idx >= len(_pinned_notes):
        return f"No pin #{args.strip()}, Boss. See `/pins`."
    removed = _pinned_notes.pop(idx)
    _save_pins()
    return f"🗑 Unpinned: _{removed}_"


# ═══════════════════════════════════════════════════════════════════════════════
# FEATURE 20: /weather command
# ═══════════════════════════════════════════════════════════════════════════════

def _handle_weather_cmd(city: str) -> str:
    city = city.strip()
    if not city:
        return "Usage: `/weather <city>` — e.g. `/weather Mumbai`"
    try:
        url = f"https://wttr.in/{city}?format=3"
        r = req.get(url, timeout=10, headers={"User-Agent": "curl/7.0"})
        if r.status_code == 200:
            return f"🌤 *Weather in {city}:*\n{r.text.strip()}"
        return f"Couldn't get weather for '{city}', Boss (status {r.status_code})."
    except Exception as e:
        return f"Weather lookup failed, Boss: {e}"


# ═══════════════════════════════════════════════════════════════════════════════
# FEATURE 20b: Processing queue
# ═══════════════════════════════════════════════════════════════════════════════

def _get_or_create_queue(chat_id: str):
    with _chat_queue_lock:
        if chat_id not in _chat_queues:
            _chat_queues[chat_id] = _queue_mod.Queue()
        return _chat_queues[chat_id]


def _queue_worker(chat_id: str):
    from intent_dispatch import get_pending_action
    global _hitl_msg_id

    q = _get_or_create_queue(chat_id)
    while True:
        try:
            item = q.get(timeout=120)
        except _queue_mod.Empty:
            with _chat_queue_lock:
                _chat_workers.pop(chat_id, None)
            return

        text, msg = item
        try:
            _send_typing(chat_id)
            msg_id = send_telegram_placeholder("⏳ On it, Boss...")
            try:
                response = process_message(text, msg)
                pending = get_pending_action()
                if pending and msg_id:
                    _send_hitl_keyboard(msg_id, response)
                    _hitl_msg_id = msg_id
                elif msg_id:
                    if not edit_telegram_message(msg_id, response, parse_mode="Markdown"):
                        edit_telegram_message(msg_id, response)
                else:
                    send_telegram(response, parse_mode=None)
            except Exception as e:
                err_msg = _edith_error(e, "processing your message")
                if msg_id:
                    edit_telegram_message(msg_id, err_msg)
                else:
                    send_telegram(err_msg)
        finally:
            q.task_done()


def _enqueue_message(chat_id: str, text: str, msg: dict) -> None:
    q = _get_or_create_queue(chat_id)
    qsize = q.qsize()

    if qsize > 0:
        send_telegram(f"⏳ Queued (position {qsize + 1}) — I'll get to it, Boss.")

    q.put((text, msg))

    with _chat_queue_lock:
        worker = _chat_workers.get(chat_id)
        if worker is None or not worker.is_alive():
            t = threading.Thread(target=_queue_worker, args=(chat_id,), daemon=True)
            t.start()
            _chat_workers[chat_id] = t


# ═══════════════════════════════════════════════════════════════════════════════
# Existing commands handlers (unchanged)
# ═══════════════════════════════════════════════════════════════════════════════

def _handle_mcpstatus_cmd() -> str:
    try:
        import mcp_bridge
        status = mcp_bridge.get_mcp_status()
        if not status:
            return "No MCP servers configured."
        lines = ["🔌 *MCP Server Status*\n"]
        for name, info in status.items():
            state = "✅" if info["enabled"] else "❌"
            lines.append(
                f"{state} *{name}* — tools: {info['tool_count']} — last: {info['last_called']}\n"
                f"  _{info['description']}_"
            )
        return "\n".join(lines)
    except Exception as e:
        return f"MCP status error: {e}"


def _handle_mcp_cmd(args: str) -> str:
    try:
        import mcp_bridge
    except Exception as e:
        return f"MCP bridge unavailable: {e}"

    if not args:
        enabled = mcp_bridge.get_enabled_servers()
        srv = ", ".join(enabled) if enabled else "none"
        return (
            f"🔌 *MCP* — enabled: {srv}\n\n"
            "Commands:\n"
            "`/mcp read /path/file` — read file\n"
            "`/mcp list /path/` — list directory\n"
            "`/mcp search <query>` — Brave web search\n"
            "`/mcp github <query>` — GitHub search\n"
            "`/mcp drive <query>` — Google Drive search\n"
            "`/mcpstatus` — server status"
        )

    lower = args.lower()

    if lower.startswith("read "):
        path_m = re.search(r"(/[^\s]+|\b[\w./~-]+\.\w+)", args)
        if not path_m:
            return "📄 Usage: `/mcp read /path/to/file`"
        path = os.path.expanduser(path_m.group(1))
        result = mcp_bridge.call_mcp_server("filesystem", "read_file", {"path": path})
        return f"📄 *{path}*\n\n{result[:3000]}"

    if lower.startswith("list ") or lower.startswith("ls "):
        path_m = re.search(r"(/[^\s]+)", args)
        path = os.path.expanduser(path_m.group(1)) if path_m else os.path.expanduser("~")
        result = mcp_bridge.call_mcp_server("filesystem", "list_directory", {"path": path})
        return f"📂 *{path}*\n\n{result[:3000]}"

    if lower.startswith("search "):
        query = args[7:].strip()
        result = mcp_bridge.call_mcp_server("brave-search", "search", {"query": query})
        return f"🔍 *{query}*\n\n{result[:3000]}"

    if lower.startswith("github "):
        query = args[7:].strip()
        result = mcp_bridge.call_mcp_server("github", "search_repositories", {"query": query})
        return f"🐙 *{query}*\n\n{result[:3000]}"

    if lower.startswith("drive "):
        query = args[6:].strip()
        result = mcp_bridge.call_mcp_server("gdrive", "search_files", {"query": query})
        return f"📁 *{query}*\n\n{result[:3000]}"

    return f"Unknown MCP sub-command: `{args}`\nTry: read, list, search, github, drive"


def _handle_history_cmd() -> str:
    from orchestrator import _source_history
    turns = _source_history["telegram"][-20:]
    if len(turns) < 2:
        return "No conversation history yet, Boss."
    lines = []
    for entry in turns:
        role = entry.get("role", "")
        content = entry.get("content", "")
        if len(content) > 150:
            content = content[:150] + "…"
        if role == "user":
            lines.append(f"👤 {content}")
        elif role == "assistant":
            lines.append(f"🤖 {content}")
    return "\n".join(lines)


def _handle_clear_cmd() -> str:
    import tempfile
    from orchestrator import _source_history, TELEGRAM_JSONL
    _source_history["telegram"].clear()
    try:
        data_dir = os.path.dirname(TELEGRAM_JSONL)
        os.makedirs(data_dir, exist_ok=True)
        with tempfile.NamedTemporaryFile(mode="w", delete=False, dir=data_dir, suffix=".jsonl") as tmp:
            tmp_path = tmp.name
        os.replace(tmp_path, TELEGRAM_JSONL)
        return "🗑 Telegram history cleared, Boss. Fresh start."
    except OSError as e:
        return f"Cleared in memory, Boss. Disk write failed — {e}."


def _handle_status_cmd() -> str:
    try:
        from smart_router import router_status
        provider = router_status().get("active_provider", "unavailable")
    except Exception:
        provider = "unavailable"

    try:
        from orchestrator import _source_history
        history_len = len(_source_history["telegram"])
    except Exception:
        history_len = "unavailable"

    try:
        from orchestrator import smart_memory
        memory_count = smart_memory.count()
    except Exception:
        memory_count = "unavailable"

    now_str = datetime.now().strftime("%H:%M")
    status = (
        f"🤖 EDITH Status\n"
        f"⚡ Provider: {provider}\n"
        f"💬 Telegram turns: {history_len}\n"
        f"🧠 Memories: {memory_count}\n"
        f"🕐 {now_str}"
    )
    return status[:300]


def _answer_callback(cq_id: str, text: str = "") -> None:
    token = TOKEN or os.getenv("TELEGRAM_TOKEN", "")
    if not token or not cq_id:
        return
    url = f"https://api.telegram.org/bot{token}/answerCallbackQuery"
    try:
        req.post(url, json={"callback_query_id": cq_id, "text": text}, timeout=5)
    except Exception as e:
        log.warning(f"answerCallbackQuery failed: {e}")


def _send_hitl_keyboard(msg_id: int, prompt_text: str) -> None:
    token = TOKEN or os.getenv("TELEGRAM_TOKEN", "")
    chat_id = CHAT_ID or os.getenv("TELEGRAM_CHAT_ID", "")
    if not token or not chat_id or not msg_id:
        return
    reply_markup = {
        "inline_keyboard": [[
            {"text": "✅ Yes, run it", "callback_data": "hitl_confirm"},
            {"text": "❌ Cancel",       "callback_data": "hitl_cancel"},
        ]]
    }
    url = f"https://api.telegram.org/bot{token}/editMessageText"
    try:
        req.post(url, json={
            "chat_id": chat_id,
            "message_id": msg_id,
            "text": prompt_text[:4000],
            "reply_markup": reply_markup,
        }, timeout=10)
    except Exception as e:
        log.warning(f"HITL keyboard send failed: {e}")


def _handle_callback_query(cq: dict) -> None:
    from intent_dispatch import get_pending_action, execute_pending_action, clear_pending_action

    global _hitl_msg_id

    cq_id  = cq.get("id", "")
    data   = cq.get("data", "")
    msg    = cq.get("message", {})
    msg_id = msg.get("message_id")
    from_chat = str(msg.get("chat", {}).get("id", CHAT_ID))

    _answer_callback(cq_id, "")

    # Menu callbacks
    if data.startswith("menu_"):
        action = data[5:]
        if action == "status":
            send_telegram(_handle_status_cmd(), parse_mode=None)
        elif action == "history":
            send_telegram(_handle_history_cmd(), parse_mode=None)
        elif action == "clear":
            send_telegram(_handle_clear_cmd(), parse_mode=None)
        elif action == "uptime":
            send_telegram(_handle_uptime_cmd())
        elif action == "pins":
            send_telegram(_handle_pins_cmd())
        elif action == "todo":
            send_telegram(_handle_todo_cmd("list"))
        elif action == "briefing":
            threading.Thread(target=send_weekly_briefing, daemon=True).start()
            send_telegram("📰 Generating weekly briefing, Boss...")
        elif action == "search":
            send_telegram("Use `/search <query>` to search the web, Boss.")
        elif action == "remind":
            send_telegram("Use `/remind in 30 minutes <message>`, Boss.")
        return

    # Exec HITL
    if data == "exec_confirm":
        pending = _shell_confirm_pending.pop(from_chat, None) or _shell_confirm_pending.pop(str(CHAT_ID), None)
        if not pending:
            send_telegram("No pending shell command, Boss.")
            return
        result = _run_shell_cmd(pending.get("cmd", ""))
        token = TOKEN or os.getenv("TELEGRAM_TOKEN", "")
        tg_chat_id = CHAT_ID or os.getenv("TELEGRAM_CHAT_ID", "")
        try:
            req.post(f"https://api.telegram.org/bot{token}/editMessageText", json={
                "chat_id": tg_chat_id, "message_id": msg_id,
                "text": result[:4000] or "Done.", "parse_mode": "Markdown",
                "reply_markup": {"inline_keyboard": []},
            }, timeout=10)
        except Exception as e:
            send_telegram(result or "Done.")
        return

    if data == "exec_cancel":
        _shell_confirm_pending.pop(from_chat, None)
        _shell_confirm_pending.pop(str(CHAT_ID), None)
        token = TOKEN or os.getenv("TELEGRAM_TOKEN", "")
        tg_chat_id = CHAT_ID or os.getenv("TELEGRAM_CHAT_ID", "")
        try:
            req.post(f"https://api.telegram.org/bot{token}/editMessageText", json={
                "chat_id": tg_chat_id, "message_id": msg_id,
                "text": "Cancelled, Boss.", "reply_markup": {"inline_keyboard": []},
            }, timeout=10)
        except Exception:
            pass
        return

    # Code HITL
    if data == "code_confirm":
        pending = _exec_confirm_pending.pop(from_chat, None) or _exec_confirm_pending.pop(str(CHAT_ID), None)
        if not pending:
            send_telegram("No pending code to run, Boss.")
            return
        result = _run_python_code(pending.get("code", ""))
        token = TOKEN or os.getenv("TELEGRAM_TOKEN", "")
        tg_chat_id = CHAT_ID or os.getenv("TELEGRAM_CHAT_ID", "")
        try:
            req.post(f"https://api.telegram.org/bot{token}/editMessageText", json={
                "chat_id": tg_chat_id, "message_id": msg_id,
                "text": (result or "Done.")[:4000], "parse_mode": "Markdown",
                "reply_markup": {"inline_keyboard": []},
            }, timeout=10)
        except Exception:
            send_telegram(result or "Done.")
        return

    if data == "code_cancel":
        _exec_confirm_pending.pop(from_chat, None)
        _exec_confirm_pending.pop(str(CHAT_ID), None)
        token = TOKEN or os.getenv("TELEGRAM_TOKEN", "")
        tg_chat_id = CHAT_ID or os.getenv("TELEGRAM_CHAT_ID", "")
        try:
            req.post(f"https://api.telegram.org/bot{token}/editMessageText", json={
                "chat_id": tg_chat_id, "message_id": msg_id,
                "text": "Cancelled, Boss.", "reply_markup": {"inline_keyboard": []},
            }, timeout=10)
        except Exception:
            pass
        return

    # Original HITL
    pending = get_pending_action()
    if not pending:
        return

    if data == "hitl_confirm":
        try:
            result = execute_pending_action(pending)
            result_text = str(result) if result else "Done, Boss."
        except Exception as e:
            result_text = _edith_error(e, "executing the command")
        clear_pending_action()
        token = TOKEN or os.getenv("TELEGRAM_TOKEN", "")
        chat_id = CHAT_ID or os.getenv("TELEGRAM_CHAT_ID", "")
        try:
            req.post(f"https://api.telegram.org/bot{token}/editMessageText", json={
                "chat_id": chat_id, "message_id": msg_id,
                "text": result_text[:4000], "reply_markup": {"inline_keyboard": []},
            }, timeout=10)
        except Exception as e:
            log.warning(f"HITL confirm edit failed: {e}")
        _hitl_msg_id = None

    elif data == "hitl_cancel":
        clear_pending_action()
        token = TOKEN or os.getenv("TELEGRAM_TOKEN", "")
        chat_id = CHAT_ID or os.getenv("TELEGRAM_CHAT_ID", "")
        try:
            req.post(f"https://api.telegram.org/bot{token}/editMessageText", json={
                "chat_id": chat_id, "message_id": msg_id,
                "text": "Cancelled, Boss.", "reply_markup": {"inline_keyboard": []},
            }, timeout=10)
        except Exception as e:
            log.warning(f"HITL cancel edit failed: {e}")
        _hitl_msg_id = None


def _handle_photo(msg: dict) -> str:
    from context import DispatchContext
    from orchestrator import chat as _orch_chat

    token = TOKEN or os.getenv("TELEGRAM_TOKEN", "")
    caption = msg.get("caption", "").strip() or "Describe this image."
    photos = msg.get("photo", [])
    if not photos:
        return "Couldn't find photo data in that message, Boss."

    best = photos[-1]
    file_id = best.get("file_id", "")

    try:
        r = req.get(f"https://api.telegram.org/bot{token}/getFile", params={"file_id": file_id}, timeout=10)
        file_path = r.json()["result"]["file_path"]
    except Exception as e:
        return "Couldn't download that photo, Boss. Try again?"

    local_path = None
    try:
        dl_url = f"https://api.telegram.org/file/bot{token}/{file_path}"
        img_bytes = req.get(dl_url, timeout=30).content
        suffix = os.path.splitext(file_path)[1] or ".jpg"
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            tmp.write(img_bytes)
            local_path = tmp.name
    except Exception as e:
        return "Couldn't download that photo, Boss. Try again?"

    try:
        from handlers.misc import _handle_vision
        ctx = DispatchContext(
            user_input=f"{caption} [image: {local_path}]",
            intent="vision", source="telegram", device="telegram",
            chat_fn=_orch_chat,
        )
        result = _handle_vision(ctx)
        if hasattr(result, "ok"):
            return str(result.value) if result.ok else _edith_error(Exception(result.error), "vision analysis")
        return str(result)
    except Exception as e:
        return "Vision isn't available right now, Boss."
    finally:
        if local_path:
            try:
                os.unlink(local_path)
            except Exception:
                pass


# ═══════════════════════════════════════════════════════════════════════════════
# Scheduling helpers
# ═══════════════════════════════════════════════════════════════════════════════

def send_drift_alert():
    from cognitive_profile import detect_drift, get_recent_queries
    recent = get_recent_queries(10)
    if len(recent) < 5:
        return
    drift_report = detect_drift()
    drift_lower = drift_report.lower()
    if any(w in drift_lower for w in ["drift", "not aligned", "misalign", "off track", "warning"]):
        send_telegram(f"⚠️ *EDITH DRIFT ALERT*\n\n{drift_report}", parse_mode="Markdown")


def start_briefing_scheduler():
    import schedule

    schedule.every().sunday.at("08:00").do(send_weekly_briefing)
    schedule.every().day.at("08:00").do(send_daily_briefing)      # Feature 15
    schedule.every(6).hours.do(send_drift_alert)
    log.info("Scheduler active: weekly=Sunday 08:00, daily=every day 08:00, drift check=every 6h")

    def _run():
        while True:
            schedule.run_pending()
            time.sleep(60)

    t = threading.Thread(target=_run, daemon=True)
    t.start()
    return t


# ═══════════════════════════════════════════════════════════════════════════════
# Shared command dispatcher (used by both poll and webhook)
# ═══════════════════════════════════════════════════════════════════════════════

def _dispatch_text(text: str, msg: dict, chat_id: str) -> None:
    """Dispatch a text message to the correct handler."""
    from session import track_query
    from intent_dispatch import get_pending_action
    global _hitl_msg_id

    log.info(f"Telegram received: {text[:80]}")
    track_query(text)

    tl = text.lower()

    # ── Commands ───────────────────────────────────────────────────────────────
    if tl in ["/start", "start"]:
        send_telegram("🤖 *EDITH online.* Ready, Boss.")
        return

    if tl in ["/help", "help"]:
        send_telegram(
            "*EDITH Commands*\n\n"
            "💬 Just type anything to chat\n"
            "/menu — quick action buttons\n"
            "/status — system status\n"
            "/history — recent conversation\n"
            "/clear — clear history\n"
            "/remind in 30m do X — set reminder\n"
            "/search <query> — web search\n"
            "/summarize <url> — summarize URL\n"
            "/todo list|add X|done N — todo list\n"
            "/exec <cmd> — run shell command\n"
            "/run <code> — run Python code\n"
            "/uptime — server stats\n"
            "/export — export conversation\n"
            "/model <name> — switch AI model\n"
            "/ask <model> <question> — ask specific model\n"
            "/pin <text> — pin permanent context\n"
            "/pins — show pinned notes\n"
            "/unpin <n> — remove pin\n"
            "/weather <city> — weather\n"
            "/mcpstatus — MCP server status\n"
            "/mcp <cmd> — MCP tools"
        )
        return

    if tl == "/history":
        send_telegram(_handle_history_cmd(), parse_mode=None)
        return

    if tl == "/clear":
        send_telegram(_handle_clear_cmd(), parse_mode=None)
        return

    if tl == "/status":
        send_telegram(_handle_status_cmd(), parse_mode=None)
        return

    if tl == "/mcpstatus":
        send_telegram(_handle_mcpstatus_cmd())
        return

    if tl.startswith("/mcp"):
        send_telegram(_handle_mcp_cmd(text[4:].strip()))
        return

    if tl == "/menu":
        _send_menu(chat_id)
        return

    if tl.startswith("/remind"):
        send_telegram(_handle_remind_cmd(text[7:].strip()))
        return

    if tl.startswith("/summarize"):
        _send_typing(chat_id)
        s_msg_id = send_telegram_placeholder("⏳ Fetching and summarizing, Boss...")
        response = _handle_summarize_cmd(text[10:].strip())
        if s_msg_id:
            if not edit_telegram_message(s_msg_id, response, parse_mode="Markdown"):
                edit_telegram_message(s_msg_id, response)
        else:
            send_telegram(response)
        return

    if tl.startswith("/search"):
        _send_typing(chat_id)
        s_msg_id = send_telegram_placeholder("⏳ Searching, Boss...")
        response = _handle_search_cmd(text[7:].strip())
        if s_msg_id:
            if not edit_telegram_message(s_msg_id, response, parse_mode="Markdown"):
                edit_telegram_message(s_msg_id, response)
        else:
            send_telegram(response)
        return

    if tl.startswith("/todo"):
        send_telegram(_handle_todo_cmd(text[5:].strip()))
        return

    if tl.startswith("/exec"):
        _handle_exec_cmd(text[5:].strip(), chat_id)
        return

    if tl == "/uptime":
        send_telegram(_handle_uptime_cmd())
        return

    if tl.startswith("/model"):
        send_telegram(_handle_model_cmd(text[6:].strip()))
        return

    if tl.startswith("/run"):
        _handle_run_cmd(text[4:].strip(), chat_id)
        return

    if tl == "/export":
        _send_typing(chat_id)
        result = _handle_export_cmd()
        if result:
            send_telegram(result)
        return

    if tl.startswith("/ask"):
        _send_typing(chat_id)
        a_msg_id = send_telegram_placeholder("⏳ Routing to model, Boss...")
        response = _handle_ask_cmd(text[4:].strip())
        if a_msg_id:
            if not edit_telegram_message(a_msg_id, response, parse_mode="Markdown"):
                edit_telegram_message(a_msg_id, response)
        else:
            send_telegram(response)
        return

    if tl.startswith("/pin ") or tl == "/pin":
        send_telegram(_handle_pin_cmd(text[4:].strip()))
        return

    if tl == "/pins":
        send_telegram(_handle_pins_cmd())
        return

    if tl.startswith("/unpin"):
        send_telegram(_handle_unpin_cmd(text[6:].strip()))
        return

    if tl.startswith("/weather"):
        send_telegram(_handle_weather_cmd(text[8:].strip()))
        return

    # Auto-detect URL (message is mostly just a URL)
    url_match = _URL_RE.search(text)
    if url_match and len(text.split()) <= 3:
        _send_typing(chat_id)
        u_msg_id = send_telegram_placeholder("⏳ Fetching URL, Boss...")
        response = _fetch_and_summarize_url(url_match.group(0))
        if u_msg_id:
            if not edit_telegram_message(u_msg_id, response, parse_mode="Markdown"):
                edit_telegram_message(u_msg_id, response)
        else:
            send_telegram(response)
        return

    # Multi-step task chain
    is_chain = text.lower().startswith("do:") or text.lower().count(" then ") >= 2
    if is_chain:
        _handle_task_chain(text, msg, chat_id)
        return

    # Code block detection
    code_match = _CODE_BLOCK_RE.search(text)
    if code_match:
        _handle_code_block(code_match.group(1).strip(), chat_id)
        return

    # Full EDITH pipeline via queue
    _enqueue_message(chat_id, text, msg)


# ═══════════════════════════════════════════════════════════════════════════════
# Main polling loop
# ═══════════════════════════════════════════════════════════════════════════════

def poll_telegram():
    if not TOKEN or not CHAT_ID:
        print("[EDITH Telegram] Missing TELEGRAM_TOKEN or TELEGRAM_CHAT_ID")
        return

    from session import start_session

    _load_pins()
    _load_todos()

    last_update_id = None
    session_id = start_session()
    print(f"[EDITH Telegram] Polling... Session: {session_id}")
    print("  Send messages from your phone → EDITH processes → replies")
    print("  Ctrl+C to stop\n")

    try:
        send_telegram("🤖 *EDITH online.* Memory loaded. Awaiting commands, Boss.")
    except Exception as e:
        log.warning(f"Failed to send startup message: {e}")

    while True:
        try:
            url = f"https://api.telegram.org/bot{TOKEN}/getUpdates"
            params = {"timeout": 10, "offset": last_update_id}
            r = req.get(url, params=params, timeout=15)
            updates = r.json().get("result", [])

            for update in updates:
                last_update_id = update["update_id"] + 1

                if "callback_query" in update:
                    _handle_callback_query(update["callback_query"])
                    continue

                msg     = update.get("message", {})
                chat_id = str(msg.get("chat", {}).get("id", ""))

                if not chat_id or chat_id != str(CHAT_ID):
                    if chat_id:
                        log.warning(f"Rejected message from unauthorized chat_id={chat_id}")
                    continue

                if _tg_is_rate_limited(chat_id):
                    continue

                # Media routing
                if "photo" in msg:
                    _send_typing(chat_id)
                    ph_id = send_telegram_placeholder("⏳ Analysing image, Boss...")
                    try:
                        response = _handle_photo(msg)
                    except Exception as e:
                        response = _edith_error(e, "photo analysis")
                    if ph_id:
                        edit_telegram_message(ph_id, response, parse_mode="Markdown") or edit_telegram_message(ph_id, response)
                    else:
                        send_telegram(response, parse_mode=None)
                    continue

                if "voice" in msg or "audio" in msg:
                    _send_typing(chat_id)
                    v_id = send_telegram_placeholder("⏳ Transcribing audio, Boss...")
                    try:
                        response = _handle_voice(msg)
                    except Exception as e:
                        response = _edith_error(e, "voice transcription")
                    if v_id:
                        edit_telegram_message(v_id, response, parse_mode="Markdown") or edit_telegram_message(v_id, response)
                    else:
                        send_telegram(response, parse_mode=None)
                    continue

                if "document" in msg:
                    _send_typing(chat_id)
                    d_id = send_telegram_placeholder("⏳ Processing document, Boss...")
                    try:
                        response = _handle_document(msg)
                    except Exception as e:
                        response = _edith_error(e, "document processing")
                    if d_id:
                        edit_telegram_message(d_id, response, parse_mode="Markdown") or edit_telegram_message(d_id, response)
                    else:
                        send_telegram(response, parse_mode=None)
                    continue

                if "location" in msg:
                    _send_typing(chat_id)
                    try:
                        response = _handle_location(msg)
                    except Exception as e:
                        response = _edith_error(e, "location")
                    send_telegram(response)
                    continue

                if "sticker" in msg:
                    _send_typing(chat_id)
                    try:
                        response = _handle_sticker(msg)
                    except Exception as e:
                        response = _edith_error(e, "sticker")
                    send_telegram(response, parse_mode=None)
                    continue

                text = msg.get("text", "").strip()
                if not text:
                    continue

                _dispatch_text(text, msg, chat_id)

            time.sleep(2)

        except KeyboardInterrupt:
            send_telegram("🔴 EDITH going offline. Goodbye, Boss.")
            print("\n[EDITH Telegram] Stopped.")
            break
        except Exception as e:
            log.error(f"Polling error: {e}")
            time.sleep(10)


def handle_telegram_update(update: dict) -> None:
    """Webhook mode entry point."""
    global _hitl_msg_id

    if "callback_query" in update:
        _handle_callback_query(update["callback_query"])
        return

    msg     = update.get("message", {})
    chat_id = str(msg.get("chat", {}).get("id", ""))

    if not chat_id or chat_id != str(CHAT_ID):
        if chat_id:
            log.warning(f"Webhook: rejected from chat_id={chat_id}")
        return

    if _tg_is_rate_limited(chat_id):
        return

    if "photo" in msg:
        _send_typing(chat_id)
        ph_id = send_telegram_placeholder("⏳ Analysing image, Boss...")
        try:
            response = _handle_photo(msg)
        except Exception as e:
            response = _edith_error(e, "photo analysis")
        if ph_id:
            edit_telegram_message(ph_id, response, parse_mode="Markdown") or edit_telegram_message(ph_id, response)
        else:
            send_telegram(response, parse_mode=None)
        return

    if "voice" in msg or "audio" in msg:
        _send_typing(chat_id)
        v_id = send_telegram_placeholder("⏳ Transcribing audio, Boss...")
        try:
            response = _handle_voice(msg)
        except Exception as e:
            response = _edith_error(e, "voice transcription")
        if v_id:
            edit_telegram_message(v_id, response, parse_mode="Markdown") or edit_telegram_message(v_id, response)
        else:
            send_telegram(response, parse_mode=None)
        return

    if "document" in msg:
        _send_typing(chat_id)
        d_id = send_telegram_placeholder("⏳ Processing document, Boss...")
        try:
            response = _handle_document(msg)
        except Exception as e:
            response = _edith_error(e, "document processing")
        if d_id:
            edit_telegram_message(d_id, response, parse_mode="Markdown") or edit_telegram_message(d_id, response)
        else:
            send_telegram(response, parse_mode=None)
        return

    if "location" in msg:
        _send_typing(chat_id)
        try:
            response = _handle_location(msg)
        except Exception as e:
            response = _edith_error(e, "location")
        send_telegram(response)
        return

    if "sticker" in msg:
        _send_typing(chat_id)
        try:
            response = _handle_sticker(msg)
        except Exception as e:
            response = _edith_error(e, "sticker")
        send_telegram(response, parse_mode=None)
        return

    text = msg.get("text", "").strip()
    if not text:
        return

    from session import track_query
    track_query(text)
    _dispatch_text(text, msg, chat_id)


if __name__ == "__main__":
    _cmd = sys.argv[1].lower() if len(sys.argv) > 1 else None

    if _cmd in ("poll",):
        poll_telegram()
    elif _cmd in ("start", "server"):
        start_briefing_scheduler()
        poll_telegram()
    elif _cmd in ("briefing",):
        send_weekly_briefing()
    elif _cmd is None:
        print("[EDITH Telegram Bot]")
        print("1. Poll for messages (live terminal)")
        print("2. Send weekly briefing now")
        print("3. Start scheduler + polling")
        choice = input(">> ").strip()
        if choice == "1":
            poll_telegram()
        elif choice == "2":
            send_weekly_briefing()
        elif choice == "3":
            start_briefing_scheduler()
            poll_telegram()
        else:
            print("Usage: python telegram_bot.py [poll|start|briefing]")
    else:
        print(f"Unknown command: {_cmd}")
        sys.exit(1)
