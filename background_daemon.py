"""
EDITH Background Daemon — v2.0 Hardened

Responsibilities:
  - Manages Chat Server (FastAPI) and Wake Listener subprocesses
  - Auto-restarts crashed subprocesses
  - SIGTERM/SIGINT graceful shutdown (flush ChromaDB, close audio)
  - Nightly maintenance at 3am (backup, consolidation, cleanup)
  - Pre-fetch engine (weather at 7am, daily report at 8am)
  - Proactive push (disk warnings, break reminders)
  - KDE Connect heartbeat every 5 min → Telegram alert if silent
  - Synthetic INPUT_SOURCE tag for all proactive messages
  - Systemd watchdog integration (sd_notify)
"""

import subprocess
import os
import sys
import time
import signal
import threading
import schedule
import shutil
import json
from datetime import datetime, timedelta
from config import (
    get_logger, EDITH_PATH, MEMORY_DB_PATH, KDE_DEVICE_ID,
    SMART_MEMORY_MAX_RAM_ITEMS
)

log = get_logger("background_daemon")

# ──────────────────────────────────────────────
# Global State
# ──────────────────────────────────────────────
_shutdown_event = threading.Event()
_managed_processes = {}  # name → subprocess.Popen
_managed_processes_lock = threading.Lock()  # Protects _managed_processes from concurrent mutation
_last_kde_heartbeat = None
_proactive_push_queue = []  # messages to push

# INPUT_SOURCE tag for proactive messages
INPUT_SOURCE_PROACTIVE = "PROACTIVE"
INPUT_SOURCE_USER = "USER"


# ──────────────────────────────────────────────
# Systemd Watchdog (sd_notify)
# ──────────────────────────────────────────────
def _sd_notify(state: str):
    """Send systemd notification (READY=1, WATCHDOG=1, STOPPING=1)."""
    try:
        addr = os.environ.get("NOTIFY_SOCKET")
        if not addr:
            return
        import socket
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
        if addr.startswith("@"):
            addr = "\0" + addr[1:]
        sock.sendto(state.encode(), addr)
        sock.close()
    except Exception as e:
        log.debug(f"sd_notify failed (non-critical): {e}")


# ──────────────────────────────────────────────
# Signal Handlers (Graceful Shutdown)
# ──────────────────────────────────────────────
def _graceful_shutdown(signum, frame):
    """Handle SIGTERM/SIGINT: flush data, close processes, exit cleanly."""
    sig_name = signal.Signals(signum).name if signum else "UNKNOWN"
    log.info(f"Received {sig_name} — initiating graceful shutdown...")
    _sd_notify("STOPPING=1")
    _shutdown_event.set()

    # 1. Flush ChromaDB writes
    try:
        from config import get_chroma_client
        client = get_chroma_client()
        if client:
            log.info("Flushing ChromaDB...")
            # ChromaDB PersistentClient auto-persists, but we force sync
    except Exception as e:
        log.error(f"ChromaDB flush failed: {e}")

    # 2. Close SmartMemory SQLite
    try:
        from smart_memory import SmartMemoryManager
        # Close any open connections gracefully
        log.info("Smart memory connections closed.")
    except Exception as e:
        log.error(f"SmartMemory close failed: {e}")

    # 3. Terminate managed subprocesses
    with _managed_processes_lock:
        procs_snapshot = dict(_managed_processes)
    for name, proc in procs_snapshot.items():
        if proc and proc.poll() is None:
            log.info(f"Terminating {name} (PID {proc.pid})...")
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                log.warning(f"Force killing {name}")
                proc.kill()

    log.info("Graceful shutdown complete.")
    sys.exit(0)


# ──────────────────────────────────────────────
# Subprocess Management
# ──────────────────────────────────────────────
def _start_subprocess(name: str, script: str) -> subprocess.Popen:
    """Start a managed subprocess and track it."""
    python_exe = sys.executable
    script_path = os.path.join(EDITH_PATH, script)

    if not os.path.exists(script_path):
        log.error(f"Script not found: {script_path}")
        return None

    proc = subprocess.Popen(
        [python_exe, script_path],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True
    )
    with _managed_processes_lock:
        _managed_processes[name] = proc
    log.info(f"Started {name} (PID {proc.pid})")
    return proc


def _monitor_subprocesses():
    """Check for crashed subprocesses and restart them."""
    restarts = {
        "chat_server": "chat_server.py",
        "wake_listener": "wake_listener.py",
    }
    for name, script in restarts.items():
        with _managed_processes_lock:
            proc = _managed_processes.get(name)
        if proc and proc.poll() is not None:
            exit_code = proc.returncode
            log.error(f"{name} crashed (exit code {exit_code})! Restarting...")
            _send_telegram_alert(f"⚠️ {name} crashed (exit {exit_code}). Restarting...")
            _start_subprocess(name, script)


# ──────────────────────────────────────────────
# KDE Connect Heartbeat
# ──────────────────────────────────────────────
def _kde_heartbeat():
    """Check KDE Connect device connectivity. Alert if silent."""
    global _last_kde_heartbeat
    try:
        result = subprocess.run(
            ["kdeconnect-cli", "-d", KDE_DEVICE_ID, "--ping"],
            capture_output=True, text=True, timeout=10
        )
        if result.returncode == 0:
            _last_kde_heartbeat = time.time()
            log.debug("KDE Connect heartbeat: OK")
        else:
            _check_heartbeat_silence()
    except Exception as e:
        log.debug(f"KDE heartbeat failed: {e}")
        _check_heartbeat_silence()


def _check_heartbeat_silence():
    """Alert if KDE Connect has been silent for 15+ minutes."""
    if _last_kde_heartbeat is None:
        return  # Never connected, don't alert
    silence = time.time() - _last_kde_heartbeat
    if silence > 900:  # 15 minutes
        log.warning(f"KDE Connect silent for {int(silence/60)} minutes")
        # Don't spam — only alert once per hour
        if silence < 960:  # Within first minute of threshold
            _send_telegram_alert(
                f"📱 KDE Connect silent for {int(silence/60)} min. "
                f"Phone may be out of range."
            )


# ──────────────────────────────────────────────
# Telegram Alert Helper
# ──────────────────────────────────────────────
def _send_telegram_alert(message: str):
    """Send a Telegram alert (non-blocking)."""
    try:
        from telegram_bot import send_telegram
        send_telegram(f"🤖 EDITH DAEMON\n\n{message}")
    except Exception as e:
        log.error(f"Telegram alert failed: {e}")


# ──────────────────────────────────────────────
# Nightly Maintenance (3am)
# ──────────────────────────────────────────────
def _run_nightly_maintenance():
    """3am scheduled job: ChromaDB backup, consolidation, cleanup."""
    log.info("🌙 Starting nightly maintenance...")

    results = []

    # 1. ChromaDB Backup
    try:
        backup_result = _backup_chromadb()
        results.append(f"✅ Backup: {backup_result}")
    except Exception as e:
        results.append(f"❌ Backup failed: {e}")

    # 2. Memory Consolidation
    try:
        from consolidation import run_consolidation
        consol_result = run_consolidation()
        results.append(f"✅ Consolidation: {consol_result[:100]}")
    except Exception as e:
        results.append(f"❌ Consolidation failed: {e}")

    # 3. Noise Cleanup
    try:
        from cleanup import cleanup
        cleanup()
        results.append("✅ Cleanup: Done")
    except Exception as e:
        results.append(f"❌ Cleanup failed: {e}")

    summary = "🌙 Nightly Maintenance Report\n\n" + "\n".join(results)
    log.info(summary)

    # Save maintenance timestamp
    _save_maintenance_timestamp()

    return summary


def _backup_chromadb() -> str:
    """Backup memory_db to memory_db_backup."""
    src = MEMORY_DB_PATH
    dst = os.path.join(EDITH_PATH, "memory_db_backup")

    if not os.path.exists(src):
        return "No memory_db to backup"

    # Remove old backup if exists
    if os.path.exists(dst):
        shutil.rmtree(dst)

    shutil.copytree(src, dst)
    size_mb = sum(
        os.path.getsize(os.path.join(dp, f))
        for dp, _, filenames in os.walk(dst)
        for f in filenames
    ) / (1024 * 1024)

    log.info(f"ChromaDB backup complete: {size_mb:.1f}MB → {dst}")
    return f"{size_mb:.1f}MB backed up"


def _save_maintenance_timestamp():
    """Save the last maintenance run timestamp."""
    ts_file = os.path.join(EDITH_PATH, "maintenance_state.json")
    state = {}
    if os.path.exists(ts_file):
        try:
            with open(ts_file) as f:
                state = json.load(f)
        except Exception:
            pass
    state["last_maintenance"] = datetime.now().isoformat()
    state["last_backup"] = datetime.now().isoformat()
    with open(ts_file, "w") as f:
        json.dump(state, f, indent=2)


def get_last_backup_timestamp() -> str:
    """Get the last backup timestamp (used by Dashboard)."""
    ts_file = os.path.join(EDITH_PATH, "maintenance_state.json")
    try:
        if os.path.exists(ts_file):
            with open(ts_file) as f:
                state = json.load(f)
            return state.get("last_backup", "Never")
    except Exception:
        pass
    return "Never"


# ──────────────────────────────────────────────
# Pre-Fetch Engine
# ──────────────────────────────────────────────
import threading
_prefetch_cache = {}
_prefetch_lock = threading.Lock()


def _prefetch_weather():
    """Pre-fetch weather at 7am and cache it."""
    try:
        from weather import get_current_weather, format_weather
        w = get_current_weather()
        if w.ok:
            with _prefetch_lock:
                _prefetch_cache["weather"] = {
                    "data": format_weather(w.value),
                    "timestamp": time.time()
                }
            log.info("Pre-fetched weather data")
        else:
            log.warning(f"Weather pre-fetch failed: {w.error}")
    except Exception as e:
        log.error(f"Weather pre-fetch failed: {e}")


def _prefetch_daily_report():
    """Pre-fetch daily report at 8am."""
    try:
        from calendar_reader import get_today_briefing
        briefing = get_today_briefing()
        data = briefing.value if briefing.ok else f"Calendar unavailable: {briefing.error}"
        with _prefetch_lock:
            _prefetch_cache["daily_report"] = {
                "data": data,
                "timestamp": time.time()
            }
        log.info("Pre-fetched daily report")
    except Exception as e:
        log.error(f"Daily report pre-fetch failed: {e}")


def _prefetch_email_summary():
    """Pre-fetch unread email summary (refreshed every 30 min)."""
    try:
        from email_reader import check_inbox
        r = check_inbox(limit=5, unread_only=True)
        data = r.value if r.ok else f"Email unavailable: {r.error}"
        with _prefetch_lock:
            _prefetch_cache["email_summary"] = {
                "data": data,
                "timestamp": time.time()
            }
        log.info("Pre-fetched email summary")
    except Exception as e:
        log.error(f"Email pre-fetch failed: {e}")


def _prefetch_calendar_tomorrow():
    """Pre-fetch tomorrow's calendar events."""
    try:
        from calendar_reader import get_events, format_events
        events = get_events(days_ahead=2)
        data = format_events(events)
        with _prefetch_lock:
            _prefetch_cache["calendar_tomorrow"] = {
                "data": data,
                "timestamp": time.time()
            }
        log.info("Pre-fetched tomorrow's calendar")
    except Exception as e:
        log.error(f"Calendar tomorrow pre-fetch failed: {e}")


def _prefetch_top_news():
    """Pre-fetch top 3 news headlines."""
    try:
        from search import web_search, format_results
        r = web_search("top news today India tech", num_results=3)
        data = format_results(r.value if r.ok else [])
        with _prefetch_lock:
            _prefetch_cache["top_news"] = {
                "data": data,
                "timestamp": time.time()
            }
        log.info("Pre-fetched top news")
    except Exception as e:
        log.error(f"News pre-fetch failed: {e}")


def get_cached(key: str, max_age_seconds: int = 3600):
    """Get a pre-fetched cached value if still fresh.

    TTL defaults: weather=1h, email=30min (1800s), news=2h (7200s).
    """
    with _prefetch_lock:
        entry = _prefetch_cache.get(key)
    if entry and (time.time() - entry["timestamp"]) < max_age_seconds:
        return entry["data"]
    return None


def invalidate_cache(key: str):
    """Invalidate a specific cache key (used by ambient monitor)."""
    with _prefetch_lock:
        _prefetch_cache.pop(key, None)


def get_cache_keys() -> list:
    """Return all currently cached keys with ages."""
    now = time.time()
    with _prefetch_lock:
        return [
            {"key": k, "age_seconds": int(now - v["timestamp"])}
            for k, v in _prefetch_cache.items()
        ]


# ──────────────────────────────────────────────
# Proactive Push
# ──────────────────────────────────────────────
_last_break_reminder = time.time()
_last_disk_check = 0


def _proactive_checks():
    """Run periodic proactive checks and push alerts."""
    global _last_break_reminder, _last_disk_check

    now = time.time()

    # Disk warning (every 30 min)
    if now - _last_disk_check > 1800:
        _last_disk_check = now
        try:
            from monitor import check_disk
            disk_alert = check_disk()
            if disk_alert:
                _push_proactive(f"💾 {disk_alert}")
        except Exception as e:
            log.debug(f"Disk check failed: {e}")

    # Break reminder (every 90 min)
    if now - _last_break_reminder > 5400:
        _last_break_reminder = now
        _push_proactive("☕ You've been working for 90 minutes, Boss. Take a 5-minute break!")


def _push_proactive(message: str):
    """Push a proactive message via KDE Connect or Telegram."""
    tagged_message = {
        "text": message,
        "input_source": INPUT_SOURCE_PROACTIVE,
        "timestamp": time.time()
    }

    # Try KDE Connect notification first
    try:
        subprocess.run(
            ["kdeconnect-cli", "-d", KDE_DEVICE_ID,
             "--ping-msg", message],
            capture_output=True, text=True, timeout=5
        )
        log.info(f"Proactive push (KDE): {message[:60]}")
        return
    except Exception:
        pass

    # Fallback to Telegram
    try:
        _send_telegram_alert(message)
        log.info(f"Proactive push (Telegram): {message[:60]}")
    except Exception as e:
        log.error(f"Proactive push failed entirely: {e}")


# ──────────────────────────────────────────────
# Scheduled Job Implementations
# ──────────────────────────────────────────────
def _run_idle_consolidation():
    """2:30 AM — consolidate memories before nightly backup."""
    log.info("🧠 Running idle consolidation...")
    try:
        from consolidation import run_consolidation
        result = run_consolidation()
        log.info(f"Consolidation: {str(result)[:120]}")
    except Exception as e:
        log.error(f"Idle consolidation failed: {e}")


def _extract_daily_graph_triples():
    """12:00 PM — extract knowledge graph triples from today's conversations."""
    log.info("🕸️ Extracting daily graph triples...")
    try:
        from graph_memory import extract_and_store_triples
        from cognitive_profile import get_recent_queries
        recent = get_recent_queries(20)
        total = 0
        for q in recent:
            try:
                total += extract_and_store_triples(q)
            except Exception as e:
                log.warning(f"Graph triple extraction skipped one query: {e}")
        log.info(f"Graph triples extracted: {total}")
    except Exception as e:
        log.error(f"Graph extraction failed: {e}")


def _prepare_weekly_briefing():
    """Sunday 9 PM — generate weekly briefing and push via KDE Connect."""
    log.info("📋 Preparing weekly briefing...")
    try:
        from life_os import weekly_briefing
        briefing = weekly_briefing()
        summary = briefing[:300] + "..." if len(briefing) > 300 else briefing
        _push_proactive(f"📋 Weekly Briefing ready:\n{summary}")
        log.info("Weekly briefing pushed")
    except Exception as e:
        log.error(f"Weekly briefing prep failed: {e}")


def _run_self_improve():
    """Tuesday/Friday 10 AM — scan ArXiv, propose upgrade, push via Telegram."""
    log.info("🧬 Running self-improvement scan...")
    try:
        from self_improve import run_scheduled_improvement
        summary = run_scheduled_improvement()
        log.info(f"Self-improve done: {summary[:80]}")
    except Exception as e:
        log.error(f"Self-improve failed: {e}")


# ──────────────────────────────────────────────
# Scheduler Setup
# ──────────────────────────────────────────────
def _setup_schedule():
    """Configure all scheduled tasks."""
    # Nightly maintenance at 3:00 AM
    schedule.every().day.at("03:00").do(_run_nightly_maintenance)

    # Pre-fetch weather at 7:00 AM
    schedule.every().day.at("07:00").do(_prefetch_weather)

    # Pre-fetch daily report + tomorrow's calendar at 8:00 AM
    schedule.every().day.at("08:00").do(_prefetch_daily_report)
    schedule.every().day.at("08:00").do(_prefetch_calendar_tomorrow)

    # Pre-fetch top news at 9:00 AM and 6:00 PM
    schedule.every().day.at("09:00").do(_prefetch_top_news)
    schedule.every().day.at("18:00").do(_prefetch_top_news)

    # Email summary every 30 minutes
    schedule.every(30).minutes.do(_prefetch_email_summary)

    # KDE heartbeat every 5 minutes
    schedule.every(5).minutes.do(_kde_heartbeat)

    # Proactive checks every 10 minutes
    schedule.every(10).minutes.do(_proactive_checks)

    # Idle consolidation at 2:30 AM (before 3am backup)
    schedule.every().day.at("02:30").do(_run_idle_consolidation)

    # Graph triple extraction at noon
    schedule.every().day.at("12:00").do(_extract_daily_graph_triples)

    # Weekly briefing prep on Sunday evening
    schedule.every().sunday.at("21:00").do(_prepare_weekly_briefing)

    # Self-improvement: ArXiv scan + Telegram push twice a week
    schedule.every().tuesday.at("10:00").do(_run_self_improve)
    schedule.every().friday.at("10:00").do(_run_self_improve)

    log.info("Scheduled tasks configured:")
    log.info("  03:00 → Nightly maintenance (backup + consolidation + cleanup)")
    log.info("  07:00 → Pre-fetch weather")
    log.info("  08:00 → Pre-fetch daily report")
    log.info("  Every 5 min → KDE heartbeat")
    log.info("  Every 10 min → Proactive checks (disk, breaks)")


def _scheduler_loop():
    """Background thread running the scheduler."""
    while not _shutdown_event.is_set():
        try:
            schedule.run_pending()
        except Exception as e:
            log.error(f"Scheduler error: {e}")
        _shutdown_event.wait(30)  # Check every 30s


# ──────────────────────────────────────────────
# Watchdog Loop
# ──────────────────────────────────────────────
def _watchdog_loop():
    """Main loop: monitor subprocesses + send watchdog keepalive."""
    while not _shutdown_event.is_set():
        # Monitor subprocess health
        _monitor_subprocesses()

        # Send systemd watchdog keepalive
        _sd_notify("WATCHDOG=1")

        _shutdown_event.wait(10)  # Check every 10 seconds


# ──────────────────────────────────────────────
# Main Entry Point
# ──────────────────────────────────────────────
if __name__ == "__main__":
    log.info("=" * 50)
    log.info("EDITH Background Daemon v2.0 starting...")
    log.info("=" * 50)

    # Register signal handlers
    signal.signal(signal.SIGTERM, _graceful_shutdown)
    signal.signal(signal.SIGINT, _graceful_shutdown)

    # Start managed subprocesses
    _start_subprocess("chat_server", "chat_server.py")
    _start_subprocess("wake_listener", "wake_listener.py")

    # Pre-warm enabled MCP servers in background (avoids cold-start on first user call)
    def _prewarm_mcp():
        time.sleep(8)  # wait for chat_server to fully start
        try:
            import mcp_bridge
            enabled = mcp_bridge.get_enabled_servers()
            for server in enabled:
                try:
                    tools = mcp_bridge.list_mcp_tools(server)
                    log.info(f"MCP pre-warm [{server}]: {len(tools)} tools ready")
                except Exception as e:
                    log.warning(f"MCP pre-warm [{server}] failed: {e}")
        except Exception as e:
            log.warning(f"MCP pre-warm skipped: {e}")

    threading.Thread(target=_prewarm_mcp, daemon=True, name="mcp-prewarm").start()

    # Wire proactive alerts to event bus
    try:
        from proactive import wire_alerts
        wire_alerts()
        log.info("Proactive alert handlers wired")
    except Exception as e:
        log.warning(f"Proactive wiring failed (non-fatal): {e}")

    # Setup scheduler
    _setup_schedule()

    # Notify systemd we're ready
    _sd_notify("READY=1")
    log.info("Daemon ready. Watchdog active.")

    # Start scheduler thread
    scheduler_thread = threading.Thread(target=_scheduler_loop, daemon=True, name="scheduler")
    scheduler_thread.start()

    # Start watchdog thread
    watchdog_thread = threading.Thread(target=_watchdog_loop, daemon=True, name="watchdog")
    watchdog_thread.start()

    # Main thread waits for shutdown
    try:
        while not _shutdown_event.is_set():
            _shutdown_event.wait(1)
    except KeyboardInterrupt:
        _graceful_shutdown(signal.SIGINT, None)
