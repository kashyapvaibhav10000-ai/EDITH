"""
EDITH Telegram Bot — Full intent routing + scheduled weekly briefings.
Turns your Telegram into a live EDITH terminal from your phone.
"""

import os
import vault
import time
import threading
from collections import defaultdict
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

TOKEN = vault.get_secret("TELEGRAM_TOKEN", "") or os.getenv("TELEGRAM_TOKEN", "")
CHAT_ID = vault.get_secret("TELEGRAM_CHAT_ID", "") or os.getenv("TELEGRAM_CHAT_ID", "")

# Per-sender rate limit: max 10 messages per 60 seconds
_TG_RATE_LIMIT = 10
_TG_RATE_WINDOW = 60
_tg_rate_cache: dict = defaultdict(list)  # chat_id → [timestamps]

# Module-level HITL state: message_id of the pending HITL confirmation message
_hitl_msg_id: int | None = None

def _tg_is_rate_limited(chat_id: str) -> bool:
    now = time.time()
    timestamps = _tg_rate_cache[chat_id]
    # Drop old entries outside window
    _tg_rate_cache[chat_id] = [t for t in timestamps if now - t < _TG_RATE_WINDOW]
    if len(_tg_rate_cache[chat_id]) >= _TG_RATE_LIMIT:
        return True
    _tg_rate_cache[chat_id].append(now)
    return False


def _edith_error(e: Exception, context_hint: str = "") -> str:
    """Format any exception into an EDITH-voiced error string.

    Logs the exception at ERROR level, caps the message at 120 chars,
    and never exposes raw traceback frames to the user.
    """
    log.error(f"EDITH error: {e}", exc_info=True)
    err = str(e)
    if len(err) > 120:
        err = err[:120] + "…"
    hint = f" ({context_hint})" if context_hint else ""
    return f"Hit a snag on my end{hint}, Boss. {err} Want me to try a different approach?"


def send_telegram_placeholder(text: str = "⏳ Thinking...") -> int | None:
    """Send a placeholder message and return its message_id for later editing."""
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
    """Edit an existing Telegram message in-place. Used for streaming updates."""
    token = TOKEN or os.getenv("TELEGRAM_TOKEN", "")
    chat_id = CHAT_ID or os.getenv("TELEGRAM_CHAT_ID", "")
    if not token or not chat_id or not message_id:
        return False
    url = f"https://api.telegram.org/bot{token}/editMessageText"
    # Telegram edit limit: 4096 chars per message
    text = text[:4000]
    payload = {"chat_id": chat_id, "message_id": message_id, "text": text}
    if parse_mode:
        payload["parse_mode"] = parse_mode
    try:
        r = req.post(url, json=payload, timeout=10)
        if r.status_code == 200:
            return True
        # 400 "message is not modified" is fine — content unchanged
        if r.status_code == 400 and "not modified" in r.text:
            return True
        log.warning(f"Edit message failed: {r.status_code} {r.text[:100]}")
        return False
    except Exception as e:
        log.warning(f"Edit message error: {e}")
        return False


def send_telegram(message: str, parse_mode: str = "Markdown") -> bool:
    """Send a message to the user's Telegram."""
    token = TOKEN or os.getenv("TELEGRAM_TOKEN", "")
    chat_id = CHAT_ID or os.getenv("TELEGRAM_CHAT_ID", "")
    if not token or not chat_id:
        log.error("TELEGRAM_TOKEN or TELEGRAM_CHAT_ID not set in .env")
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
    """Send typing indicator to Telegram. Swallows errors silently."""
    token = TOKEN or os.getenv("TELEGRAM_TOKEN", "")
    if not token or not chat_id:
        return
    url = f"https://api.telegram.org/bot{token}/sendChatAction"
    try:
        req.post(url, json={"chat_id": chat_id, "action": "typing"}, timeout=5)
    except Exception as e:
        log.warning(f"Typing indicator failed: {e}")


def _build_reply_context(msg: dict, user_input: str) -> str:
    """Prepend reply-to context if the message is a reply to another message."""
    reply_msg = msg.get("reply_to_message", {})
    quoted = reply_msg.get("text", "").strip()
    if not quoted:
        return user_input
    if len(quoted) > 200:
        quoted = quoted[:200]
    return f'[Replying to: "{quoted}"] {user_input}'


def process_message(text: str, msg: dict = None) -> str:
    """Route a Telegram message through the full orchestrator.chat() pipeline.

    Uses the complete EDITH pipeline: memory recall, Conversation DNA, emotion/urgency
    detection, EDITH persona system prompt, skill injection, and post-turn reflection.
    Isolated per-source history ensures Telegram context stays separate from web/voice.
    """
    from intent import detect_intent
    from life_os import add_open_loop, close_open_loop
    from orchestrator import chat

    intent = detect_intent(text)
    inp = text.lower()

    # Telegram-specific shortcuts (open loops) — short-circuit before pipeline
    if "loop" in inp or "remember" in inp or "note" in inp:
        add_open_loop(text)
        return f"📝 Logged as open loop: {text}"
    if "close" in inp or "done" in inp or "resolved" in inp:
        close_open_loop(text)
        return f"✅ Attempting to close matching loop."

    # Inject reply-thread context if this is a reply to another message
    augmented_text = _build_reply_context(msg or {}, text)

    # Full orchestrator pipeline: memory + DNA + persona + LLM + post-turn reflection
    return chat(augmented_text, intent=intent, source="telegram", device="telegram")


def send_weekly_briefing():
    """Generate and send the weekly briefing via Telegram."""
    from life_os import weekly_briefing
    from cognitive_profile import update_profile
    log.info("Generating weekly briefing for Telegram...")
    briefing = weekly_briefing()
    success = send_telegram(briefing, parse_mode=None)
    if success:
        update_profile("Weekly briefing sent via Telegram", "telegram")
        log.info("Weekly briefing sent successfully")
    return success


def _handle_mcpstatus_cmd() -> str:
    """Return formatted MCP server status table for Telegram /mcpstatus command."""
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
        log.error(f"MCP status cmd error: {e}")
        return f"MCP status error: {e}"


def _handle_mcp_cmd(args: str) -> str:
    """Handle /mcp <args> from Telegram. Supports read, list, search sub-commands."""
    import re as _re
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
        path_m = _re.search(r"(/[^\s]+|\b[\w./~-]+\.\w+)", args)
        if not path_m:
            return "📄 Usage: `/mcp read /path/to/file`"
        import os as _os
        path = _os.path.expanduser(path_m.group(1))
        result = mcp_bridge.call_mcp_server("filesystem", "read_file", {"path": path})
        return f"📄 *{path}*\n\n{result[:3000]}"

    if lower.startswith("list ") or lower.startswith("ls "):
        path_m = _re.search(r"(/[^\s]+)", args)
        import os as _os
        path = _os.path.expanduser(path_m.group(1)) if path_m else os.path.expanduser("~")
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
    """Return formatted last 10 conversation turns from Telegram history."""
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
    """Clear the Telegram conversation history (in-memory and on disk)."""
    import tempfile
    from orchestrator import _source_history, TELEGRAM_JSONL
    _source_history["telegram"].clear()
    try:
        data_dir = os.path.dirname(TELEGRAM_JSONL)
        os.makedirs(data_dir, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            mode="w", delete=False, dir=data_dir, suffix=".jsonl"
        ) as tmp:
            tmp_path = tmp.name
        os.replace(tmp_path, TELEGRAM_JSONL)
        return "🗑 Telegram history cleared, Boss. Fresh start."
    except OSError as e:
        log.error(f"_handle_clear_cmd disk write failed: {e}")
        return (
            f"Cleared in memory, Boss. Disk write failed — {e}. "
            "Will try again next restart."
        )


def _handle_status_cmd() -> str:
    """Return a compact EDITH system status string (≤300 chars)."""
    from datetime import datetime

    # Active LLM provider
    try:
        from smart_router import router_status
        provider = router_status().get("active_provider", "unavailable")
    except Exception:
        provider = "unavailable"

    # Telegram history length
    try:
        from orchestrator import _source_history
        history_len = len(_source_history["telegram"])
    except Exception:
        history_len = "unavailable"

    # Memory count
    try:
        from orchestrator import smart_memory
        memory_count = smart_memory.count()
    except Exception:
        memory_count = "unavailable"

    # Current time
    now_str = datetime.now().strftime("%H:%M")

    status = (
        f"🤖 EDITH Status\n"
        f"⚡ Provider: {provider}\n"
        f"💬 Telegram turns: {history_len}\n"
        f"🧠 Memories: {memory_count}\n"
        f"🕐 {now_str}"
    )
    # Ensure we stay under 300 chars
    return status[:300]


def _answer_callback(cq_id: str, text: str = "") -> None:
    """Answer a Telegram callback query to dismiss the loading spinner."""
    token = TOKEN or os.getenv("TELEGRAM_TOKEN", "")
    if not token or not cq_id:
        return
    url = f"https://api.telegram.org/bot{token}/answerCallbackQuery"
    try:
        req.post(url, json={"callback_query_id": cq_id, "text": text}, timeout=5)
    except Exception as e:
        log.warning(f"answerCallbackQuery failed: {e}")


def _send_hitl_keyboard(msg_id: int, prompt_text: str) -> None:
    """Edit the placeholder message to show an inline Yes/No confirmation keyboard."""
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
    payload = {
        "chat_id": chat_id,
        "message_id": msg_id,
        "text": prompt_text[:4000],
        "reply_markup": reply_markup,
    }
    try:
        req.post(url, json=payload, timeout=10)
    except Exception as e:
        log.warning(f"HITL keyboard send failed: {e}")


def _handle_callback_query(cq: dict) -> None:
    """Process inline keyboard callback queries for HITL shell confirmation."""
    from intent_dispatch import get_pending_action, execute_pending_action, clear_pending_action

    global _hitl_msg_id

    cq_id  = cq.get("id", "")
    data   = cq.get("data", "")
    msg    = cq.get("message", {})
    msg_id = msg.get("message_id")

    # Dismiss the Telegram spinner immediately
    _answer_callback(cq_id, "")

    pending = get_pending_action()
    if not pending:
        log.warning("callback_query received but no pending HITL action stored")
        return

    if data == "hitl_confirm":
        try:
            result = execute_pending_action(pending)
            result_text = str(result) if result else "Done, Boss."
        except Exception as e:
            result_text = _edith_error(e, "executing the command")
        clear_pending_action()
        # Edit message with result, removing the inline keyboard
        token = TOKEN or os.getenv("TELEGRAM_TOKEN", "")
        chat_id = CHAT_ID or os.getenv("TELEGRAM_CHAT_ID", "")
        try:
            req.post(
                f"https://api.telegram.org/bot{token}/editMessageText",
                json={
                    "chat_id": chat_id,
                    "message_id": msg_id,
                    "text": result_text[:4000],
                    "reply_markup": {"inline_keyboard": []},
                },
                timeout=10,
            )
        except Exception as e:
            log.warning(f"HITL confirm edit failed: {e}")
        _hitl_msg_id = None

    elif data == "hitl_cancel":
        clear_pending_action()
        token = TOKEN or os.getenv("TELEGRAM_TOKEN", "")
        chat_id = CHAT_ID or os.getenv("TELEGRAM_CHAT_ID", "")
        try:
            req.post(
                f"https://api.telegram.org/bot{token}/editMessageText",
                json={
                    "chat_id": chat_id,
                    "message_id": msg_id,
                    "text": "Cancelled, Boss.",
                    "reply_markup": {"inline_keyboard": []},
                },
                timeout=10,
            )
        except Exception as e:
            log.warning(f"HITL cancel edit failed: {e}")
        _hitl_msg_id = None


def _handle_photo(msg: dict) -> str:
    """Download the highest-resolution photo and route it to the vision handler."""
    from context import DispatchContext
    from orchestrator import chat as _orch_chat

    token = TOKEN or os.getenv("TELEGRAM_TOKEN", "")
    caption = msg.get("caption", "").strip() or "Describe this image."
    photos  = msg.get("photo", [])
    if not photos:
        return "Couldn't find photo data in that message, Boss."

    # Telegram sends photos sorted ascending by resolution — last is highest-res
    best = photos[-1]
    file_id = best.get("file_id", "")

    # Step 1: resolve file path via getFile
    try:
        r = req.get(
            f"https://api.telegram.org/bot{token}/getFile",
            params={"file_id": file_id}, timeout=10
        )
        file_path = r.json()["result"]["file_path"]
    except Exception as e:
        log.error(f"Photo getFile failed: {e}")
        return "Couldn't download that photo, Boss. Try again?"

    # Step 2: download image bytes
    local_path = None
    try:
        import tempfile as _tmp
        dl_url = f"https://api.telegram.org/file/bot{token}/{file_path}"
        img_bytes = req.get(dl_url, timeout=30).content
        suffix = os.path.splitext(file_path)[1] or ".jpg"
        with _tmp.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            tmp.write(img_bytes)
            local_path = tmp.name
    except Exception as e:
        log.error(f"Photo download failed: {e}")
        return "Couldn't download that photo, Boss. Try again?"

    # Step 3: route to vision handler via DispatchContext
    try:
        from handlers.misc import _handle_vision
        ctx = DispatchContext(
            user_input=f"{caption} [image: {local_path}]",
            intent="vision",
            source="telegram",
            device="telegram",
            chat_fn=_orch_chat,
        )
        result = _handle_vision(ctx)
        if hasattr(result, "ok"):
            return str(result.value) if result.ok else _edith_error(Exception(result.error), "vision analysis")
        return str(result)
    except Exception as e:
        log.error(f"Vision handler failed: {e}")
        return "Vision isn't available right now, Boss."
    finally:
        if local_path:
            try:
                os.unlink(local_path)
            except Exception:
                pass


def poll_telegram():
    """Poll Telegram for incoming messages — live EDITH terminal from phone."""
    if not TOKEN or not CHAT_ID:
        print("[EDITH Telegram] Missing TELEGRAM_TOKEN or TELEGRAM_CHAT_ID in .env")
        print("  Add TELEGRAM_CHAT_ID — get yours from @userinfobot on Telegram")
        return

    from session import start_session, track_query
    from intent_dispatch import get_pending_action

    global _hitl_msg_id

    last_update_id = None
    session_id = start_session()
    print(f"[EDITH Telegram] Polling... Session: {session_id}")
    print("  Send messages from your phone → EDITH processes → replies")
    print("  Ctrl+C to stop\n")

    send_telegram("🤖 *EDITH online.* Memory loaded. Awaiting commands, Boss.")

    while True:
        try:
            url = f"https://api.telegram.org/bot{TOKEN}/getUpdates"
            params = {"timeout": 10, "offset": last_update_id}
            r = req.get(url, params=params, timeout=15)
            updates = r.json().get("result", [])

            for update in updates:
                last_update_id = update["update_id"] + 1

                # ── Inline keyboard callback queries (HITL confirm/cancel) ──
                if "callback_query" in update:
                    _handle_callback_query(update["callback_query"])
                    continue

                msg     = update.get("message", {})
                chat_id = str(msg.get("chat", {}).get("id", ""))

                # Security: only the owner's chat_id is accepted
                if not chat_id or chat_id != str(CHAT_ID):
                    if chat_id:
                        log.warning(f"Rejected message from unauthorized chat_id={chat_id}")
                    continue

                if _tg_is_rate_limited(chat_id):
                    log.warning(f"Telegram rate limit hit for chat_id={chat_id}")
                    continue

                # ── Photo messages ──
                if "photo" in msg:
                    _send_typing(chat_id)
                    ph_msg_id = send_telegram_placeholder("⏳ Analysing image, Boss...")
                    try:
                        response = _handle_photo(msg)
                    except Exception as e:
                        response = _edith_error(e, "photo analysis")
                    if ph_msg_id:
                        if not edit_telegram_message(ph_msg_id, response, parse_mode="Markdown"):
                            edit_telegram_message(ph_msg_id, response)
                    else:
                        send_telegram(response, parse_mode=None)
                    continue

                # ── Text messages ──
                text = msg.get("text", "").strip()
                if not text:
                    continue

                log.info(f"Telegram received: {text[:80]}")
                track_query(text)

                tl = text.lower()

                # Built-in commands — no pipeline, no placeholder
                if tl in ["/start", "start"]:
                    send_telegram("🤖 *EDITH online.* Ready, Boss.")
                    continue

                if tl == "/history":
                    send_telegram(_handle_history_cmd(), parse_mode=None)
                    continue

                if tl == "/clear":
                    send_telegram(_handle_clear_cmd(), parse_mode=None)
                    continue

                if tl == "/status":
                    send_telegram(_handle_status_cmd(), parse_mode=None)
                    continue

                if tl == "/mcpstatus":
                    send_telegram(_handle_mcpstatus_cmd())
                    continue

                if tl.startswith("/mcp"):
                    send_telegram(_handle_mcp_cmd(text[4:].strip()))
                    continue

                # ── Full EDITH pipeline ──
                _send_typing(chat_id)
                msg_id = send_telegram_placeholder("⏳ On it, Boss...")
                try:
                    response = process_message(text, msg)
                    pending  = get_pending_action()
                    if pending and msg_id:
                        # HITL confirmation needed — show inline keyboard
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

            time.sleep(2)

        except KeyboardInterrupt:
            send_telegram("🔴 EDITH going offline. Goodbye, Boss.")
            print("\n[EDITH Telegram] Stopped.")
            break
        except Exception as e:
            log.error(f"Polling error: {e}")
            time.sleep(10)


def handle_telegram_update(update: dict) -> None:
    """Process a single Telegram update dict (webhook mode entry point)."""
    from session import track_query
    from intent_dispatch import get_pending_action

    global _hitl_msg_id

    # ── Inline keyboard callback queries (HITL confirm/cancel) ──
    if "callback_query" in update:
        _handle_callback_query(update["callback_query"])
        return

    msg     = update.get("message", {})
    chat_id = str(msg.get("chat", {}).get("id", ""))

    # Security: only the owner's chat_id is accepted
    if not chat_id or chat_id != str(CHAT_ID):
        if chat_id:
            log.warning(f"Webhook: rejected message from unauthorized chat_id={chat_id}")
        return

    if _tg_is_rate_limited(chat_id):
        log.warning(f"Telegram webhook rate limit hit for chat_id={chat_id}")
        return

    # ── Photo messages ──
    if "photo" in msg:
        _send_typing(chat_id)
        ph_msg_id = send_telegram_placeholder("⏳ Analysing image, Boss...")
        try:
            response = _handle_photo(msg)
        except Exception as e:
            response = _edith_error(e, "photo analysis")
        if ph_msg_id:
            if not edit_telegram_message(ph_msg_id, response, parse_mode="Markdown"):
                edit_telegram_message(ph_msg_id, response)
        else:
            send_telegram(response, parse_mode=None)
        return

    # ── Text messages ──
    text = msg.get("text", "").strip()
    if not text:
        return

    log.info(f"Telegram webhook received: {text[:80]}")
    track_query(text)

    tl = text.lower()

    # Built-in commands — no pipeline, no placeholder
    if tl in ["/start", "start"]:
        send_telegram("🤖 *EDITH online.* Ready, Boss.")
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

    # ── Full EDITH pipeline ──
    _send_typing(chat_id)
    msg_id = send_telegram_placeholder("⏳ On it, Boss...")
    try:
        response = process_message(text, msg)
        pending  = get_pending_action()
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


def send_drift_alert():
    """Check for drift and alert on Telegram if detected."""
    from cognitive_profile import detect_drift, get_recent_queries
    recent = get_recent_queries(10)
    if len(recent) < 5:
        return  # Not enough data yet
    log.info("Running drift check...")
    drift_report = detect_drift()
    drift_lower = drift_report.lower()
    # Only alert if drift is detected (not aligned)
    if any(w in drift_lower for w in ["drift", "not aligned", "misalign", "off track", "warning"]):
        send_telegram(f"⚠️ *EDITH DRIFT ALERT*\n\n{drift_report}", parse_mode="Markdown")
        log.warning(f"Drift alert sent: {drift_report[:80]}")


def start_briefing_scheduler():
    """Run weekly briefing + drift alerts in background thread."""
    import schedule

    schedule.every().sunday.at("08:00").do(send_weekly_briefing)
    schedule.every(6).hours.do(send_drift_alert)
    log.info("Scheduler active: briefing=Sunday 08:00, drift check=every 6h")

    def _run():
        while True:
            schedule.run_pending()
            time.sleep(60)

    t = threading.Thread(target=_run, daemon=True)
    t.start()
    return t


if __name__ == "__main__":
    import sys

    # Support CLI args for non-interactive server startup:
    #   python telegram_bot.py poll        — poll only
    #   python telegram_bot.py start       — scheduler + polling (default for server)
    #   python telegram_bot.py briefing    — send weekly briefing now and exit
    # No args → interactive menu (local dev only)

    _cmd = sys.argv[1].lower() if len(sys.argv) > 1 else None

    if _cmd in ("poll",):
        poll_telegram()
    elif _cmd in ("start", "server"):
        start_briefing_scheduler()
        poll_telegram()
    elif _cmd in ("briefing",):
        send_weekly_briefing()
    elif _cmd is None:
        # Interactive menu — local dev
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
        print("Usage: python telegram_bot.py [poll|start|briefing]")
        sys.exit(1)
