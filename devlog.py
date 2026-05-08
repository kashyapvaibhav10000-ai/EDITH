import re
import os
import datetime
import threading
import time
import vault
from dotenv import load_dotenv
from config import DEVLOG_PATH, SIMPLENOTE_EMAIL, SIMPLENOTE_PASSWORD, get_logger

load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))

log = get_logger("devlog")
_file_lock = threading.Lock()  # Protects devlog.md from concurrent read/write

def _format_entry(change, reason, status, error, next_plan):
    """Formats log fields into a warm, humanized journal entry."""
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    
    # Humanized status mapping
    status_map = {
        "success": "Everything went smoothly this time around.",
        "failed": "I hit a bit of a snag during the process.",
        "partial": "I made some progress, but there's still more to do.",
        "ongoing": "I'm still in the middle of this one.",
        "fixed": "I managed to squash that bug for good.",
        "broken": "Things aren't quite working right at the moment."
    }
    
    s_lower = status.lower().strip()
    status_desc = status_map.get(s_lower, f"The status of this work is: {status}.")
    
    # Handle error description
    err_desc = ""
    if error and error.lower().strip() not in ["none", "no", "n/a", ""]:
        err_desc = f" Unfortunately, I ran into an error along the way: {error}."

    # First-person, conversational tone
    entry = f"""## Journal Entry: {now}

Today I spent some time working on **{change.strip()}**. My primary motivation for this was **{reason.strip()}**.

{status_desc}{err_desc}

Looking ahead, my plan is to **{next_plan.strip()}**.

---
"""
    return entry

def add_entry(change, reason, status, error, next_plan):
    """Appends a new journal entry to the local devlog.md."""
    entry = _format_entry(change, reason, status, error, next_plan)
    
    # Ensure directory exists
    os.makedirs(os.path.dirname(DEVLOG_PATH), exist_ok=True)
    
    with _file_lock:
        with open(DEVLOG_PATH, "a") as f:
            f.write(entry + "\n")
    
    log.info("New journal entry recorded in devlog.md")
    return "Progress recorded! I've added a new entry to our development journal, Boss."

def parse_log_command(text):
    """Parses user input for log-specific commands.
    
    Commands:
    - log: <change> reason: <why> status: <status> error: <err> next: <plan>
    - show log
    - sync log
    """
    text = text.strip()
    
    # Regex to capture the standard log command format
    # Note: Using [\s\S]* to allow multi-line or complex strings in fields
    pattern = r"log:\s*([\s\S]*?)\s*reason:\s*([\s\S]*?)\s*status:\s*([\s\S]*?)\s*error:\s*([\s\S]*?)\s*next:\s*([\s\S]*)"
    log_match = re.match(pattern, text, re.IGNORECASE)
    
    if log_match:
        change, reason, status, error, next_plan = log_match.groups()
        return add_entry(change, reason, status, error, next_plan)
    
    # Show last entries
    if text.lower() == "show log":
        if not os.path.exists(DEVLOG_PATH):
            return "The development journal is currently empty, Boss."
        
        try:
            with _file_lock:
                with open(DEVLOG_PATH, "r") as f:
                    content = f.read()
                # Split by divider and filter empty strings
                entries = [e.strip() for e in content.split("---") if e.strip() and not e.startswith("# EDITH")]
                if not entries:
                    return "The journal exists, but I couldn't find any entries yet."
                
                # Format the last 3 entries for display
                display = "\n\n---\n".join(entries[-3:])
                return f"📋 Here are our most recent journal entries:\n\n{display}"
        except Exception as e:
            return f"I had some trouble reading the journal: {e}"
            
    # Trigger manual sync
    if text.lower() == "sync log":
        log.info("Manual sync triggered by user.")
        _sync_to_simplenote()
        return "I'm synchronizing our development journal with Simplenote right now, Boss."
        
    return None

def _sync_to_simplenote():
    """Syncs the entire devlog.md to Simplenote, replacing existing content."""
    if not SIMPLENOTE_EMAIL or not SIMPLENOTE_PASSWORD:
        log.warning("Simplenote sync skipped: Credentials not set.")
        return

    try:
        import simplenote
        sn = simplenote.Simplenote(SIMPLENOTE_EMAIL, SIMPLENOTE_PASSWORD)
        
        if not os.path.exists(DEVLOG_PATH):
            log.info("Sync skipped: devlog.md does not exist.")
            return
            
        with _file_lock:
            with open(DEVLOG_PATH, "r") as f:
                full_content = f.read()
            
        # Add a title header for Simplenote recognition
        content_to_sync = f"EDITH DevLog\n\n{full_content}"
        
        # Search for existing note
        notes, res = sn.get_note_list()
        if res != 0:
            log.error("Failed to retrieve notes from Simplenote.")
            return
            
        dev_note = None
        for n in notes:
            # We match by the first line of content
            c = n.get("content", "")
            if c.startswith("EDITH DevLog"):
                dev_note = n
                break
        
        if dev_note:
            # Update existing
            dev_note["content"] = content_to_sync
            # Ensure the tag is there
            if "edith-devlog" not in dev_note.get("tags", []):
                tags = dev_note.get("tags", [])
                tags.append("edith-devlog")
                dev_note["tags"] = tags
                
            update_res, update_status = sn.update_note(dev_note)
            if update_status == 0:
                log.info("Simplenote: Successfully updated the DevLog note.")
            else:
                log.error(f"Simplenote: Failed to update note. Status: {update_status}")
        else:
            # Create new
            new_note = {
                "content": content_to_sync,
                "tags": ["edith-devlog"]
            }
            add_res, add_status = sn.add_note(new_note)
            if add_status == 0:
                log.info("Simplenote: Created a new DevLog note.")
            else:
                log.error(f"Simplenote: Failed to create note. Status: {add_status}")
            
    except Exception as e:
        log.error(f"Simplenote sync process encountered an error: {e}")

def _generate_status_report():
    """Auto-generate a humanized system health report. Returns the report string."""
    now = datetime.datetime.now()
    time_str = now.strftime("%d %b %Y, %I:%M %p")
    hour = now.hour
    greeting = "Good morning" if hour < 12 else "Good afternoon" if hour < 17 else "Good evening"

    sections = []

    # 1. Uptime
    try:
        import psutil
        boot_time = datetime.datetime.fromtimestamp(psutil.boot_time())
        uptime = now - boot_time
        hours = int(uptime.total_seconds() // 3600)
        mins = int((uptime.total_seconds() % 3600) // 60)
        sections.append(f"Your PC has been running for {hours} hours and {mins} minutes.")
    except Exception:
        pass

    # 2. Circuit breaker status
    try:
        from circuit_breaker import get_all_status
        statuses = get_all_status()
        up = [k for k, v in statuses.items() if v.get("state") == "closed"]
        down = [k for k, v in statuses.items() if v.get("state") != "closed"]
        if up and not down:
            sections.append(f"All AI services are online and healthy: {', '.join(up)}.")
        elif up and down:
            sections.append(f"Most services are up ({', '.join(up)}), but {', '.join(down)} seem to be having trouble right now.")
        elif down and not up:
            # Only report degraded if EDITH has been running long enough to test them
            sections.append(f"I haven't been able to reach {', '.join(down)} yet — they may just need a moment to warm up.")
    except Exception:
        pass

    # 3. Disk usage
    try:
        import shutil
        usage = shutil.disk_usage("/")
        free_gb = usage.free / (1024**3)
        total_gb = usage.total / (1024**3)
        used_pct = int((usage.used / usage.total) * 100)
        if free_gb < 5:
            sections.append(f"Heads up — disk is getting full. Only {free_gb:.1f} GB left out of {total_gb:.1f} GB ({used_pct}% used).")
        else:
            sections.append(f"Disk is looking fine — {free_gb:.1f} GB free out of {total_gb:.1f} GB total.")
    except Exception:
        pass

    # 4. Knowledge graph
    try:
        from graph_memory import graph_stats
        stats = graph_stats()
        sections.append(f"My knowledge base is growing: {stats}.")
    except Exception:
        pass

    # 5. Session info
    try:
        from session import get_session_id, get_session_device
        sid = get_session_id()
        dev = get_session_device()
        if sid != "unknown":
            sections.append(f"Currently in session {sid} on {dev}.")
    except Exception:
        pass

    body = "\n\n".join(sections) if sections else "Everything looks quiet on my end."

    telegram_msg = (
        f"🤖 EDITH Check-In — {time_str}\n\n"
        f"{greeting}, Boss!\n\n"
        f"{body}\n\n"
        f"I'll check in again in 30 minutes. Stay productive! 💪"
    )

    # Write raw version to devlog.md
    raw_entry = f"## Auto Status Report: {now.strftime('%Y-%m-%d %H:%M')}\n\n{body}\n\n---\n"
    try:
        os.makedirs(os.path.dirname(DEVLOG_PATH), exist_ok=True)
        with _file_lock:
            with open(DEVLOG_PATH, "a") as f:
                f.write(raw_entry + "\n")
        log.info("Auto status report written to devlog.md")
    except Exception as e:
        log.error(f"Failed to write status report: {e}")

    return telegram_msg


def _send_telegram_report(report: str):
    """Send status report via Telegram."""
    try:
        import httpx
        token = vault.get_secret("TELEGRAM_TOKEN", "") or os.getenv("TELEGRAM_TOKEN", "")
        chat_id = vault.get_secret("TELEGRAM_CHAT_ID", "") or os.getenv("TELEGRAM_CHAT_ID", "")
        if not token or not chat_id:
            log.warning("Telegram report skipped: TOKEN or CHAT_ID not set.")
            return
        msg = f"EDITH DevLog — Auto Report\n\n{report}"
        chunks = [msg[i:i+4000] for i in range(0, len(msg), 4000)]
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        for chunk in chunks:
            r = httpx.post(url, json={"chat_id": chat_id, "text": chunk}, timeout=10)
            if r.status_code != 200:
                log.error(f"Telegram send failed: {r.status_code} {r.text}")
                return
        log.info("Status report sent via Telegram.")
    except Exception as e:
        log.error(f"Telegram report send failed: {e}")


def _sync_loop():
    """Background loop: generate status report + send via Telegram every 30 min."""
    time.sleep(1800)  # Wait 30 min before first run to avoid blocking startup
    while True:
        try:
            report = _generate_status_report()
            _send_telegram_report(report)
            log.info("Periodic sync cycle complete.")
        except Exception as e:
            log.error(f"Sync loop error: {e}")
        time.sleep(1800)  # 30 minutes


def start_devlog():
    """Initializes the DevLog system and starts the background sync thread."""
    if not os.path.exists(DEVLOG_PATH):
        os.makedirs(os.path.dirname(DEVLOG_PATH), exist_ok=True)
        with open(DEVLOG_PATH, "w") as f:
            f.write("# EDITH Development Journal\n\n")
            f.write("A conversational record of my evolution and growth.\n\n---\n")
            
    # Use a daemon thread so it exits when the main process does
    thread = threading.Thread(target=_sync_loop, daemon=True, name="devlog-sync")
    thread.start()
    log.info("DevLog: Background sync thread is active (30m interval — auto status reports + Simplenote push).")

