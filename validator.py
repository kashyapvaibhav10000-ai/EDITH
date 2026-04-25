"""
EDITH World State Validator — Item 3

Per-tool ground truth checks. Call validate_all() for a full system health snapshot,
or individual validate_*() functions before invoking a specific capability.
All functions return Result[str] (ok = capability available, failure = why not).
"""

import os
import shutil
import subprocess
import requests
import psutil

from config import OLLAMA_URL, MODELS, KDE_DEVICE_ID, EDITH_PATH, get_logger
from errors import Result

log = get_logger("validator")

# Thresholds
_MIN_DISK_GB = 1.0
_MIN_RAM_MB = 200


# ──────────────────────────────────────────────
# Individual Validators
# ──────────────────────────────────────────────

def validate_network() -> Result:
    """Check internet reachability via TCP socket to Cloudflare DNS."""
    import socket
    try:
        socket.setdefaulttimeout(5)
        with socket.create_connection(("1.1.1.1", 53)):
            return Result.success("Network reachable")
    except Exception as e:
        return Result.failure(f"Network unreachable: {e}", error_type="connection")


def validate_ollama() -> Result:
    """Check Ollama is running and the primary chat model is available."""
    try:
        r = requests.get(f"{OLLAMA_URL}/api/tags", timeout=5)
        r.raise_for_status()
        models = r.json().get("models", [])
        names = [m.get("name", "") for m in models]
        target = MODELS["chat"]
        available = any(target.split(":")[0] in n for n in names)
        if available:
            return Result.success(f"Ollama running, model '{target}' available")
        return Result.failure(
            f"Ollama running but '{target}' not found. Available: {names[:5]}",
            error_type="not_found"
        )
    except Exception as e:
        return Result.failure(f"Ollama not reachable: {e}", error_type="connection")


def validate_phone() -> Result:
    """Check KDE Connect device is paired and reachable."""
    try:
        if not shutil.which("kdeconnect-cli"):
            return Result.failure("kdeconnect-cli not installed", error_type="not_found")
        r = subprocess.run(
            ["kdeconnect-cli", "--list-devices", "--id-only"],
            capture_output=True, text=True, timeout=5
        )
        if KDE_DEVICE_ID in r.stdout:
            return Result.success(f"Phone connected (device {KDE_DEVICE_ID})")
        return Result.failure("Phone not paired or unreachable", error_type="connection")
    except subprocess.TimeoutExpired:
        return Result.failure("KDE Connect check timed out", error_type="timeout")
    except Exception as e:
        return Result.from_exception(e)


def validate_calendar() -> Result:
    """Check Google Calendar token exists and appears valid."""
    token_path = os.path.join(EDITH_PATH, "token.json")
    creds_path = os.path.join(EDITH_PATH, "credentials.json")
    if not os.path.exists(creds_path):
        return Result.failure("credentials.json missing — run OAuth setup", error_type="auth")
    if not os.path.exists(token_path):
        return Result.failure("token.json missing — run calendar auth flow", error_type="auth")
    try:
        import json
        with open(token_path) as f:
            tok = json.load(f)
        # Token exists and has required fields
        if tok.get("refresh_token") or tok.get("token"):
            return Result.success("Calendar token present")
        return Result.failure("token.json malformed — missing token fields", error_type="auth")
    except Exception as e:
        return Result.from_exception(e)


def validate_disk() -> Result:
    """Check free disk space on EDITH's partition."""
    try:
        usage = psutil.disk_usage(EDITH_PATH)
        free_gb = usage.free / (1024 ** 3)
        if free_gb >= _MIN_DISK_GB:
            return Result.success(f"Disk OK ({free_gb:.1f} GB free)")
        return Result.failure(
            f"Low disk space: {free_gb:.1f} GB free (need {_MIN_DISK_GB} GB)",
            error_type="resource"
        )
    except Exception as e:
        return Result.from_exception(e)


def validate_memory() -> Result:
    """Check available system RAM."""
    try:
        mem = psutil.virtual_memory()
        avail_mb = mem.available / (1024 ** 2)
        if avail_mb >= _MIN_RAM_MB:
            return Result.success(f"RAM OK ({avail_mb:.0f} MB available)")
        return Result.failure(
            f"Low RAM: {avail_mb:.0f} MB available (need {_MIN_RAM_MB} MB)",
            error_type="resource"
        )
    except Exception as e:
        return Result.from_exception(e)


def validate_vision_model() -> Result:
    """Check vision model is available in Ollama."""
    try:
        r = requests.get(f"{OLLAMA_URL}/api/tags", timeout=5)
        r.raise_for_status()
        models = r.json().get("models", [])
        names = [m.get("name", "") for m in models]
        target = MODELS["vision"]
        if any(target.split(":")[0] in n for n in names):
            return Result.success(f"Vision model '{target}' available")
        return Result.failure(
            f"Vision model '{target}' not installed. Run: ollama pull {target}",
            error_type="not_found"
        )
    except Exception as e:
        return Result.failure(f"Ollama not reachable for vision check: {e}", error_type="connection")


# ──────────────────────────────────────────────
# Full System Snapshot
# ──────────────────────────────────────────────

_VALIDATORS = [
    ("network",  validate_network),
    ("ollama",   validate_ollama),
    ("phone",    validate_phone),
    ("calendar", validate_calendar),
    ("disk",     validate_disk),
    ("memory",   validate_memory),
    ("vision",   validate_vision_model),
]


def validate_all(emit_events: bool = False) -> dict:
    """Run all validators. Returns dict[str, Result].

    If emit_events=True, publishes HEALTH_CRITICAL to event_bus for each failed check.
    """
    results = {}
    for name, fn in _VALIDATORS:
        try:
            results[name] = fn()
        except Exception as e:
            results[name] = Result.from_exception(e)

    if emit_events:
        try:
            from event_bus import health_critical
            for name, r in results.items():
                if not r.ok:
                    health_critical(name, r.error, source="validator")
        except Exception as e:
            log.warning(f"Event emit failed: {e}")

    return results


def format_health_report(results: dict) -> str:
    """Format validate_all() output into a human-readable health report."""
    lines = ["🩺 **EDITH System Health**\n"]
    ok_count = 0
    for name, r in results.items():
        icon = "✅" if r.ok else "❌"
        msg = r.value if r.ok else r.error
        lines.append(f"{icon} **{name}**: {msg}")
        if r.ok:
            ok_count += 1
    lines.append(f"\n{ok_count}/{len(results)} systems operational")
    return "\n".join(lines)


if __name__ == "__main__":
    import json
    results = validate_all()
    print(format_health_report(results))
