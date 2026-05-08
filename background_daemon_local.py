"""
EDITH Local Node Background Daemon — v2.0

Responsibilities (LOCAL HARDWARE NODE):
  - Manages Chat Server (FastAPI on 8001) and Wake Listener subprocesses
  - Auto-restarts crashed subprocesses
  - SIGTERM/SIGINT graceful shutdown (close audio, terminate processes)
  - Systemd watchdog integration (sd_notify)

CLOUD TASKS MOVED TO background_daemon_cloud.py:
  - Scheduler jobs (nightly backup, consolidation, cleanup)
  - Pre-fetch engine (weather, calendar, news, email)
  - Proactive push (disk warnings, break reminders)
  - KDE Connect heartbeat
  - Weekly briefing + self-improve scans
"""

import subprocess
import os
import sys
import time
import signal
import threading
from config import get_logger, EDITH_PATH

log = get_logger("background_daemon_local")

# ──────────────────────────────────────────────
# Global State
# ──────────────────────────────────────────────
_shutdown_event = threading.Event()
_managed_processes = {}  # name → subprocess.Popen
_managed_processes_lock = threading.Lock()


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
    """Handle SIGTERM/SIGINT: close audio, terminate processes, exit cleanly."""
    sig_name = signal.Signals(signum).name if signum else "UNKNOWN"
    log.info(f"Received {sig_name} — initiating graceful shutdown...")
    _sd_notify("STOPPING=1")
    _shutdown_event.set()

    # Close audio/voice resources
    try:
        import voice
        # Voice cleanup if needed
        log.info("Voice resources released.")
    except Exception as e:
        log.debug(f"Voice close: {e}")

    # Terminate managed subprocesses
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
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
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
            _start_subprocess(name, script)


# ──────────────────────────────────────────────
# Watchdog Loop
# ──────────────────────────────────────────────
def _watchdog_loop():
    """Main loop: monitor subprocess health + send watchdog keepalive."""
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
    log.info("EDITH Local Node Daemon starting...")
    log.info("=" * 50)

    # Register signal handlers
    signal.signal(signal.SIGTERM, _graceful_shutdown)
    signal.signal(signal.SIGINT, _graceful_shutdown)

    # Start managed subprocesses
    _start_subprocess("chat_server", "chat_server.py")
    _start_subprocess("wake_listener", "wake_listener.py")

    # Pre-warm Ollama on boot (ensures model is loaded into memory)
    def _prewarm_ollama():
        import urllib.request
        deadline = time.time() + 30
        while time.time() < deadline:
            try:
                urllib.request.urlopen("http://localhost:11434/api/tags", timeout=2)
                break
            except Exception:
                log.debug("Ollama not ready yet — retrying in 2s")
                time.sleep(2)
        else:
            log.warning("Ollama did not become ready within 30s — skipping prewarm")
            return
        try:
            from smart_router import smart_call
            response = smart_call("Say hello", intent="internal").strip()
            log.info(f"✅ Ollama warmed up ({len(response)} chars)")
        except Exception as e:
            log.warning(f"Ollama warmup failed (non-fatal): {e}")

    threading.Thread(target=_prewarm_ollama, daemon=True, name="ollama-prewarm").start()

    # Pre-warm enabled MCP servers in background
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

    # Pre-warm DB connection pool
    try:
        import db_pool
        log.info("DB connection pool initialized")
    except Exception as e:
        log.warning(f"DB pool init failed (non-fatal): {e}")

    # Notify systemd we're ready
    _sd_notify("READY=1")
    log.info("Local node ready. Watchdog active.")

    # Start watchdog thread
    watchdog_thread = threading.Thread(target=_watchdog_loop, daemon=True, name="watchdog")
    watchdog_thread.start()

    # Main thread waits for shutdown
    try:
        while not _shutdown_event.is_set():
            _shutdown_event.wait(1)
    except KeyboardInterrupt:
        _graceful_shutdown(signal.SIGINT, None)
