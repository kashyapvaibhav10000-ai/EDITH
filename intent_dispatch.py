"""
EDITH Intent Dispatch Table — Phase 4 Architecture Refactor

Central dispatch table. Each handler receives a DispatchContext and returns a Result.
No circular imports. No global state. No elif chains.

Usage:
    from context import DispatchContext
    from intent_dispatch import dispatch
    ctx = DispatchContext(user_input="...", intent="weather", chat_fn=chat, source="widget")
    reply = dispatch(ctx)
"""

import re
import os
import datetime
import subprocess
import shlex
import threading

from config import get_logger
from context import DispatchContext
from errors import Result

log = get_logger("intent_dispatch")


# ──────────────────────────────────────────────
# Shared State: HITL Pending Action
# ──────────────────────────────────────────────
_pending_action = None
_action_lock = threading.Lock()


def get_pending_action():
    with _action_lock:
        return _pending_action


def set_pending_action(action):
    global _pending_action
    with _action_lock:
        _pending_action = action


def clear_pending_action():
    global _pending_action
    with _action_lock:
        _pending_action = None


# ──────────────────────────────────────────────
# Extraction Helpers
# ──────────────────────────────────────────────
def _extract_date(text):
    lower = text.lower()
    today = datetime.date.today()
    if "tomorrow" in lower or "tommorrow" in lower:
        return (today + datetime.timedelta(days=1)).strftime("%Y-%m-%d")
    if "today" in lower:
        return today.strftime("%Y-%m-%d")
    if "day after tomorrow" in lower:
        return (today + datetime.timedelta(days=2)).strftime("%Y-%m-%d")
    m = re.search(r"(\d{4})-(\d{2})-(\d{2})", text)
    if m:
        return m.group(0)
    m = re.search(r"(\d{1,2})[/\-](\d{1,2})", text)
    if m:
        day, month = int(m.group(1)), int(m.group(2))
        return f"{today.year}-{month:02d}-{day:02d}"
    days_map = {"monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3,
                "friday": 4, "saturday": 5, "sunday": 6}
    for name, num in days_map.items():
        if name in lower:
            days_ahead = num - today.weekday()
            if days_ahead <= 0:
                days_ahead += 7
            return (today + datetime.timedelta(days=days_ahead)).strftime("%Y-%m-%d")
    return today.strftime("%Y-%m-%d")


def _extract_time(text):
    m = re.search(r"(\d{1,2})(?::(\d{2}))?\s*(am|pm)", text.lower())
    if m:
        hour = int(m.group(1))
        minute = int(m.group(2) or 0)
        if m.group(3) == "pm" and hour != 12:
            hour += 12
        if m.group(3) == "am" and hour == 12:
            hour = 0
        return f"{hour:02d}:{minute:02d}"
    m = re.search(r"(\d{1,2}):(\d{2})", text)
    if m:
        return f"{int(m.group(1)):02d}:{int(m.group(2)):02d}"
    return None


def _extract_event_title(text):
    cleaned = re.sub(r"(add|create|schedule|set|make|book|remind me|to|for|at|on|tomorrow|today|am|pm|\d{1,2}:\d{2}|\d{1,2}\s*(am|pm))", "", text, flags=re.IGNORECASE).strip()
    cleaned = re.sub(r"^(a|an|the|about|for|to)\s+", "", cleaned, flags=re.IGNORECASE).strip()
    return cleaned.capitalize() if cleaned and len(cleaned) > 2 else "New Event"


def _extract_filepath(text):
    m = re.search(r"(/[^\s]+\.\w+)", text)
    if m:
        return m.group(1)
    m = re.search(r"(~/[^\s]+)", text)
    if m:
        return os.path.expanduser(m.group(1))
    return None


def _extract_phone_number(text):
    m = re.search(r"(\+?\d[\d\s\-]{8,14}\d)", text)
    return re.sub(r"[\s\-]", "", m.group(1)) if m else None


def _extract_sms_body(text):
    m = re.search(r"(?:saying|message|text|that says|with)\s+[\"']?(.+?)[\"']?\s*$", text, re.IGNORECASE)
    return m.group(1).strip() if m else None


# ──────────────────────────────────────────────
# Safety Helpers
# ──────────────────────────────────────────────
_SAFE_COMMANDS = {
    "ls", "ll", "dir", "cat", "head", "tail", "wc", "df", "du", "free",
    "uname", "whoami", "hostname", "date", "cal", "uptime", "which",
    "file", "stat", "pwd", "echo", "tree", "find", "locate",
    "neofetch", "lsb_release", "lscpu", "lsusb", "lspci",
}


def _is_safe_command(cmd):
    base_cmd = cmd.strip().split()[0] if cmd.strip() else ""
    base_cmd = os.path.basename(base_cmd)
    if any(c in cmd for c in ['>', '|', '&&', '||', ';', '`', '$(']):
        return False
    return base_cmd in _SAFE_COMMANDS


def _friendly_error(intent, error):
    err = str(error).lower()
    if "timeout" in err or "timed out" in err:
        return "That's taking too long right now. The service might be busy — try again in a moment, Boss."
    if "connection" in err or "refused" in err or "unreachable" in err:
        return "I'm having trouble connecting to that service. It might be offline or your internet could be down."
    if "not found" in err or "no such file" in err:
        return "I couldn't find what I was looking for. Double-check the path or name and try again."
    if "permission" in err or "denied" in err:
        return "I don't have permission to do that. You might need to run it with elevated privileges."
    log.error(f"Intent handler [{intent}] error: {error}")
    return "Something went wrong on my end, Boss. Want me to try a different approach?"


# ──────────────────────────────────────────────
# Intent Handlers (each takes DispatchContext, returns Result)
# ──────────────────────────────────────────────

def _handle_weather(ctx) -> Result:
    try:
        from weather import get_current_weather, format_weather
        w = get_current_weather()
        if w.ok:
            return Result.success(format_weather(w.value))
        return Result.success("Couldn't fetch weather data right now.")
    except Exception as e:
        return Result.from_exception(e)


def _handle_calendar_today(ctx) -> Result:
    try:
        from calendar_reader import get_today_briefing
        return get_today_briefing()
    except Exception as e:
        return Result.from_exception(e)


def _handle_calendar_week(ctx) -> Result:
    try:
        from calendar_reader import get_week_briefing
        return get_week_briefing()
    except Exception as e:
        return Result.from_exception(e)


def _handle_calendar_create(ctx) -> Result:
    try:
        from calendar_reader import create_event
        date_str = _extract_date(ctx.user_input)
        time_str = _extract_time(ctx.user_input)
        title = _extract_event_title(ctx.user_input)
        r = create_event(title, date_str, time_str)
        return Result.success(f"📅 {r.value}") if r.ok else r
    except Exception as e:
        return Result.from_exception(e)


def _handle_email(ctx) -> Result:
    try:
        from email_reader import check_inbox
        return check_inbox(limit=5, unread_only=False)
    except Exception as e:
        return Result.from_exception(e)


def _handle_unread_email(ctx) -> Result:
    try:
        from email_reader import check_inbox
        return check_inbox(limit=5, unread_only=True)
    except Exception as e:
        return Result.from_exception(e)


def _handle_search(ctx) -> Result:
    try:
        from search import web_search, format_results
        results_r = web_search(ctx.user_input)
        results = results_r.value if results_r.ok else []
        search_text = format_results(results)
        if search_text and "error" not in search_text.lower() and "no results" not in search_text.lower():
            today_str = datetime.datetime.now().strftime('%A, %d %B %Y')
            prompt = (
                f"Current Date: {today_str}\n\nUser Query: {ctx.user_input}\n\n"
                f"Search results:\n{search_text}\n\n"
                f"IMPORTANT: Use the Current Date to verify words like 'today'!\n"
                f"Answer with EXACT facts — scores, names, numbers, dates. "
                f"No fluff, no 'based on search results'. Just the answer."
            )
            return Result.success(ctx.chat_fn(prompt, intent="search"))
        return Result.success("I searched but couldn't find reliable results right now. Want me to try a different query, Boss?")
    except Exception as e:
        return Result.from_exception(e)


def _handle_call(ctx) -> Result:
    try:
        number = _extract_phone_number(ctx.user_input)
        if number:
            from phone import initiate_call
            initiate_call(number)
            return Result.success(f"📞 Calling {number} now.")
        return Result.success("📞 Who should I call? Give me a number.")
    except Exception as e:
        return Result.from_exception(e)


def _handle_sms(ctx) -> Result:
    try:
        from phone import send_sms
        number = _extract_phone_number(ctx.user_input)
        body = _extract_sms_body(ctx.user_input)
        if not body:
            m = re.search(r"(?:say|saying)\s+(.+)", ctx.user_input, re.IGNORECASE)
            body = m.group(1).strip() if m else None
        if not number and not body:
            return Result.success("📱 What do you want to text? Try: 'send sms to +91XXXXXXXXXX saying hello'")
        if not number:
            return Result.success(f'📱 Got the message: "{body}". Who should I send it to?')
        if not body:
            return Result.success(f"📱 Got number {number}. What should the message say?")
        send_sms(number, body)
        return Result.success(f'📱 SMS sent to {number}: "{body}"')
    except Exception as e:
        return Result.from_exception(e)


def _handle_phone(ctx) -> Result:
    try:
        from phone import ring_phone, get_notifications, phone_status
        lower = ctx.user_input.lower()
        if "ring" in lower or "find" in lower:
            ring_phone()
            return Result.success("📱 Ringing your phone now!")
        elif "notification" in lower:
            r = get_notifications()
            return Result.success(f"📱 {r.value if r.ok else r.error}")
        elif "battery" in lower:
            from phone import get_battery
            r = get_battery()
            return Result.success(f"📱 {r.value if r.ok else r.error}")
        r = phone_status()
        return Result.success(f"📱 {r.value if r.ok else r.error}")
    except Exception as e:
        return Result.from_exception(e)


def _handle_vision(ctx) -> Result:
    try:
        from vision import analyze_screenshot
        question = ctx.user_input if len(ctx.user_input.split()) > 3 else "What is on my screen right now?"
        r = analyze_screenshot(question)
        return Result.success(f"👁️ {r.value}") if r.ok else r
    except Exception as e:
        return Result.from_exception(e)


def _handle_shell(ctx) -> Result:
    try:
        cmd = ctx.user_input
        for prefix in ["run ", "execute ", "terminal ", "shell ", "command "]:
            if cmd.lower().startswith(prefix):
                cmd = cmd[len(prefix):].strip()
                break
        cmd = cmd.strip("\"'`")
        if not cmd or cmd.lower() in ["run", "execute", "command", "shell"]:
            return Result.success("What command should I run, Boss? Something like 'run ls -la /home/vaibhav'.")

        if _is_safe_command(cmd):
            try:
                result = subprocess.run(shlex.split(cmd), capture_output=True, text=True, timeout=15, cwd="/home/vaibhav")
                output = (result.stdout or result.stderr or "").strip()
                if not output:
                    return Result.success(f"Ran `{cmd}` — no output returned.")
                if len(output) < 500:
                    return Result.success(f"Here's what I got:\n\n{output}")
                return Result.success(ctx.chat_fn(
                    f"User asked: {ctx.user_input}\n\nCommand `{cmd}` returned:\n{output[:2000]}\n\nSummarize naturally. Be concise.",
                    intent="shell"
                ))
            except subprocess.TimeoutExpired:
                return Result.success("That command is taking too long. It might be stuck — want me to try with a longer timeout?")
            except Exception as e:
                return Result.success(_friendly_error("shell", e))

        # Dangerous: HITL confirmation
        set_pending_action({"type": "shell", "cmd": cmd})
        return Result.success(f"I've prepared this command:\n\n`{cmd}`\n\n⚠️ This could modify your system. Type **YES** to run or **NO** to cancel.")
    except Exception as e:
        return Result.from_exception(e)


def _handle_file_query(ctx) -> Result:
    try:
        dir_map = {
            "download": "/home/vaibhav/Downloads", "document": "/home/vaibhav/Documents",
            "desktop": "/home/vaibhav/Desktop", "home": "/home/vaibhav",
            "picture": "/home/vaibhav/Pictures", "video": "/home/vaibhav/Videos",
            "music": "/home/vaibhav/Music",
        }
        target_dir = None
        lower = ctx.user_input.lower()
        for key, path in dir_map.items():
            if key in lower:
                target_dir = path
                break
        if not target_dir:
            path_match = re.search(r'(/[\w/.-]+)', ctx.user_input)
            target_dir = os.path.expanduser(path_match.group(1)) if path_match else "/home/vaibhav"

        if not os.path.isdir(target_dir):
            return Result.success(f"Can't find `{target_dir}`. Sure it exists?")

        items = os.listdir(target_dir)
        if not items:
            return Result.success(f"`{target_dir}` is empty.")

        folders = sorted([f for f in items if os.path.isdir(os.path.join(target_dir, f))])
        files = sorted([f for f in items if os.path.isfile(os.path.join(target_dir, f))])

        file_groups = {}
        ext_labels = {
            '.pdf': '📄 PDFs', '.docx': '📝 Documents', '.doc': '📝 Documents',
            '.xlsx': '📊 Spreadsheets', '.xls': '📊 Spreadsheets', '.csv': '📊 Spreadsheets',
            '.png': '🖼️ Images', '.jpg': '🖼️ Images', '.jpeg': '🖼️ Images',
            '.gif': '🖼️ Images', '.webp': '🖼️ Images', '.svg': '🖼️ Images',
            '.mp4': '🎬 Videos', '.mkv': '🎬 Videos', '.avi': '🎬 Videos',
            '.mp3': '🎵 Audio', '.ogg': '🎵 Audio', '.wav': '🎵 Audio',
            '.flac': '🎵 Audio', '.m4a': '🎵 Audio',
            '.zip': '📦 Archives', '.tar': '📦 Archives', '.gz': '📦 Archives',
            '.py': '💻 Code', '.js': '💻 Code', '.ts': '💻 Code',
            '.html': '💻 Code', '.css': '💻 Code',
            '.json': '⚙️ Config', '.yaml': '⚙️ Config', '.yml': '⚙️ Config',
            '.txt': '📃 Text', '.md': '📃 Text',
        }
        for f in files:
            ext = os.path.splitext(f)[1].lower()
            label = ext_labels.get(ext, '📎 Other')
            file_groups.setdefault(label, []).append(f)

        dir_name = os.path.basename(target_dir) or target_dir
        parts = [f"📂 **{dir_name}** — {len(items)} items\n"]
        if folders:
            parts.append(f"**📁 Folders ({len(folders)})**")
            for i, f in enumerate(folders, 1):
                parts.append(f"  {i}. {f}/")
            parts.append("")
        for label, group_files in sorted(file_groups.items(), key=lambda x: -len(x[1])):
            parts.append(f"**{label} ({len(group_files)})**")
            for i, f in enumerate(group_files, 1):
                try:
                    size = os.path.getsize(os.path.join(target_dir, f))
                    size_str = f"{size} B" if size < 1024 else (f"{size/1024:.0f} KB" if size < 1048576 else f"{size/1048576:.1f} MB")
                except Exception:
                    size_str = ""
                parts.append(f"  {i}. {f}  `{size_str}`" if size_str else f"  {i}. {f}")
            parts.append("")
        return Result.success("\n".join(parts))
    except PermissionError as e:
        return Result.failure(f"Don't have permission to access that directory.", error_type="permission")
    except Exception as e:
        return Result.from_exception(e)


def _handle_create_file(ctx) -> Result:
    try:
        filepath = _extract_filepath(ctx.user_input)
        if not filepath:
            return Result.success("📁 I need a file path. Try: 'create file /home/vaibhav/notes/todo.txt'")
        content_match = re.search(r"(?:with content|containing|with text|content)\s+(.+)", ctx.user_input, re.IGNORECASE | re.DOTALL)
        content = content_match.group(1).strip() if content_match else "(empty)"
        set_pending_action({"type": "create_file", "path": filepath, "content": content})
        return Result.success(f"📁 File Creation Request:\nPath: {filepath}\nContent length: {len(content)} chars\n\n⚠️ Proceed? Type YES or NO.")
    except Exception as e:
        return Result.from_exception(e)


def _handle_delete_file(ctx) -> Result:
    try:
        filepath = _extract_filepath(ctx.user_input)
        if not filepath:
            return Result.success("🗑️ I need a file path. Try: 'delete file /home/vaibhav/old_notes.txt'")
        set_pending_action({"type": "delete_file", "path": filepath})
        return Result.success(f"🗑️ Deletion Request:\nPath: {filepath}\n\n⚠️ Proceed with permanently deleting this file? Type YES or NO.")
    except Exception as e:
        return Result.from_exception(e)


def _handle_rag(ctx) -> Result:
    try:
        from rag import build_index, query_rag
        idx_r = build_index()
        if not idx_r.ok:
            return Result.success(f"📚 {idx_r.error}")
        r = query_rag(ctx.user_input, idx_r.value)
        return r
    except Exception as e:
        return Result.from_exception(e)


def _handle_data_analysis(ctx) -> Result:
    try:
        filepath = _extract_filepath(ctx.user_input)
        if not filepath:
            return Result.success("📊 I need a file path. Try: 'analyze /home/vaibhav/data.csv what month had highest sales'")
        question = ctx.user_input.replace(filepath, "").strip()
        for word in ["analyze", "analyse", "read", "load", "open", "chart", "graph", "plot"]:
            question = re.sub(rf"\b{word}\b", "", question, flags=re.IGNORECASE).strip()
        from data_analyst import analyze_file
        r = analyze_file(filepath, question if question else None, "bar")
        return Result.success(f"📊 {r.value}") if r.ok else r
    except Exception as e:
        return Result.from_exception(e)


def _handle_agent(ctx) -> Result:
    try:
        from agent import plan_task
        task = ctx.user_input
        for prefix in ["agent ", "automate ", "plan "]:
            if task.lower().startswith(prefix):
                task = task[len(prefix):].strip()
        plan = plan_task(task)
        steps = []
        for line in plan.split("\n"):
            line = line.strip()
            if line and line[0].isdigit() and "." in line:
                step = line.split(".", 1)[-1].strip()
                if step:
                    steps.append(step)
        set_pending_action({"type": "agent", "task": task, "steps": steps})
        return Result.success(f"🤖 Agent Plan for '{task}':\n\n{plan}\n\n⚠️ Proceed with executing Phase 1? Type YES or NO.")
    except Exception as e:
        return Result.failure(f"🤖 Agent planning failed: {e}")


def _handle_council(ctx) -> Result:
    try:
        from council import run_council
        return Result.success(f"🏛️ Council of Minds:\n\n{run_council(ctx.user_input)}")
    except Exception as e:
        return Result.from_exception(e)


def _handle_decision(ctx) -> Result:
    try:
        from life_os import simulate_decision
        return Result.success(f"🔮 Decision Simulation:\n\n{simulate_decision(ctx.user_input)}")
    except Exception as e:
        return Result.from_exception(e)


def _handle_briefing(ctx) -> Result:
    try:
        from life_os import weekly_briefing
        return Result.success(f"📋 Weekly Briefing:\n\n{weekly_briefing()}")
    except Exception as e:
        return Result.from_exception(e)


def _handle_profile(ctx) -> Result:
    try:
        from cognitive_profile import get_full_profile, detect_drift, get_prime_directive, set_prime_directive
        lower = ctx.user_input.lower()
        if "drift" in lower:
            return Result.success(f"🧭 Drift Check:\n\n{detect_drift()}")
        if "prime directive" in lower or "north star" in lower:
            if "set" in lower or "change" in lower:
                new = re.sub(r"(set|change|update|my)\s*(prime directive|north star)\s*(to|as)?\s*", "", ctx.user_input, flags=re.IGNORECASE).strip()
                if new:
                    set_prime_directive(new)
                    return Result.success(f"🎯 Prime directive updated to: {new}")
                return Result.success("🎯 What should the new prime directive be?")
            return Result.success(f"🎯 Prime Directive: {get_prime_directive()}")
        return Result.success(f"📊 Cognitive Profile:\n\n{get_full_profile()}")
    except Exception as e:
        return Result.from_exception(e)


def _handle_self_improve(ctx) -> Result:
    try:
        from self_improve import run_self_improvement
        from life_os import add_open_loop
        proposal = run_self_improvement()
        if proposal:
            add_open_loop(f"Review upgrade: {proposal[:100]}")
            return Result.success(f"🧬 Self-Improvement Proposal:\n\n{proposal}\n\n✅ Added to open loops for review.")
        return Result.success("🧬 No upgrade proposals generated (check internet).")
    except Exception as e:
        return Result.from_exception(e)


def _handle_session_end(ctx) -> Result:
    return Result.success("Session noted. Goodbye, Boss. All conversation history has been saved. 👋")


def _handle_wake(ctx) -> Result:
    return Result.success("I'm here, Boss. What do you need?")


def _handle_whatsapp(ctx) -> Result:
    try:
        from whatsapp import is_available, get_unread, draft_message, send_message, BRIDGE_URL
        lower = ctx.user_input.lower()
        if not is_available():
            if BRIDGE_URL:
                try:
                    import requests
                    r = requests.get(f"{BRIDGE_URL}/status", timeout=3)
                    if r.status_code == 200 and not r.json().get("ready"):
                        return Result.success("📱 WhatsApp bridge is running but not authenticated. Scan the QR code in the bridge terminal.")
                except Exception:
                    pass
                return Result.success("📱 WhatsApp bridge is not reachable. Make sure the bridge server is running.")
            return Result.success("📱 WhatsApp bridge not configured. Set WHATSAPP_BRIDGE_URL in .env.")
        if "unread" in lower or "check" in lower:
            return Result.success(f"📱 {get_unread()}")
        contact = _extract_phone_number(ctx.user_input)
        body = _extract_sms_body(ctx.user_input)
        if not contact:
            return Result.success("📱 Who should I WhatsApp? Try: 'send WhatsApp to +91XXXXXXXXXX saying hello'")
        set_pending_action({"type": "whatsapp", "contact": contact, "message": body or ""})
        return Result.success(draft_message(contact, body or ""))
    except Exception as e:
        return Result.from_exception(e)


def _handle_mcp(ctx) -> Result:
    try:
        import mcp_bridge
        lower = ctx.user_input.lower()

        if re.search(r"\b(status|servers?|list servers?)\b", lower) and "mcp" in lower:
            status = mcp_bridge.get_mcp_status()
            if not status:
                return Result.success("No MCP servers configured.")
            lines = ["🔌 **MCP Server Status**\n"]
            for name, info in status.items():
                state = "✅ enabled" if info["enabled"] else "❌ disabled"
                last = info["last_called"]
                lines.append(f"**{name}** — {state} | tools: {info['tool_count']} | last: {last}")
                lines.append(f"  _{info['description']}_")
            return Result.success("\n".join(lines))

        m = re.search(r"(?:tools?|list tools?)\s+(?:for\s+)?(\w[\w-]*)", lower)
        if m:
            server = m.group(1)
            tools = mcp_bridge.list_mcp_tools(server)
            if not tools:
                return Result.success(f"No tools found for '{server}' (server may be disabled or unreachable).")
            lines = [f"🔧 **Tools on {server}**\n"]
            for t in tools:
                desc = t.get("description", "")
                lines.append(f"• **{t.get('name', '?')}** — {desc}")
            return Result.success("\n".join(lines))

        if re.search(r"\b(read|open|show|cat)\b", lower) and re.search(r"(/[^\s]+|\S+\.\w+)", ctx.user_input):
            path_m = re.search(r"(/[^\s]+|\b[\w./~-]+\.\w+)", ctx.user_input)
            if not path_m:
                return Result.success("📄 I need a file path. Try: 'mcp read /home/vaibhav/notes/todo.txt'")
            path = os.path.expanduser(path_m.group(1))
            result = mcp_bridge.call_mcp_server("filesystem", "read_file", {"path": path}, context_intent=ctx.intent)
            return Result.success(f"📄 **{path}**\n\n{result}")

        if re.search(r"\b(list|ls|dir)\b", lower):
            path_m = re.search(r"(/[^\s]+)", ctx.user_input)
            path = os.path.expanduser(path_m.group(1)) if path_m else "/home/vaibhav"
            result = mcp_bridge.call_mcp_server("filesystem", "list_directory", {"path": path}, context_intent=ctx.intent)
            return Result.success(f"📂 **{path}**\n\n{result}")

        if re.search(r"\b(write|save|create)\b", lower):
            path_m = re.search(r"(/[^\s]+|\b[\w./~-]+\.\w+)", ctx.user_input)
            if not path_m:
                return Result.success("📄 I need a file path. Try: 'mcp write /home/vaibhav/notes/test.txt with content Hello'")
            path = os.path.expanduser(path_m.group(1))
            content_m = re.search(r"(?:with content|content|containing|text)\s+(.+)$", ctx.user_input, re.IGNORECASE | re.DOTALL)
            content = content_m.group(1).strip() if content_m else ""
            if not content:
                return Result.success(f"📄 What should I write to `{path}`? Try: 'mcp write {path} with content Hello'")
            result = mcp_bridge.call_mcp_server("filesystem", "write_file", {"path": path, "content": content}, context_intent=ctx.intent)
            return Result.success(f"📄 {result}")

        if re.search(r"\b(search|brave|web search)\b", lower):
            query_m = re.search(r"(?:search|brave search|web search)\s+(?:for\s+)?(.+)$", ctx.user_input, re.IGNORECASE)
            query = query_m.group(1).strip() if query_m else ctx.user_input
            result = mcp_bridge.call_mcp_server("brave-search", "search", {"query": query}, context_intent=ctx.intent)
            return Result.success(f"🔍 **MCP Brave Search**: {query}\n\n{result}")

        if re.search(r"\bgithub\b", lower):
            query_m = re.search(r"github\s+(.+)$", ctx.user_input, re.IGNORECASE)
            query = query_m.group(1).strip() if query_m else ctx.user_input
            result = mcp_bridge.call_mcp_server("github", "search_repositories", {"query": query}, context_intent=ctx.intent)
            return Result.success(f"🐙 **GitHub**: {query}\n\n{result}")

        if re.search(r"\b(drive|gdrive|google drive)\b", lower):
            query_m = re.search(r"(?:drive|gdrive|google drive)\s+(?:search\s+)?(.+)$", ctx.user_input, re.IGNORECASE)
            query = query_m.group(1).strip() if query_m else ""
            result = mcp_bridge.call_mcp_server("gdrive", "search_files", {"query": query}, context_intent=ctx.intent)
            return Result.success(f"📁 **Google Drive**: {query}\n\n{result}")

        enabled = mcp_bridge.get_enabled_servers()
        if not enabled:
            return Result.success(
                "🔌 No MCP servers currently enabled.\n"
                "Enable servers in `/home/vaibhav/EDITH/mcp_config.json` and restart EDITH."
            )
        return Result.success(
            f"🔌 MCP active servers: {', '.join(enabled)}\n\n"
            "Commands:\n"
            "• `mcp read /path/to/file` — read a file\n"
            "• `mcp list /path/` — list directory\n"
            "• `mcp write /path content …` — write file\n"
            "• `mcp search <query>` — Brave web search\n"
            "• `mcp github <query>` — GitHub search\n"
            "• `mcp drive <query>` — Google Drive search\n"
            "• `mcp status` — server status"
        )
    except Exception as e:
        return Result.from_exception(e)


def _handle_image_gen(ctx) -> Result:
    try:
        import subprocess as _sp
        from image_gen import generate_image
        prompt = ctx.user_input
        for kw in ["generate image", "create image", "draw", "visualize", "make image", "generate a", "create a"]:
            prompt = re.sub(rf"\b{re.escape(kw)}\b", "", prompt, flags=re.IGNORECASE).strip()
        prompt = prompt.strip(" of ")
        if len(prompt) < 3:
            return Result.success("🎨 What should I generate? Example: 'create image of a sunset over mountains'")
        path = generate_image(prompt)
        if not path:
            return Result.success("🎨 Image generation failed. Check internet connection.")
        try:
            _sp.Popen(["xdg-open", path], stdout=_sp.DEVNULL, stderr=_sp.DEVNULL)
        except Exception:
            pass
        return Result.success(f"🎨 Saved to: {path}\n(Opening viewer...)")
    except Exception as e:
        return Result.from_exception(e)


def _handle_video_summarize(ctx) -> Result:
    try:
        import shutil as _sh
        url_match = re.search(r'https?://\S+', ctx.user_input)
        if not url_match:
            return Result.success("📹 Provide a YouTube URL. Example: 'summarize https://youtu.be/XXXXX'")
        if not _sh.which("yt-dlp"):
            return Result.success("📹 yt-dlp not installed. Run: pip install yt-dlp")
        url = url_match.group(0)
        from video_summarizer import download_audio, transcribe_audio, summarize_with_qwen
        audio = download_audio(url)
        if not audio:
            return Result.success("📹 Download failed. Check URL and yt-dlp.")
        transcript = transcribe_audio(audio)
        summary = summarize_with_qwen(transcript)
        try:
            os.remove(audio)
        except Exception:
            pass
        return Result.success(f"📹 Summary:\n\n{summary}")
    except Exception as e:
        return Result.from_exception(e)


def _handle_chat_fallback(ctx) -> Result:
    try:
        from search import web_search, format_results

        feat_query = ctx.user_input.lower()
        if any(p in feat_query for p in ["what can you do", "your features", "what are your capabilities"]):
            return Result.success(
                "I'm your full-stack AI assistant, Boss. Here's what I've got:\n\n"
                "**Chat & Knowledge** — conversation, reasoning, coding help\n"
                "**Web Search** — real-time info, news, scores, prices\n"
                "**Email & Calendar** — read inbox, schedule events\n"
                "**Phone Control** — ring, SMS, battery, notifications\n"
                "**File & System** — browse files, run commands (with safety checks)\n"
                "**Vision** — analyze your screen or any image\n"
                "**Agent Mode** — multi-step task automation\n"
                "**Data Analysis** — CSV/Excel analysis with charts\n"
                "**Cognitive Suite** — Council of Minds, decision simulation, weekly briefings, drift detection, self-improvement\n\n"
                "Just ask naturally — I'll figure out what you need."
            )

        if re.search(r"\b(who won|score|result|ipl|cricket|football|election|stock|price|match|latest|today.s|current|news)\b", ctx.user_input.lower()):
            search_query = ctx.user_input
            try:
                from smart_router import smart_call
                rewrite_prompt = (
                    f"User asked: {ctx.user_input}\n"
                    f"Write a short, highly specific web search query for DuckDuckGo to find the exact answer. "
                    f"Reply ONLY with the search phrase."
                )
                rewritten = smart_call(rewrite_prompt, intent="reason").strip(' "\'\n')
                if rewritten and len(rewritten.split()) < 10:
                    search_query = rewritten
                    log.info(f"AI Query Rewriter: '{ctx.user_input}' -> '{search_query}'")
            except Exception as e:
                log.warning(f"Query rewrite failed: {e}")

            log.info(f"Auto-search triggered: {search_query[:80]}")
            results_r = web_search(search_query, num_results=3)
            search_text = format_results(results_r.value if results_r.ok else [])
            if search_text and "error" not in search_text.lower():
                today_str = datetime.datetime.now().strftime('%A, %d %B %Y')
                prompt = (
                    f"Current Date: {today_str}\n\nUser Query: {ctx.user_input}\n\n"
                    f"Search results:\n{search_text}\n\n"
                    f"IMPORTANT: Verify dates against Current Date! "
                    f"Answer with EXACT facts. No fluff. Just the answer."
                )
                return Result.success(ctx.chat_fn(prompt, intent="search"))

        reply = ctx.chat_fn(ctx.user_input, intent=ctx.intent)

        if re.search(r"(i can search|search the web|i don.t have real.time|let me check|want me to.*search)", reply.lower()):
            log.info(f"LLM admitted need for search: {ctx.user_input[:50]}")
            results_r = web_search(ctx.user_input, num_results=3)
            search_text = format_results(results_r.value if results_r.ok else [])
            if search_text and "error" not in search_text.lower():
                today_str = datetime.datetime.now().strftime('%A, %d %B %Y')
                prompt = (
                    f"Current Date: {today_str}\n\nUser Query: {ctx.user_input}\n\n"
                    f"Search results:\n{search_text}\n\n"
                    f"Extract the exact answer. Check against Current Date. Answer directly."
                )
                return Result.success(ctx.chat_fn(prompt, intent="search"))

        return Result.success(reply)
    except Exception as e:
        return Result.from_exception(e)


# ──────────────────────────────────────────────
# Dispatch Table
# ──────────────────────────────────────────────
INTENT_HANDLERS = {
    "weather":         _handle_weather,
    "calendar_today":  _handle_calendar_today,
    "calendar_week":   _handle_calendar_week,
    "calendar_create": _handle_calendar_create,
    "email":           _handle_email,
    "unread_email":    _handle_unread_email,
    "search":          _handle_search,
    "call":            _handle_call,
    "sms":             _handle_sms,
    "phone":           _handle_phone,
    "vision":          _handle_vision,
    "shell":           _handle_shell,
    "file_query":      _handle_file_query,
    "create_file":     _handle_create_file,
    "delete_file":     _handle_delete_file,
    "rag":             _handle_rag,
    "data_analysis":   _handle_data_analysis,
    "agent":           _handle_agent,
    "council":         _handle_council,
    "decision":        _handle_decision,
    "briefing":        _handle_briefing,
    "profile":         _handle_profile,
    "self_improve":    _handle_self_improve,
    "session_end":     _handle_session_end,
    "wake":            _handle_wake,
    "whatsapp":        _handle_whatsapp,
    "mcp":             _handle_mcp,
    "image_gen":       _handle_image_gen,
    "video_summarize": _handle_video_summarize,
}


def dispatch(ctx: DispatchContext) -> str:
    """Route an intent to its handler via DispatchContext. Returns response string."""
    handler = INTENT_HANDLERS.get(ctx.intent, _handle_chat_fallback)
    try:
        result = handler(ctx)
        if isinstance(result, Result):
            if result.ok:
                return str(result.value)
            log.error(f"Handler [{ctx.intent}] failure: {result.error} ({result.error_type})")
            return _friendly_error(ctx.intent, result.error)
        # Backward compat: handler returned plain string
        return str(result) if result else _friendly_error(ctx.intent, "No response generated")
    except Exception as e:
        res = Result.from_exception(e)
        log.error(f"Dispatch exception [{ctx.intent}]: {res.error}")
        return _friendly_error(ctx.intent, res.error)


def execute_pending_action(action) -> str:
    """Execute a HITL-confirmed action. Returns str for backward compatibility."""
    from tools import write_file, delete_file
    atype = action.get("type")

    if atype == "whatsapp":
        from whatsapp import send_message
        return f"📱 {send_message(action['contact'], action['message'])}"
    elif atype == "shell":
        cmd = action.get("cmd")
        try:
            result = subprocess.run(shlex.split(cmd), capture_output=True, text=True, timeout=30, cwd="/home/vaibhav")
            output = result.stdout or result.stderr
            return f"💻 Execution Complete:\n\n{output.strip() or 'No output returned.'}"
        except Exception as e:
            return f"❌ Shell Error: {e}"
    elif atype == "create_file":
        return f"📁 {write_file(action['path'], action['content'], interactive=False)}"
    elif atype == "delete_file":
        return f"🗑️ {delete_file(action['path'], interactive=False)}"
    elif atype == "agent":
        steps = action.get("steps", [])
        if not steps:
            return "No valid steps found in the plan to execute."
        from agent import is_dangerous, get_command
        results = []
        for i, step in enumerate(steps, 1):
            cmd = get_command(step)
            if is_dangerous(cmd):
                results.append(f"⛔ Step {i} Blocked (Dangerous): `{cmd}`")
                continue
            try:
                subprocess.run(shlex.split(cmd), capture_output=True, text=True, timeout=30, cwd="/home/vaibhav")
                results.append(f"✅ Step {i}: `{cmd}` -> OK")
            except Exception as e:
                results.append(f"❌ Step {i}: `{cmd}` -> ERROR ({e})")
        return "🤖 Agent Execution Summary:\n\n" + "\n".join(results)

    return "Unknown action type."
