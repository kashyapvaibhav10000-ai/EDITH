"""
EDITH Monitor — Proactive System Monitoring

Checks: disk usage, phone battery, weather, break reminders, stock alerts.
Used by background_daemon.py for proactive push notifications.
"""

import subprocess
import shutil
import time
import os
import json
import psutil
from datetime import datetime
from config import KDE_DEVICE_ID, EDITH_PATH, MEMORY_DB_PATH, get_logger

log = get_logger("monitor")


# ──────────────────────────────────────────────
# System Checks
# ──────────────────────────────────────────────
def check_disk(threshold: float = 85.0) -> str:
    """Check disk usage. Returns warning string or None if OK."""
    total, used, free = shutil.disk_usage("/")
    percent = (used / total) * 100
    free_gb = free / (1024**3)
    if percent > threshold:
        return f"WARNING: Disk is {percent:.1f}% full! Only {free_gb:.1f}GB free."
    return None


def check_ram() -> dict:
    """Get current RAM usage stats."""
    mem = psutil.virtual_memory()
    return {
        "percent": mem.percent,
        "used_gb": round(mem.used / (1024**3), 1),
        "total_gb": round(mem.total / (1024**3), 1),
        "available_gb": round(mem.available / (1024**3), 1),
    }


def check_cpu() -> dict:
    """Get current CPU usage."""
    return {
        "percent": psutil.cpu_percent(interval=1),
        "cores": psutil.cpu_count(),
        "load_avg": os.getloadavg(),
    }


def check_phone_battery():
    """Check phone battery via KDE Connect. Returns string or None."""
    try:
        result = subprocess.run(
            ["kdeconnect-cli", "-d", KDE_DEVICE_ID, "--battery"],
            capture_output=True, text=True, timeout=5
        )
        output = result.stdout.strip()
        if output:
            return output
    except Exception:
        pass
    return None


def check_weather():
    """Get current weather. Returns formatted string or error."""
    try:
        from weather import get_current_weather, format_weather
        w = get_current_weather()
        return format_weather(w) if w else "Weather unavailable"
    except Exception as e:
        return f"Weather unavailable: {e}"


def check_breaks(last_break: float) -> str:
    """Check if user needs a break. Returns reminder or None."""
    now = time.time()
    if now - last_break > 3600:
        return "You have been working for over an hour. Take a 5 minute break!"
    return None


# ──────────────────────────────────────────────
# ChromaDB Backup
# ──────────────────────────────────────────────
def backup_chromadb() -> str:
    """Full backup of memory_db to memory_db_backup."""
    src = MEMORY_DB_PATH
    dst = os.path.join(EDITH_PATH, "memory_db_backup")

    if not os.path.exists(src):
        return "No memory_db to backup"

    # Remove old backup
    if os.path.exists(dst):
        shutil.rmtree(dst)

    shutil.copytree(src, dst)

    # Calculate size
    size_mb = sum(
        os.path.getsize(os.path.join(dp, f))
        for dp, _, filenames in os.walk(dst)
        for f in filenames
    ) / (1024 * 1024)

    # Save timestamp
    _update_maintenance_state("last_backup", datetime.now().isoformat())

    log.info(f"ChromaDB backup complete: {size_mb:.1f}MB → {dst}")
    return f"{size_mb:.1f}MB backed up to {dst}"


def get_last_backup_timestamp() -> str:
    """Get the last backup timestamp."""
    state = _load_maintenance_state()
    return state.get("last_backup", "Never")


def get_last_maintenance_timestamp() -> str:
    """Get the last maintenance run timestamp."""
    state = _load_maintenance_state()
    return state.get("last_maintenance", "Never")


# ──────────────────────────────────────────────
# Maintenance State Persistence
# ──────────────────────────────────────────────
_MAINTENANCE_STATE_FILE = os.path.join(EDITH_PATH, "maintenance_state.json")


def _load_maintenance_state() -> dict:
    """Load maintenance state from disk."""
    try:
        if os.path.exists(_MAINTENANCE_STATE_FILE):
            with open(_MAINTENANCE_STATE_FILE) as f:
                return json.load(f)
    except Exception:
        pass
    return {}


def _update_maintenance_state(key: str, value):
    """Update a single key in maintenance state."""
    state = _load_maintenance_state()
    state[key] = value
    try:
        with open(_MAINTENANCE_STATE_FILE, "w") as f:
            json.dump(state, f, indent=2)
    except Exception as e:
        log.error(f"Failed to save maintenance state: {e}")


# ──────────────────────────────────────────────
# Resource Mode
# ──────────────────────────────────────────────
def is_resource_constrained() -> bool:
    """Check if system is under resource pressure (RAM > 85%)."""
    ram = check_ram()
    return ram["percent"] > 85


def get_resource_mode() -> str:
    """Return 'light' if constrained, 'full' otherwise."""
    return "light" if is_resource_constrained() else "full"


# ──────────────────────────────────────────────
# Full System Status (for Dashboard)
# ──────────────────────────────────────────────
def get_system_status() -> dict:
    """Get comprehensive system status for Dashboard."""
    ram = check_ram()
    disk_alert = check_disk()

    return {
        "ram": ram,
        "disk_alert": disk_alert,
        "disk_free_gb": round(shutil.disk_usage("/").free / (1024**3), 1),
        "disk_percent": round((shutil.disk_usage("/").used / shutil.disk_usage("/").total) * 100, 1),
        "phone_battery": check_phone_battery(),
        "last_backup": get_last_backup_timestamp(),
        "last_maintenance": get_last_maintenance_timestamp(),
        "resource_mode": get_resource_mode(),
        "timestamp": datetime.now().isoformat(),
    }


# ──────────────────────────────────────────────
# Phase 21: Unified Proactive Alerts
# ──────────────────────────────────────────────
def get_full_proactive_alerts(last_break_time: float) -> list:
    """Collect all proactive alerts in one call. Used by background_daemon."""
    alerts = []
    disk = check_disk()
    if disk:
        alerts.append(f"💾 {disk}")
    ram = check_ram()
    if ram["percent"] > 85:
        alerts.append(f"🚨 RAM {ram['percent']}% — consider closing apps")
    cpu = check_cpu()
    if cpu["percent"] > 90:
        alerts.append(f"🔥 CPU {cpu['percent']}% — high load")
    battery = check_phone_battery()
    if battery and any(w in battery.lower() for w in ["low", "5%", "10%", "15%", "20%"]):
        alerts.append(f"🔋 Phone: {battery}")
    break_msg = check_breaks(last_break_time)
    if break_msg:
        alerts.append(f"☕ {break_msg}")
    return alerts


# ──────────────────────────────────────────────
# Standalone Monitor Loop (legacy support)
# ──────────────────────────────────────────────
def run_monitor():
    """Standalone monitor loop (for edith.py menu option 9)."""
    print("[EDITH Monitor] Starting proactive monitoring...")
    log.info("Monitor started (standalone mode)")
    last_break = time.time()
    check_count = 0
    while True:
        alerts = []
        check_count += 1

        disk_alert = check_disk()
        if disk_alert:
            alerts.append(disk_alert)

        break_alert = check_breaks(last_break)
        if break_alert:
            alerts.append(break_alert)
            last_break = time.time()

        # Weather every 30 minutes (every 6th check at 5min intervals)
        if check_count % 6 == 0:
            weather = check_weather()
            if weather:
                alerts.append(f"Weather update: {weather}")

        # RAM check
        ram = check_ram()
        if ram["percent"] > 85:
            alerts.append(f"⚠️ RAM: {ram['percent']}% ({ram['used_gb']}GB / {ram['total_gb']}GB)")

        if alerts:
            print(f"\n[EDITH Monitor] {datetime.now().strftime('%H:%M')}")
            for alert in alerts:
                print(f"  >> {alert}")
                log.info(f"Alert: {alert}")

        time.sleep(600)  # Check every 10 minutes


if __name__ == "__main__":
    print("Testing individual checks...")
    print(f"Disk: {check_disk() or 'OK'}")
    print(f"RAM: {check_ram()}")
    print(f"Weather: {check_weather()}")
    print(f"Break needed: {check_breaks(0)}")
    print(f"Phone: {check_phone_battery() or 'Not connected'}")
    print(f"Resource mode: {get_resource_mode()}")
    print(f"Last backup: {get_last_backup_timestamp()}")
    print(f"\nFull status: {json.dumps(get_system_status(), indent=2)}")
