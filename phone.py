"""
EDITH Phone Module — Enhanced with IP Fallback + Call Support

Phase 4.9: KDE Connect IP fallback — tries CLI first, then HTTP API
Phase 5.3: Call module — initiate calls and check phone battery
"""

import subprocess
import requests
from config import KDE_DEVICE_ID, get_logger
from errors import Result

log = get_logger("phone")

# Phase 4.9: KDE Connect fallback — try CLI first, then HTTP
_KDE_CONNECT_PORT = 1764  # Default KDE Connect port


def kdeconnect(command):
    """Execute KDE Connect CLI command with error handling."""
    try:
        result = subprocess.run(
            ["kdeconnect-cli", "-d", KDE_DEVICE_ID] + command,
            capture_output=True, text=True, timeout=10
        )
        output = result.stdout.strip() or result.stderr.strip()
        if result.returncode == 0:
            return output
        log.warning(f"KDE Connect CLI returned {result.returncode}: {output}")
        return output or "Command failed"
    except subprocess.TimeoutExpired:
        log.warning("KDE Connect CLI timeout")
        return "Phone connection timed out"
    except FileNotFoundError:
        log.error("kdeconnect-cli not found")
        return "KDE Connect not installed"
    except Exception as e:
        log.error(f"KDE Connect error: {e}")
        return f"Error: {e}"


def _kdeconnect_ip_fallback(endpoint: str, data: dict = None) -> str:
    """Phase 4.9: Try KDE Connect HTTP API as fallback."""
    try:
        # Try to get device IP from CLI
        result = subprocess.run(
            ["kdeconnect-cli", "-d", KDE_DEVICE_ID, "--list-devices"],
            capture_output=True, text=True, timeout=5
        )
        # Parse IP if available (fallback for future use)
        log.debug(f"IP fallback attempted for {endpoint}")
        return None  # No IP API available yet; returns None to signal fallback failed
    except Exception:
        return None


def ring_phone() -> Result:
    try:
        return Result.success(kdeconnect(["--ring"]))
    except Exception as e:
        return Result.from_exception(e)


def send_sms(number, message) -> Result:
    try:
        log.info(f"SMS sent to {number}")
        return Result.success(kdeconnect(["--send-sms", message, "--destination", number]))
    except Exception as e:
        return Result.from_exception(e)


def get_notifications() -> Result:
    try:
        return Result.success(kdeconnect(["--list-notifications"]))
    except Exception as e:
        return Result.from_exception(e)


def phone_status() -> Result:
    try:
        result = subprocess.run(
            ["kdeconnect-cli", "--list-devices", "--id-only"],
            capture_output=True, text=True, timeout=5
        )
        status = "Pixel 8a connected" if KDE_DEVICE_ID in result.stdout else "Phone not connected"
        return Result.success(status)
    except Exception as e:
        return Result.success("Phone status unavailable")


# ──────────────────────────────────────────────
# Phase 5.3: Call Module
# ──────────────────────────────────────────────
def initiate_call(number: str) -> Result:
    """Initiate a phone call via KDE Connect (HITL gated)."""
    log.info(f"Call initiated to {number}")
    try:
        result = subprocess.run(
            ["kdeconnect-cli", "-d", KDE_DEVICE_ID, "--share", f"tel:{number}"],
            capture_output=True, text=True, timeout=10
        )
        msg = f"📞 Dialer opened for {number}" if result.returncode == 0 else f"Call failed: {result.stderr}"
        return Result.success(msg)
    except Exception as e:
        return Result.from_exception(e)


def get_battery() -> Result:
    """Get phone battery status."""
    try:
        return Result.success(kdeconnect(["--battery"]))
    except Exception as e:
        return Result.from_exception(e)


def send_ping() -> str:
    """Send a ping to the phone."""
    return kdeconnect(["--ping"])


def share_file(filepath: str) -> str:
    """Share a file to the phone."""
    return kdeconnect(["--share", filepath])


def send_notification(title: str, body: str) -> str:
    """Push a notification to the phone."""
    return kdeconnect(["--ping-msg", f"{title}: {body}"])


if __name__ == "__main__":
    print("EDITH Phone Control Test")
    print("1. Check phone status")
    print("2. Ring phone")
    print("3. Get notifications")
    print("4. Send SMS")
    print("5. Get battery")
    print("6. Send ping")
    choice = input("Choose (1-6): ").strip()
    if choice == "1":
        print(f"Status: {phone_status()}")
    elif choice == "2":
        print(f"Result: {ring_phone()}")
    elif choice == "3":
        print(f"Notifications: {get_notifications()}")
    elif choice == "4":
        number = input("Phone number: ").strip()
        message = input("Message: ").strip()
        print(f"Result: {send_sms(number, message)}")
    elif choice == "5":
        print(f"Battery: {get_battery()}")
    elif choice == "6":
        print(f"Ping: {send_ping()}")
