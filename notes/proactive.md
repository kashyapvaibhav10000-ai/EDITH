# proactive.py
## Purpose
Event-driven Telegram alerts — subscribes to event_bus, rate-limited push notifications.
## Key Functions
- `wire_alerts()` — subscribe all handlers to event_bus topics
- `_on_system_alert(payload)` — format + send SYSTEM_ALERT
- `_on_health_critical(payload)` — format + send HEALTH_CRITICAL (bypass rate limit)
- `_on_calendar_reminder(payload)` — send calendar event reminder
- `_on_email_arrived(payload)` — notify new email
- `_on_agent_done(payload)` — agent completion notification
- `_on_self_improve(payload)` — ArXiv upgrade proposal notification
- `_on_phone_notification(payload)` — phone notification relay
- `_RateLimiter` class — max N messages per hour per topic
- `_is_quiet_hours()` — suppress non-critical alerts during sleep hours
## Imports From
config, errors
## Imported By
background_daemon (wire_alerts() at startup)
## Status
OK
## Notes
Item 7. Rate limit: 10 msg/hr/topic. Quiet hours suppress non-critical. HEALTH_CRITICAL always sends.
