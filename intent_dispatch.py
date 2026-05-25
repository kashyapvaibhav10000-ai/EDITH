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

from config import get_logger, get_user_dir, USER_HOME, EDITH_PATH
from command_runner import run_piped_command, run_command
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


def _handle_identity(ctx: DispatchContext) -> Result:
    """Handle identity/greeting intents dynamically via chat_fn."""
    system_hint = (
        "You are EDITH (Even Dead, I'm The Hero), a personal AI OS built by Vaibhav Kashyap. "
        "Answer questions about yourself, your purpose, your creator naturally and conversationally."
    )
    response = ctx.chat_fn(f"{system_hint}\n\nUser: {ctx.user_input}", intent="chat")
    return Result(ok=True, value=response)


# Kept for stream-endpoint backward compat — real logic lives in _run_local_exec
_LOCAL_SYSINFO = []


# ── _SYSINFO_TERMS: each entry (compiled_re, label, shell_cmd) ──────────────
_SYSINFO_TERMS = [
    (re.compile(r"\b(os|operating system|distro|linux version|what os)\b", re.I),
     "OS", "lsb_release -d 2>/dev/null || grep PRETTY_NAME /etc/os-release | cut -d= -f2 | tr -d '\"'"),
    (re.compile(r"\bkernel\b", re.I),
     "Kernel", "uname -r"),
    (re.compile(r"\b(cpu|processor)\b", re.I),
     "CPU", "lscpu | grep 'Model name' | sed 's/.*: *//' | head -1"),
    (re.compile(r"\b(ram|memory|mem)\b", re.I),
     "RAM", "free -h | grep ^Mem"),
    (re.compile(r"\bdisk\b", re.I),
     "Disk", "df -h -x tmpfs -x devtmpfs 2>/dev/null"),
    (re.compile(r"\bhostname\b", re.I),
     "Hostname", "hostname"),
    (re.compile(r"\buptime\b", re.I),
     "Uptime", "uptime -p"),
    (re.compile(r"\b(local|network|private|lan)\s+(ip|address|addr)\b|\bmy\s+ip\b|\bwhat.*my.*ip\b", re.I),
     "Network", "ip -br addr show"),
    (re.compile(r"\bmtu\b", re.I),
     "MTU", "ip link show | grep -E 'mtu|UP'"),
    (re.compile(r"\bnetwork interfaces?\b|\bshow.*interfaces?\b|\blist.*interfaces?\b", re.I),
     "Interfaces", "ip -br link show"),
]


def _run_local_exec(user_input: str):
    """
    Detect and execute local system/file ops. Never web-search, never hallucinate.
    Returns result string or None if query is not a local op.
    """
    # DISABLED on cloud: all shell=True subprocess calls below are local-only
    if os.getenv("EDITH_NODE_TYPE", "local") == "cloud":
        return None
    import random as _random
    import shutil as _shutil

    lower = user_input.lower()

    # ── 1. Process / resource monitoring — checked BEFORE sysinfo to avoid cpu/mem conflict ──
    _PROC_PAT = re.compile(
        r"\b(process(?:es)?|running apps?|applications?)\b.{0,40}\b(cpu|memory|ram|consuming|usage)\b"
        r"|\b(cpu|memory|ram)\b.{0,40}\b(process(?:es)?|consuming|usage)\b"
        r"|\bps\b.{0,30}\b(cpu|mem|process)\b"
        r"|\b(running processes|active processes|top processes)\b",
        re.I
    )
    if _PROC_PAT.search(user_input):
        thresh_m = re.search(r"(\d+)\s*%", user_input)
        threshold = float(thresh_m.group(1)) if thresh_m else 0
        by_mem = bool(re.search(r"\b(memory|ram|mem)\b", lower))
        sort_col = "-%mem" if by_mem else "-%cpu"
        col_idx = "4" if by_mem else "3"
        if threshold > 0:
            cmd = f"ps aux --sort={sort_col} | awk 'NR==1 || ${col_idx}>{threshold}' | head -30"
        else:
            cmd = f"ps aux --sort={sort_col} | head -25"
        r = run_piped_command(cmd, timeout=10)
        out = (r.output or "").strip()
        if out:
            return f"```\n{out}\n```"

    # ── 2. Compound sysinfo: >=2 sysinfo keywords → run all matched commands ──
    matched_sys = [(label, cmd) for pat, label, cmd in _SYSINFO_TERMS if pat.search(user_input)]
    if len(matched_sys) >= 2:
        parts = []
        for label, cmd in matched_sys:
            r = run_piped_command(cmd, timeout=5)
            v = (r.output or "").strip()
            if v:
                parts.append(f"**{label}:**\n```\n{v}\n```")
        if parts:
            return "\n\n".join(parts)

    # ── 3. Single sysinfo term ──────────────────────────────────────────────
    if len(matched_sys) == 1:
        label, cmd = matched_sys[0]
        r = run_piped_command(cmd, timeout=5)
        v = (r.output or "").strip()
        if v:
            return f"```\n{v}\n```"

    # ── 4. Duplicate file finding ───────────────────────────────────────────
    _DUP_PAT = re.compile(
        r"\b(duplicate|identical|same)\b.{0,20}\bfiles?\b"
        r"|\bfiles?\b.{0,20}\b(duplicate|identical)\b"
        r"|\bfind.*\bduplicate\b|\bduplicate.*\bfind\b",
        re.I
    )
    if _DUP_PAT.search(user_input):
        search_dir = USER_HOME
        for kw in ["downloads", "documents", "desktop"]:
            if kw in lower:
                search_dir = get_user_dir(kw)
                break
        abs_m = re.search(r"(/[^\s]+)", user_input)
        if abs_m:
            search_dir = abs_m.group(1)
        r = run_piped_command(
            f"fdupes -r '{search_dir}' 2>/dev/null | head -50",
            timeout=30
        )
        out = (r.output or "").strip()
        if not out:
            r2 = run_piped_command(
                f"find '{search_dir}' -type f -not -empty 2>/dev/null | xargs md5sum 2>/dev/null "
                f"| sort | awk '{{if(prev==$1)print $0; prev=$1}}' | head -20",
                timeout=30
            )
            out = (r2.output or "").strip() or "No duplicate files found."
        return f"```\n{out}\n```"

    # ── 5. Find files by extension / size / date ────────────────────────────
    _FIND_PAT = re.compile(
        r"\b(find all|find|locate|search for|list all)\b.{0,40}\bfiles?\b"
        r"|\bfiles?\b.{0,10}\b(larger|bigger|over|more than|smaller)\b"
        r"|\b\.(log|py|txt|pdf|jpg|png|mp4|csv|sh|conf|json|zip|mp3|tar|gz)\b.{0,20}\b(larger|smaller|files?|find)\b"
        r"|\bfind.{0,20}\b\.(log|py|txt|pdf|jpg|png|mp4|csv|sh|conf|json|zip|mp3|tar|gz)\b",
        re.I
    )
    if _FIND_PAT.search(user_input):
        ext_m = re.search(r"\.(log|py|txt|pdf|jpg|jpeg|png|mp4|csv|sh|conf|json|zip|tar|gz|mp3|wav|docx|xlsx)\b", lower)
        ext = ext_m.group(0) if ext_m else None
        size_m = re.search(r"(larger|bigger|greater|over|more than|>)\s*(\d+)\s*(mb|gb|kb)", lower)
        size_flag = None
        if size_m:
            n = int(size_m.group(2))
            unit = size_m.group(3)
            size_flag = f"+{n}M" if unit == "mb" else (f"+{n}G" if unit == "gb" else f"+{n}k")
        sort_desc = bool(re.search(r"\b(descend|largest|biggest|sort.*desc)\b", lower))
        name_part = f'-name "*{ext}"' if ext else '-type f'
        size_part = f"-size {size_flag}" if size_flag else ""
        cmd = (
            f"find {USER_HOME} {name_part} {size_part} 2>/dev/null "
            f"-exec ls -lh {{}} \\; 2>/dev/null"
        )
        if sort_desc or size_flag:
            cmd += " | sort -k5 -rh"
        cmd += " | head -30"
        r = run_piped_command(cmd, timeout=20)
        out = (r.output or "").strip()
        if out:
            return f"```\n{out}\n```"
        return f"No {ext or ''} files found matching criteria in {USER_HOME}."

    # ── 6. Random file selection + actual copy ──────────────────────────────
    _RAND_PAT = re.compile(
        r"\b(random(ly)?|select|pick|sample)\b.{0,50}\b(copy|move|put)\b"
        r"|\b(copy|move)\b.{0,30}\brandom\b"
        r"|\brandomly\s+(select|pick|choose|copy)\b",
        re.I
    )
    if _RAND_PAT.search(user_input):
        count_m = re.search(r"\b(\d+)\b", user_input)
        count = int(count_m.group(1)) if count_m else 10

        dest_dir = get_user_dir("downloads")
        for kw in ["downloads", "download", "documents", "desktop", "pictures", "home"]:
            if kw in lower:
                dest_dir = get_user_dir(kw)
                break

        # "test folder" / "folder named X" → subdirectory
        test_m = re.search(r"\btest\s+folder\b|\btest_folder\b", lower)
        named_m = re.search(r"\bfolder\s+named\s+(\w+)\b|\bfolder\s+called\s+(\w+)\b", lower)
        if test_m:
            dest_dir = os.path.join(dest_dir, "test")
        elif named_m:
            folder_name = named_m.group(1) or named_m.group(2)
            dest_dir = os.path.join(dest_dir, folder_name)

        # Source dir — "from X" or default to home
        src_dir = USER_HOME
        src_m = re.search(r"\bfrom\s+(\w+)\b", lower)
        if src_m:
            src_dir = get_user_dir(src_m.group(1))

        try:
            all_files = [f for f in os.listdir(src_dir) if os.path.isfile(os.path.join(src_dir, f))]
        except OSError as e:
            return f"❌ Cannot access `{src_dir}`: {e}"
        if not all_files:
            return f"❌ No files in `{src_dir}`."

        selected = _random.sample(all_files, min(count, len(all_files)))
        os.makedirs(dest_dir, exist_ok=True)
        copied, failed = [], []
        for f in selected:
            src_path = os.path.join(src_dir, f)
            dst_path = os.path.join(dest_dir, f)
            try:
                _shutil.copy2(src_path, dst_path)
                if os.path.isfile(dst_path):
                    copied.append(f)
                else:
                    failed.append(f"{f}: not found after copy")
            except Exception as e:
                failed.append(f"{f}: {e}")

        summary = f"📁 Copied {len(copied)}/{len(selected)} files to `{dest_dir}`:\n"
        summary += "\n".join(f"  • {f}" for f in copied)
        if failed:
            summary += f"\n\n❌ Failed: {', '.join(failed[:5])}"
        return summary

    # ── 7. Network connectivity / ping / DNS ────────────────────────────────
    _NET_PAT = re.compile(
        r"\b(ping|network access|internet connectivity|dns resolution|resolve dns|"
        r"validate network|check.*internet|check.*connectivity|network.*test|"
        r"pinging.*server|check.*ping|am i online|test.*network)\b",
        re.I
    )
    if _NET_PAT.search(user_input):
        parts = []
        r1 = run_piped_command("ping -c 3 -W 2 8.8.8.8 2>&1", timeout=15)
        if r1.output:
            parts.append(f"**Ping (8.8.8.8):**\n```\n{r1.output}\n```")
        r2 = run_piped_command("ping -c 2 -W 2 google.com 2>&1 | tail -3", timeout=10)
        if r2.output:
            parts.append(f"**DNS + Ping (google.com):**\n```\n{r2.output}\n```")
        r3 = run_piped_command("nslookup google.com 2>/dev/null | tail -4", timeout=8)
        if r3.output:
            parts.append(f"**DNS Lookup:**\n```\n{r3.output}\n```")
        if parts:
            return "\n\n".join(parts)
        return "❌ All network checks failed — likely offline."

    # ── 8. Privilege / permission check ────────────────────────────────────
    _PRIV_PAT = re.compile(
        r"\b(privilege|permission|sudo access|current user|whoami|user permissions|"
        r"restricted director|groups?\b.*user|check.*permission|my.*user.*info|"
        r"id\s+command|who am i|check.*sudo)\b",
        re.I
    )
    if _PRIV_PAT.search(user_input):
        parts = []
        r1 = run_piped_command("whoami && id && groups", timeout=5)
        if r1.output:
            parts.append(f"**User / Groups:**\n```\n{r1.output}\n```")
        r2 = run_piped_command("sudo -l 2>&1 | head -20", timeout=8)
        if r2.output:
            parts.append(f"**Sudo Permissions:**\n```\n{r2.output}\n```")
        r3 = run_piped_command(
            "ls -ld /root /etc/sudoers /etc/shadow 2>&1 | awk '{print $1, $3, $4, $NF}'",
            timeout=5
        )
        if r3.output:
            parts.append(f"**Restricted Paths:**\n```\n{r3.output}\n```")
        if parts:
            return "\n\n".join(parts)

    # ── 9. "Test execution / run multiple commands" ─────────────────────────
    _TEST_CMDS_PAT = re.compile(
        r"\b(test|check|verify|validate)\b.{0,50}\b(command|execution|capability|terminal)\b"
        r"|\brunning\s+(linux\s+)?commands?\s+(like|such as|including)\b"
        r"|\brun\s+(ls|pwd|df|free|ps|uname|whoami|id|hostname|uptime)\b",
        re.I
    )
    if _TEST_CMDS_PAT.search(user_input):
        # Extract known safe commands from the sentence
        _KNOWN_CMDS = ["ls", "pwd", "df", "free", "ps", "uname", "whoami", "id", "hostname", "uptime", "date", "env", "who"]
        found_cmds = [c for c in _KNOWN_CMDS if re.search(r'\b' + c + r'\b', user_input, re.I)]
        if not found_cmds:
            found_cmds = ["ls", "pwd", "df", "free", "ps"]  # default set
        parts = []
        for c in found_cmds:
            r = run_command(c, timeout=5, check_paths=False)
            out = (r.output or "").strip()
            if out:
                parts.append(f"**`{c}`:**\n```\n{out[:300]}\n```")
        if parts:
            return "\n\n".join(parts)

    return None


def _handle_search(ctx) -> Result:
    try:
        # Always try local execution before web search
        _local = _run_local_exec(ctx.user_input)
        if _local:
            return Result.success(_local)

        from search import web_search, format_results
        _ist = datetime.timezone(datetime.timedelta(hours=5, minutes=30))
        _now = datetime.datetime.now(_ist)
        _original_query = ctx.user_input
        _search_query = (
            f"Today is {_now.strftime('%A %B %d %Y')}, India IST. {_original_query}"
            if not re.search(r'\b20\d{2}\b', _original_query)
            else _original_query
        )
        results_r = web_search(_search_query)
        results = results_r.value if results_r.ok else []
        search_text = format_results(results)
        if search_text and "error" not in search_text.lower() and "no results" not in search_text.lower():
            today_str = datetime.datetime.now().strftime('%A, %d %B %Y')
            prompt = (
                f"Current Date: {today_str}\n\nUser Query: {ctx.user_input}\n\n"
                f"Search results:\n{search_text}\n\n"
                f"IMPORTANT: Verify dates against Current Date! "
                f"Answer with EXACT facts. No fluff. Just the answer."
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


def _handle_open_app(ctx) -> Result:
    try:
        import re as _re
        text = ctx.user_input.lower().strip()
        m = _re.match(r"^(?:open|launch|start)\s+(.+)$", text)
        app_name = m.group(1).strip() if m else text

        APP_MAP = {
            "chrome": ["chromium", "google-chrome", "google-chrome-stable"],
            "chromium": ["chromium"],
            "firefox": ["firefox"],
            "brave": ["brave", "brave-browser"],
            "opera": ["opera"],
            "browser": ["chromium", "firefox", "brave"],
            "terminal": ["konsole", "xterm", "gnome-terminal", "alacritty", "kitty"],
            "konsole": ["konsole"],
            "spotify": ["spotify"],
            "vlc": ["vlc"],
            "code": ["code"],
            "vscode": ["code"],
            "files": ["dolphin", "nautilus", "thunar"],
            "dolphin": ["dolphin"],
            "nautilus": ["nautilus"],
            "calculator": ["kcalc", "gnome-calculator"],
            "kcalc": ["kcalc"],
            "steam": ["steam"],
            "discord": ["discord"],
            "slack": ["slack"],
            "telegram": ["telegram-desktop", "telegram"],
            "notion": ["notion-app", "notion"],
            "obsidian": ["obsidian"],
            "gimp": ["gimp"],
            "inkscape": ["inkscape"],
            "blender": ["blender"],
            "thunderbird": ["thunderbird"],
            "libreoffice": ["libreoffice"],
            "okular": ["okular"],
            "mpv": ["mpv"],
            "celluloid": ["celluloid"],
            "audacity": ["audacity"],
            "kdenlive": ["kdenlive"],
            "handbrake": ["ghb"],
            "virtualbox": ["virtualbox"],
            "postman": ["postman"],
            "insomnia": ["insomnia"],
            "dbeaver": ["dbeaver"],
        }

        candidates = APP_MAP.get(app_name, [app_name])
        import shutil as _shutil
        binary = next((c for c in candidates if _shutil.which(c)), None)

        if binary:
            subprocess.Popen([binary], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                             start_new_session=True)
            return Result.success(f"Launched {app_name}.")
        else:
            # xdg-open fallback
            try:
                subprocess.Popen(["xdg-open", app_name], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                 start_new_session=True)
                return Result.success(f"Tried to open {app_name} — let me know if it didn't launch.")
            except Exception:
                return Result.success(f"Can't find '{app_name}' on your system. Is it installed?")
    except Exception as e:
        return Result.from_exception(e)


def _handle_shell(ctx) -> Result:
    # DISABLED on cloud: remote shell execution is an RCE vector
    if os.getenv("EDITH_NODE_TYPE", "local") == "cloud":
        return Result.success("Shell execution disabled on cloud node for security.")
    try:
        # Intercept descriptive/natural-language queries before treating as raw shell
        _local = _run_local_exec(ctx.user_input)
        if _local:
            return Result.success(_local)

        cmd = ctx.user_input
        for prefix in ["run ", "execute ", "terminal ", "shell ", "command "]:
            if cmd.lower().startswith(prefix):
                cmd = cmd[len(prefix):].strip()
                break
        cmd = cmd.strip("\"'`")
        if not cmd or cmd.lower() in ["run", "execute", "command", "shell"]:
            return Result.success(f"What command should I run, Boss? Something like 'run ls -la {USER_HOME}'.")

        if _is_safe_command(cmd):
            try:
                result = subprocess.run(shlex.split(cmd), capture_output=True, text=True, timeout=15, cwd=USER_HOME)
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
            "download": get_user_dir("downloads"),
            "document": get_user_dir("documents"),
            "desktop": get_user_dir("desktop"),
            "home": USER_HOME,
            "picture": get_user_dir("pictures"),
            "video": os.path.join(USER_HOME, "Videos"),
            "music": os.path.join(USER_HOME, "Music"),
        }
        target_dir = None
        lower = ctx.user_input.lower()
        for key, path in dir_map.items():
            if key in lower:
                target_dir = path
                break
        if not target_dir:
            path_match = re.search(r'(/[\w/.-]+)', ctx.user_input)
            target_dir = os.path.expanduser(path_match.group(1)) if path_match else USER_HOME

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
            return Result.success(f"📁 I need a file path. Try: 'create file {USER_HOME}/notes/todo.txt'")
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
            return Result.success(f"🗑️ I need a file path. Try: 'delete file {USER_HOME}/old_notes.txt'")
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
            return Result.success(f"📊 I need a file path. Try: 'analyze {USER_HOME}/data.csv what month had highest sales'")
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


def _handle_morning_briefing(ctx) -> Result:
    parts = []
    try:
        from weather import get_current_weather, format_weather
        r = get_current_weather()
        parts.append(f"🌤️ Weather: {format_weather(r.value) if r.ok else 'Unavailable'}")
    except Exception:
        parts.append("🌤️ Weather: Unavailable")
    try:
        from email_reader import check_inbox
        r = check_inbox(limit=3, unread_only=True)
        parts.append(f"📧 Email: {r.value if r.ok else 'Unavailable'}")
    except Exception:
        parts.append("📧 Email: Unavailable")
    try:
        from calendar_reader import get_today_briefing
        r = get_today_briefing()
        parts.append(f"📅 Calendar: {r.value if r.ok else 'Unavailable'}")
    except Exception:
        parts.append("📅 Calendar: Unavailable")
    try:
        from life_os import format_open_loops
        loops = format_open_loops()
        if loops and loops.strip():
            parts.append(f"🔄 Open loops: {loops}")
    except Exception:
        pass
    return Result.success("Good morning, Boss. 🌅\n\n" + "\n\n".join(parts))


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
    def _safe_path(raw: str) -> tuple:
        """Expand and jail path to USER_HOME. Returns (resolved, error_str)."""
        expanded = os.path.expanduser(raw.strip())
        resolved = os.path.realpath(expanded)
        if not resolved.startswith(USER_HOME):
            return None, f"Access denied — path outside {USER_HOME}: `{resolved}`"
        return resolved, None

    try:
        import mcp_bridge
        import secrets
        lower = ctx.user_input.lower()

        # ── MCP server status / tool listing ─────────────────────────────
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

        # ── Filesystem: create_directory ──────────────────────────────────
        _create_dir_pat = re.search(
            r"\b(create|make|mkdir)\b.{0,30}?(\d+)?.{0,20}?\b(folder|directory|dir)s?\b",
            lower
        )
        if _create_dir_pat or re.search(r"\bmkdir\b", lower):
            # Words that describe naming *style*, not the literal folder name
            _naming_noise = {"random", "using", "hash", "bit", "names", "named", "called",
                             "unique", "generated", "auto", "temp", "tmp"}

            def _resolve_base(raw_base: str) -> tuple:
                """Resolve base path with 4-step fallback. Returns (resolved, err_or_None).
                err sentinel values: None=ok, __fuzzy__:typed:matched, __notfound__:typed:csv_of_dirs"""
                if not raw_base.startswith("/") and not raw_base.startswith("~"):
                    candidate = os.path.join(USER_HOME, raw_base)
                else:
                    candidate = raw_base
                resolved, err = _safe_path(candidate)
                if err:
                    return None, err
                # Step 0: exact path exists
                if os.path.isdir(resolved):
                    return resolved, None

                import difflib
                typed_leaf = os.path.basename(resolved)
                try:
                    actual_dirs = [d for d in os.listdir(USER_HOME)
                                   if os.path.isdir(os.path.join(USER_HOME, d))]
                except OSError:
                    actual_dirs = []

                # Step 1: case-insensitive exact match ("downloads" → "Downloads")
                lower_map = {d.lower(): d for d in actual_dirs}
                if typed_leaf.lower() in lower_map:
                    matched = lower_map[typed_leaf.lower()]
                    return os.path.join(USER_HOME, matched), f"__fuzzy__:{typed_leaf}:{matched}"

                # Step 2: case-insensitive startswith ("down" → "Downloads")
                sw = [d for d in actual_dirs if d.lower().startswith(typed_leaf.lower())]
                if len(sw) == 1:
                    return os.path.join(USER_HOME, sw[0]), f"__fuzzy__:{typed_leaf}:{sw[0]}"

                # Step 3: difflib fuzzy (handles typos like "Downlaods")
                fuzzy = difflib.get_close_matches(typed_leaf, actual_dirs, n=1, cutoff=0.6)
                if fuzzy:
                    return os.path.join(USER_HOME, fuzzy[0]), f"__fuzzy__:{typed_leaf}:{fuzzy[0]}"

                # Step 4: total fail — surface available dirs to user
                top = ", ".join(sorted(actual_dirs)[:10])
                return None, f"__notfound__:{typed_leaf}:{top}"

            # How many folders?
            count_m = re.search(r"\b(\d+)\b", ctx.user_input)
            count = int(count_m.group(1)) if count_m else 1
            if count > 100:
                return Result.success("⚠️ Max 100 folders per request.")

            # Named folder? e.g. "create folder named test" / "mkdir test_folder"
            named_m = re.search(
                r"(?:named?|called|as)\s+([\w._-]+)|mkdir\s+([\w._-]+)",
                ctx.user_input, re.IGNORECASE
            )
            # Strip naming-instruction words from extracted name
            if named_m:
                _extracted = (named_m.group(1) or named_m.group(2) or "").strip().lower()
                if _extracted in _naming_noise:
                    named_m = None

            # Base path from message
            path_m = re.search(r"in\s+(/[^\s]+|~/[^\s]+|[\w]+)",
                               ctx.user_input, re.IGNORECASE)
            if path_m:
                raw_base = path_m.group(1)
            else:
                raw_base = USER_HOME

            base, base_err = _resolve_base(raw_base)
            if base_err and base_err.startswith("__fuzzy__:"):
                _, typed, matched = base_err.split(":", 2)
                # Auto-correct silently (case-only difference)
                if typed.lower() == matched.lower():
                    base_err = None
                else:
                    _named = None
                    if named_m:
                        _named = (named_m.group(1) or named_m.group(2) or "").strip()
                    set_pending_action({
                        "type": "fuzzy_confirm",
                        "resolved_path": base,
                        "count": count,
                        "named": _named,
                    })
                    return Result.success(
                        f"⚠️ No folder named `{typed}` found in {USER_HOME}/.\n"
                        f"Did you mean `{matched}`? Reply YES to confirm or give the full path."
                    )
            elif base_err and base_err.startswith("__notfound__:"):
                parts = base_err.split(":", 2)
                typed = parts[1]
                available = parts[2] if len(parts) > 2 else ""
                msg = f"⚠️ No folder called `{typed}` found in {USER_HOME}/."
                if available:
                    msg += f"\nAvailable folders: {available}"
                msg += f"\nProvide full path or correct name."
                return Result.success(msg)
            elif base_err:
                return Result.success(f"❌ {base_err}")

            def _create_one(full_path: str) -> tuple:
                """Create a single directory. Returns (success: bool, message: str)."""
                safe, err = _safe_path(full_path)
                if err:
                    return False, f"path_error: {err}"
                result = mcp_bridge.call_mcp_server(
                    "filesystem", "create_directory", {"path": safe}, context_intent=ctx.intent
                )
                if "error" in result.lower() or "failed" in result.lower():
                    try:
                        os.makedirs(safe, exist_ok=True)
                    except Exception as fe:
                        return False, f"MCP error: {result.strip()} | fallback error: {fe}"
                # Verify directory actually exists on disk
                if not os.path.isdir(safe):
                    return False, f"MCP reported success but `{safe}` not found on disk"
                return True, safe

            if named_m:
                name = (named_m.group(1) or named_m.group(2)).strip()
                ok, msg = _create_one(os.path.join(base, name))
                if not ok:
                    return Result.success(f"❌ Failed to create `{name}`: {msg}")
                return Result.success(f"📁 Created `{msg}`")
            else:
                # Create N folders with random names
                created = []
                failed = []
                for _ in range(count):
                    name = secrets.token_hex(4)
                    ok, msg = _create_one(os.path.join(base, name))
                    if ok:
                        created.append(name)
                    else:
                        failed.append(f"{name}: {msg}")
                if not created and failed:
                    return Result.success(
                        f"❌ All {count} folder(s) failed to create in `{base}`:\n"
                        + "\n".join(f"  • {f}" for f in failed[:5])
                    )
                summary = f"📁 Created {len(created)}/{count} folders in `{base}`:\n"
                summary += "\n".join(f"  • {n}" for n in created)
                if failed:
                    summary += f"\n\n❌ Failed ({len(failed)}): {', '.join(failed[:5])}"
                return Result.success(summary)

        # ── Filesystem: delete (HITL — never auto-execute) ────────────────
        if re.search(r"\b(delete|remove|rm)\b", lower) and re.search(r"(/[^\s]+|\S+\.\w+)", ctx.user_input):
            path_m = re.search(r"(/[^\s]+|\b[\w./~-]+\.\w+)", ctx.user_input)
            if not path_m:
                return Result.success("🗑️ I need a file path to delete.")
            safe, err = _safe_path(path_m.group(1))
            if err:
                return Result.success(f"❌ {err}")
            set_pending_action({"type": "delete_file", "path": safe})
            return Result.success(
                f"⚠️ **Delete `{safe}`?**\n\nThis cannot be undone. Type **YES** to confirm or **NO** to cancel."
            )

        # ── Filesystem: move / rename ─────────────────────────────────────
        if re.search(r"\b(move|rename|mv)\b", lower):
            paths = re.findall(r"(/[^\s]+|\b[\w./~-]+\.\w+)", ctx.user_input)
            if len(paths) < 2:
                return Result.success(f"📦 Need source and destination. Try: 'move {USER_HOME}/a.txt {USER_HOME}/b.txt'")
            src, err = _safe_path(paths[0])
            if err:
                return Result.success(f"❌ {err}")
            dst, err = _safe_path(paths[1])
            if err:
                return Result.success(f"❌ {err}")
            result = mcp_bridge.call_mcp_server(
                "filesystem", "move_file", {"source": src, "destination": dst}, context_intent=ctx.intent
            )
            if "error" in result.lower() or "failed" in result.lower():
                try:
                    import shutil
                    shutil.move(src, dst)
                    result = f"Moved `{src}` → `{dst}` (fallback)"
                except Exception as fe:
                    return Result.success(f"❌ Failed: {fe}")
            return Result.success(f"📦 {result}")

        # ── Filesystem: search files ──────────────────────────────────────
        if re.search(r"\b(find|search for file|search file|locate)\b", lower):
            path_m = re.search(r"in\s+(/[^\s]+)", ctx.user_input)
            base = os.path.expanduser(path_m.group(1)) if path_m else USER_HOME
            safe_base, err = _safe_path(base)
            if err:
                return Result.success(f"❌ {err}")
            pattern_m = re.search(r"(?:find|search for?|locate)\s+(\S+)", ctx.user_input, re.IGNORECASE)
            pattern = pattern_m.group(1) if pattern_m else "*"
            result = mcp_bridge.call_mcp_server(
                "filesystem", "search_files",
                {"path": safe_base, "pattern": pattern},
                context_intent=ctx.intent
            )
            return Result.success(f"🔍 **Search `{pattern}` in `{safe_base}`**\n\n{result}")

        # ── Filesystem: file info ─────────────────────────────────────────
        if re.search(r"\b(info|size|modified|stat)\b", lower) and re.search(r"(/[^\s]+|\S+\.\w+)", ctx.user_input):
            path_m = re.search(r"(/[^\s]+|\b[\w./~-]+\.\w+)", ctx.user_input)
            if not path_m:
                return Result.success("ℹ️ I need a file path.")
            safe, err = _safe_path(path_m.group(1))
            if err:
                return Result.success(f"❌ {err}")
            result = mcp_bridge.call_mcp_server(
                "filesystem", "get_file_info", {"path": safe}, context_intent=ctx.intent
            )
            return Result.success(f"ℹ️ **{safe}**\n\n{result}")

        # ── Filesystem: read file ─────────────────────────────────────────
        if re.search(r"\b(read|open|show|cat)\b", lower) and re.search(r"(/[^\s]+|\S+\.\w+)", ctx.user_input):
            path_m = re.search(r"(/[^\s]+|\b[\w./~-]+\.\w+)", ctx.user_input)
            if not path_m:
                return Result.success(f"📄 I need a file path. Try: 'read {USER_HOME}/notes/todo.txt'")
            safe, err = _safe_path(path_m.group(1))
            if err:
                return Result.success(f"❌ {err}")
            result = mcp_bridge.call_mcp_server("filesystem", "read_file", {"path": safe}, context_intent=ctx.intent)
            if "error" in result.lower() or "failed" in result.lower():
                try:
                    with open(safe) as f:
                        result = f.read()
                except Exception as fe:
                    return Result.success(f"❌ Failed: {fe}")
            return Result.success(f"📄 **{safe}**\n\n{result}")

        # ── Filesystem: list directory ────────────────────────────────────
        if re.search(r"\b(list|ls|dir|what.s in|show files)\b", lower):
            path_m = re.search(r"(/[^\s]+)", ctx.user_input)
            raw = path_m.group(1) if path_m else USER_HOME
            safe, err = _safe_path(raw)
            if err:
                return Result.success(f"❌ {err}")
            result = mcp_bridge.call_mcp_server("filesystem", "list_directory", {"path": safe}, context_intent=ctx.intent)
            if "error" in result.lower() or "failed" in result.lower():
                try:
                    entries = os.listdir(safe)
                    result = "\n".join(sorted(entries))
                except Exception as fe:
                    return Result.success(f"❌ Failed: {fe}")
            return Result.success(f"📂 **{safe}**\n\n{result}")

        # ── Filesystem: write file ────────────────────────────────────────
        if re.search(r"\b(write|save|create)\b", lower) and not re.search(r"\b(folder|directory|dir)\b", lower):
            path_m = re.search(r"(/[^\s]+|\b[\w./~-]+\.\w+)", ctx.user_input)
            if not path_m:
                return Result.success(f"📄 I need a file path. Try: 'write {USER_HOME}/notes/test.txt with content Hello'")
            safe, err = _safe_path(path_m.group(1))
            if err:
                return Result.success(f"❌ {err}")
            content_m = re.search(r"(?:with content|content|containing|text)\s+(.+)$", ctx.user_input, re.IGNORECASE | re.DOTALL)
            content = content_m.group(1).strip() if content_m else ""
            if not content:
                return Result.success(f"📄 What should I write to `{safe}`? Try: 'write {safe} with content Hello'")
            result = mcp_bridge.call_mcp_server("filesystem", "write_file", {"path": safe, "content": content}, context_intent=ctx.intent)
            if "error" in result.lower() or "failed" in result.lower():
                try:
                    with open(safe, "w") as f:
                        f.write(content)
                    result = f"Written to `{safe}` (fallback)"
                except Exception as fe:
                    return Result.success(f"❌ Failed: {fe}")
            return Result.success(f"📄 {result}")

        # ── Non-filesystem MCP: web search, github, gdrive ───────────────
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
                f"Enable servers in `{os.path.join(EDITH_PATH, 'mcp_config.json')}` and restart EDITH."
            )
        return Result.success(
            f"🔌 MCP active servers: {', '.join(enabled)}\n\n"
            "Filesystem commands:\n"
            "• `create 5 folders in Downloads` — create N folders with random names\n"
            "• `create folder named test in Downloads` — named folder\n"
            f"• `list {get_user_dir('downloads')}` — list directory\n"
            "• `read /path/to/file` — read file contents\n"
            "• `write /path/to/file with content ...` — write file\n"
            "• `move /src /dst` — move or rename\n"
            f"• `find *.py in {EDITH_PATH}` — search files\n"
            "• `info /path/to/file` — file metadata\n"
            "• `delete /path/to/file` — delete (requires confirmation)\n\n"
            "Other:\n"
            "• `search <query>` — Brave web search\n"
            "• `github <query>` — GitHub search\n"
            "• `drive <query>` — Google Drive search\n"
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
        path = os.path.abspath(path)
        if not os.path.exists(path):
            return Result.success("File not found")
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


def _handle_system_health(ctx) -> Result:
    try:
        from validator import validate_all, format_health_report
        results = validate_all()
        return Result.success(format_health_report(results))
    except Exception as e:
        return Result.from_exception(e)


def _handle_repo_analyze(ctx) -> Result:
    import re as _re
    match = _re.search(r"https://github\.com/[\w\-]+/[\w\-]+", ctx.user_input)
    if not match:
        return Result.success(
            "No GitHub URL found. Say: 'analyze repo https://github.com/owner/repo'"
        )
    url = match.group(0)
    try:
        from repo_dna import analyze_repo, RepoFetchError, RepoAnalysisError
        analysis = analyze_repo(url)

        steal = "\n".join(
            f"  • [{i['effort'].upper()}] {i['title']}" for i in analysis.get("steal_this", [])
        ) or "  none identified"
        wins = "\n".join(
            f"  • {i['title']}" for i in analysis.get("quick_wins", [])
        ) or "  none identified"
        summary = analysis.get("summary", "")

        return Result.success(
            f"**Repo DNA: {analysis.get('repo_name', url)}**\n\n"
            f"**Steal This:**\n{steal}\n\n"
            f"**Quick Wins:**\n{wins}\n\n"
            f"**Summary:** {summary}"
        )
    except (RepoFetchError, RepoAnalysisError) as exc:
        return Result.from_exception(exc)
    except Exception as exc:
        return Result.from_exception(exc)


def _handle_chat_fallback(ctx) -> Result:
    try:
        _local = _run_local_exec(ctx.user_input)
        if _local:
            return Result.success(_local)

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

        if re.search(r"\b(who won|score|result|ipl|cricket|football|election|stock|price|match|latest|today|today.s|current|news|recent|now|happening|update)\b", ctx.user_input.lower()):
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

        reply = ctx.chat_fn(ctx.user_input, intent=ctx.intent, source=getattr(ctx, "source", "widget"))

        if re.search(r"(i can search|search the web|don.t have.*real.time|real.time.*access|knowledge cutoff|can.t access|let me check|want me to.*search|up.to.date)", reply.lower()):
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
def _handle_compact(ctx: DispatchContext) -> Result:
    """O7 — /compact: trim widget history, clear conversation buffer, consolidate memories."""
    try:
        import shared_state as _ss
        with _ss._widget_history_lock:
            hist = list(_ss._widget_history.items())
            keep = dict(hist[-5:]) if len(hist) > 5 else dict(hist)
            _ss._widget_history.clear()
            _ss._widget_history.update(keep)
        mem_count = 0
        try:
            from smart_memory import SmartMemory
            sm = SmartMemory()
            mem_count = len(sm._hot)
        except Exception:
            pass
        try:
            import consolidation
            consolidation.consolidate_memories()
        except Exception:
            pass
        try:
            import orchestrator as _orch
            with _orch._history_lock:
                if len(_orch.conversation_history) > 3:
                    _orch.conversation_history = _orch.conversation_history[-3:]
        except Exception:
            pass
        return Result.success(f"Context compacted, Boss. Kept last 3 turns and consolidated memories ({mem_count} items).")
    except Exception as e:
        return Result.failure(str(e))


def _handle_think_level(ctx: DispatchContext) -> Result:
    """J2 — /think high|low: set FORCE_DEEP_THINK flag."""
    import re, config
    m = re.search(r'\b(high|deep|hard|max|low|fast|quick|shallow)\b', ctx.user_input.lower())
    if not m:
        return Result.success("Usage: /think high|deep|max|low|fast|quick")
    level = m.group(1)
    if level in ("high", "deep", "hard", "max"):
        config.FORCE_DEEP_THINK = True
        return Result.success("Deep think ON, Boss. I'll reason step by step and prefer high-context providers.")
    else:
        config.FORCE_DEEP_THINK = False
        return Result.success("Deep think OFF, Boss. Back to fast routing.")


def _handle_trace_toggle(ctx: DispatchContext) -> Result:
    """T5 — /trace on|off: toggle trace logging."""
    import re, config
    m = re.search(r'\b(on|off)\b', ctx.user_input.lower())
    if not m:
        return Result.success("Usage: /trace on|off")
    state = m.group(1)
    config.TRACE_ENABLED = (state == "on")
    return Result.success(f"Trace logging turned {state}, Boss.")


def _handle_agent_stop(ctx: DispatchContext) -> Result:
    """J3 — stop/cancel/abort agent: set _STOP_AGENT event."""
    try:
        from agent import interrupt_agent
        interrupt_agent()
        return Result.success("Stopping current task, Boss.")
    except Exception as e:
        return Result.failure(str(e))


def _handle_list_skills(ctx: DispatchContext) -> Result:
    """O1 — list skills: return loaded skill names."""
    try:
        from skills_loader import list_skills
        skills = list_skills()
        if not skills:
            return Result.success("No skills loaded, Boss.")
        return Result.success("Loaded skills: " + ", ".join(skills))
    except Exception as e:
        return Result.failure(str(e))


INTENT_HANDLERS = {
    "identity":        _handle_identity,
    "greeting":        _handle_identity,
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
    "open_app":        _handle_open_app,
    "shell":           _handle_shell,
    "file_query":      _handle_file_query,
    "create_file":     _handle_create_file,
    "delete_file":     _handle_delete_file,
    "rag":             _handle_rag,
    "data_analysis":   _handle_data_analysis,
    "agent":           _handle_agent,
    "council":         _handle_council,
    "decision":        _handle_decision,
    "morning_briefing": _handle_morning_briefing,
    "briefing":        _handle_briefing,
    "profile":         _handle_profile,
    "self_improve":    _handle_self_improve,
    "session_end":     _handle_session_end,
    "wake":            _handle_wake,
    "whatsapp":        _handle_whatsapp,
    "mcp":             _handle_mcp,
    "image_gen":       _handle_image_gen,
    "video_summarize": _handle_video_summarize,
    "system_health":   _handle_system_health,
    "repo_analyze":    _handle_repo_analyze,
    "compact":         _handle_compact,
    "think_level":     _handle_think_level,
    "trace_toggle":    _handle_trace_toggle,
    "agent_stop":      _handle_agent_stop,
    "list_skills":     _handle_list_skills,
}


def _validate_tool_output(output: str, intent: str) -> str:
    if not output or not output.strip():
        return f"I couldn't get a result for {intent} right now, Boss."
    if len(output) > 4000:
        return output[:4000] + "... [truncated]"
    return output


def _dispatch_single(ctx: DispatchContext) -> str:
    """Route one intent to its handler. No compound check — called by DAG executor."""
    handler = INTENT_HANDLERS.get(ctx.intent, _handle_chat_fallback)
    try:
        result = handler(ctx)
        if isinstance(result, Result):
            if result.ok:
                return _validate_tool_output(str(result.value), ctx.intent)
            log.error(f"Handler [{ctx.intent}] failure: {result.error} ({result.error_type})")
            return _friendly_error(ctx.intent, result.error)
        output = str(result) if result else ""
        return _validate_tool_output(output, ctx.intent) if output else _friendly_error(ctx.intent, "No response generated")
    except Exception as e:
        res = Result.from_exception(e)
        log.error(f"Dispatch exception [{ctx.intent}]: {res.error}")
        return _friendly_error(ctx.intent, res.error)


def dispatch(ctx: DispatchContext) -> str:
    """Route an intent to its handler via DispatchContext. Returns response string.

    Compound queries (with 'and then', 'then', 'also', etc.) are automatically
    split and executed through the DAG executor.
    """
    try:
        from compound_dag import detect_compound, split_into_tasks, DAGExecutor
        from intent import detect_intent

        if detect_compound(ctx.user_input):
            tasks = split_into_tasks(ctx.user_input)
            if len(tasks) >= 2:
                log.info(f"Compound intent detected — routing {len(tasks)} tasks through DAG")

                def _dag_execute(task_str):
                    sub_intent = detect_intent(task_str)
                    sub_ctx = DispatchContext(
                        user_input=task_str,
                        intent=sub_intent,
                        chat_fn=ctx.chat_fn,
                        source=ctx.source,
                    )
                    result_str = _dispatch_single(sub_ctx)
                    success = not result_str.startswith("Something went wrong") and bool(result_str)
                    return result_str, success

                dag = DAGExecutor(tasks, _dag_execute)
                dag_result = dag.execute_all()
                return dag_result.value if dag_result.ok else dag_result.error
    except Exception as e:
        log.warning(f"DAG routing failed, falling back to direct dispatch: {e}")

    return _dispatch_single(ctx)


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
            result = subprocess.run(shlex.split(cmd), capture_output=True, text=True, timeout=30, cwd=USER_HOME)
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
                subprocess.run(shlex.split(cmd), capture_output=True, text=True, timeout=30, cwd=USER_HOME)
                results.append(f"✅ Step {i}: `{cmd}` -> OK")
            except Exception as e:
                results.append(f"❌ Step {i}: `{cmd}` -> ERROR ({e})")
        return "🤖 Agent Execution Summary:\n\n" + "\n".join(results)

    elif atype == "fuzzy_confirm":
        import secrets as _sec
        base = action["resolved_path"]
        count = action.get("count", 1)
        named = action.get("named")
        created = []
        failed = []
        targets = [named] if named else [_sec.token_hex(4) for _ in range(count)]
        for name in targets:
            full = os.path.join(base, name)
            try:
                os.makedirs(full, exist_ok=True)
                if os.path.isdir(full):
                    created.append(name)
                else:
                    failed.append(f"{name}: created but not found on disk")
            except Exception as e:
                failed.append(f"{name}: {e}")
        if not created and failed:
            return (
                f"❌ All {count} folder(s) failed in `{base}`:\n"
                + "\n".join(f"  • {f}" for f in failed[:5])
            )
        summary = f"📁 Created {len(created)}/{count} folder(s) in `{base}`:\n"
        summary += "\n".join(f"  • {n}" for n in created)
        if failed:
            summary += f"\n\n❌ Failed ({len(failed)}): {', '.join(failed[:5])}"
        return summary

    return "Unknown action type."
