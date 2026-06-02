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

def _tg_is_rate_limited(chat_id: str) -> bool:
    now = time.time()
    timestamps = _tg_rate_cache[chat_id]
    # Drop old entries outside window
    _tg_rate_cache[chat_id] = [t for t in timestamps if now - t < _TG_RATE_WINDOW]
    if len(_tg_rate_cache[chat_id]) >= _TG_RATE_LIMIT:
        return True
    _tg_rate_cache[chat_id].append(now)
    return False


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


def process_message(text: str) -> str:
    """Route a Telegram message through EDITH's full intent system via DispatchContext."""
    from intent import detect_intent
    from life_os import add_open_loop, close_open_loop
    from context import DispatchContext
    from intent_dispatch import dispatch
    from orchestrator import chat

    intent = detect_intent(text)
    inp = text.lower()

    # Telegram-specific shortcuts (open loops)
    if "loop" in inp or "remember" in inp or "note" in inp:
        add_open_loop(text)
        return f"📝 Logged as open loop: {text}"
    if "close" in inp or "done" in inp or "resolved" in inp:
        close_open_loop(text)
        return f"✅ Attempting to close matching loop."

    # Dispatch through unified table
    ctx = DispatchContext(
        user_input=text,
        intent=intent,
        source="telegram",
        chat_fn=chat,
    )
    return dispatch(ctx)


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


def poll_telegram():
    """Poll Telegram for incoming messages — live EDITH terminal from phone."""
    if not TOKEN or not CHAT_ID:
        print("[EDITH Telegram] Missing TELEGRAM_TOKEN or TELEGRAM_CHAT_ID in .env")
        print("  Add TELEGRAM_CHAT_ID — get yours from @userinfobot on Telegram")
        return

    from session import start_session, track_query

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
                msg = update.get("message", {})
                text = msg.get("text", "").strip()
                chat_id = str(msg.get("chat", {}).get("id", ""))

                # Security: reject messages from anyone other than the owner
                if not chat_id or chat_id != str(CHAT_ID):
                    if chat_id:
                        log.warning(f"Rejected message from unauthorized chat_id={chat_id}")
                    continue

                if not text:
                    continue

                if _tg_is_rate_limited(chat_id):
                    log.warning(f"Telegram rate limit hit for chat_id={chat_id}")
                    continue

                log.info(f"Telegram received: {text[:80]}")
                track_query(text)

                if text.lower() in ["/start", "start"]:
                    send_telegram("🤖 *EDITH online.* Ready, Boss.")
                    continue

                if text.lower() == "/mcpstatus":
                    send_telegram(_handle_mcpstatus_cmd())
                    continue

                if text.lower().startswith("/mcp"):
                    args = text[4:].strip()
                    send_telegram(_handle_mcp_cmd(args))
                    continue

                # Process through EDITH — streaming pattern:
                # send placeholder immediately, edit in-place when done
                msg_id = send_telegram_placeholder("⏳ On it, Boss...")
                try:
                    response = process_message(text)
                    if msg_id:
                        # Try Markdown first; fall back to plain text on parse error
                        if not edit_telegram_message(msg_id, response, parse_mode="Markdown"):
                            edit_telegram_message(msg_id, response)
                    else:
                        send_telegram(response, parse_mode=None)
                except Exception as e:
                    log.error(f"Processing failed: {e}")
                    err_msg = f"Something went wrong: {e}"
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
    from session import start_session, track_query
    msg = update.get("message", {})
    text = msg.get("text", "").strip()
    chat_id = str(msg.get("chat", {}).get("id", ""))

    # Security: reject messages from anyone other than the owner
    if not chat_id or chat_id != str(CHAT_ID):
        if chat_id:
            log.warning(f"Webhook: rejected message from unauthorized chat_id={chat_id}")
        return

    if not text:
        return

    if _tg_is_rate_limited(chat_id):
        log.warning(f"Telegram webhook rate limit hit for chat_id={chat_id}")
        return

    log.info(f"Telegram webhook received: {text[:80]}")
    track_query(text)

    if text.lower() in ["/start", "start"]:
        send_telegram("🤖 *EDITH online.* Ready, Boss.")
        return

    if text.lower() == "/mcpstatus":
        send_telegram(_handle_mcpstatus_cmd())
        return

    if text.lower().startswith("/mcp"):
        send_telegram(_handle_mcp_cmd(text[4:].strip()))
        return

    msg_id = send_telegram_placeholder("⏳ On it, Boss...")
    try:
        response = process_message(text)
        if msg_id:
            if not edit_telegram_message(msg_id, response, parse_mode="Markdown"):
                edit_telegram_message(msg_id, response)
        else:
            send_telegram(response, parse_mode=None)
    except Exception as e:
        log.error(f"Webhook processing failed: {e}")
        err_msg = f"Something went wrong: {e}"
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
        print("Run with: python telegram_bot.py")
