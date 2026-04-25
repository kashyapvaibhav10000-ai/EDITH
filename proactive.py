"""
EDITH Proactive Alerts — Item 7

Subscribes to event_bus topics and pushes formatted Telegram notifications.
Rate limit: max 10 messages per hour per topic.
Quiet hours: 23:00–07:00 IST (no non-critical alerts).
"""

import datetime
import threading
import time
from collections import defaultdict, deque

from config import get_logger
from errors import Result

log = get_logger("proactive")

# IST = UTC+5:30
_IST_OFFSET = datetime.timedelta(hours=5, minutes=30)
_QUIET_HOUR_START = 23
_QUIET_HOUR_END   = 7
_RATE_LIMIT       = 10       # max pushes per topic per hour
_RATE_WINDOW      = 3600     # seconds


# ───────────────────────────���──────────────────
# Rate Limiter
# ─────────────────────────────────────────���────
class _RateLimiter:
    def __init__(self, limit: int, window: int):
        self._limit = limit
        self._window = window
        self._timestamps: dict = defaultdict(deque)
        self._lock = threading.Lock()

    def is_allowed(self, key: str) -> bool:
        now = time.monotonic()
        with self._lock:
            dq = self._timestamps[key]
            # Drop timestamps outside window
            while dq and now - dq[0] > self._window:
                dq.popleft()
            if len(dq) >= self._limit:
                return False
            dq.append(now)
            return True


_limiter = _RateLimiter(_RATE_LIMIT, _RATE_WINDOW)


# ──────────────────────────────────────────────
# Quiet hours check (IST)
# ──────────────────────────────────────────────
def _is_quiet_hours() -> bool:
    ist_now = datetime.datetime.utcnow() + _IST_OFFSET
    hour = ist_now.hour
    if _QUIET_HOUR_START <= 23:
        return hour >= _QUIET_HOUR_START or hour < _QUIET_HOUR_END
    return False


def _send(message: str, topic_key: str, critical: bool = False) -> Result:
    """Send a Telegram push with rate limiting and quiet hours check."""
    if not critical and _is_quiet_hours():
        log.debug(f"Quiet hours — suppressed alert for {topic_key}")
        return Result.success("suppressed (quiet hours)")

    if not _limiter.is_allowed(topic_key):
        log.warning(f"Rate limit hit for {topic_key} — suppressed")
        return Result.success("suppressed (rate limit)")

    try:
        from telegram_bot import send_telegram
        ok = send_telegram(message, parse_mode="Markdown")
        if ok:
            log.info(f"Proactive push sent: {topic_key}")
            return Result.success("sent")
        return Result.failure("Telegram send returned False", error_type="connection")
    except Exception as e:
        return Result.from_exception(e)


# ──────────────────────────────────────────────
# Event handlers
# ─────────────────────────────────────────────���
def _on_system_alert(payload: dict):
    severity = payload.get("severity", "medium")
    msg = payload.get("message", "")
    icon = {"high": "🔴", "critical": "🚨", "medium": "🟡", "low": "🟢"}.get(severity, "⚠️")
    text = f"{icon} *EDITH Alert* ({severity.upper()})\n{msg}"
    _send(text, "system_alert", critical=(severity in ("high", "critical")))


def _on_health_critical(payload: dict):
    check = payload.get("check", "unknown")
    detail = payload.get("detail", "")
    text = f"🚨 *EDITH Health Critical*\n`{check}` failed:\n_{detail}_"
    _send(text, "health_critical", critical=True)


def _on_calendar_reminder(payload: dict):
    title = payload.get("title", "Event")
    start = payload.get("start_time", "")
    mins = payload.get("minutes_until", 0)
    text = f"📅 *Reminder* — {title}\nStarting in {mins} minutes ({start})"
    _send(text, "calendar_reminder")


def _on_email_arrived(payload: dict):
    sender = payload.get("from", "Unknown")
    subject = payload.get("subject", "")
    preview = payload.get("preview", "")
    text = f"📧 *New Email* from {sender}\n*{subject}*\n_{preview[:200]}_"
    _send(text, "email_arrived")


def _on_agent_done(payload: dict):
    task = payload.get("task", "")
    state = payload.get("state", "")
    summary = payload.get("summary", "")
    icon = "✅" if state == "done" else "❌"
    text = f"{icon} *Agent Task Complete*\nTask: _{task}_\nResult: {summary[:300]}"
    _send(text, "agent_done")


def _on_self_improve(payload: dict):
    proposal = payload.get("proposal", "")
    text = f"🧬 *Self-Improvement Proposal*\n{proposal[:500]}"
    _send(text, "self_improve")


def _on_phone_notification(payload: dict):
    app = payload.get("app", "")
    message = payload.get("message", "")
    text = f"📱 *Phone* ({app}): {message[:200]}"
    _send(text, "phone_notification")


# ──────────────────────────────────────────────
# Wire to event bus
# ──────────────────────────────────────────────
_wired = False
_wire_lock = threading.Lock()


def wire_alerts():
    """Register all proactive handlers on the global event bus. Idempotent."""
    global _wired
    with _wire_lock:
        if _wired:
            return
        try:
            from event_bus import bus, Topic
            bus.subscribe_fn(Topic.SYSTEM_ALERT,          _on_system_alert)
            bus.subscribe_fn(Topic.HEALTH_CRITICAL,       _on_health_critical)
            bus.subscribe_fn(Topic.CALENDAR_REMINDER,     _on_calendar_reminder)
            bus.subscribe_fn(Topic.EMAIL_ARRIVED,         _on_email_arrived)
            bus.subscribe_fn(Topic.AGENT_DONE,            _on_agent_done)
            bus.subscribe_fn(Topic.SELF_IMPROVE_PROPOSAL, _on_self_improve)
            bus.subscribe_fn(Topic.PHONE_NOTIFICATION,    _on_phone_notification)
            _wired = True
            log.info("Proactive alert handlers wired to event bus")
        except Exception as e:
            log.error(f"Failed to wire proactive alerts: {e}")


# Auto-wire on import
wire_alerts()


if __name__ == "__main__":
    from event_bus import bus, Topic, alert, health_critical

    print("Proactive alerts wired:", _wired)
    print(f"Quiet hours now: {_is_quiet_hours()}")

    # Fire a test alert (will attempt Telegram send)
    alert("Test proactive alert — system operational", severity="low")
    import time; time.sleep(0.2)
    print("Done.")
