# event_bus.py
## Purpose
In-process pub/sub event bus — backbone for decoupled module communication.
## Key Functions
- `EventBus` class — subscribe(topic, callback), publish(event)
- `Topic` enum — SYSTEM_ALERT, CALENDAR_REMINDER, EMAIL_ARRIVED, AGENT_DONE, HEALTH_CRITICAL, PHONE_NOTIFICATION, SELF_IMPROVE_PROPOSAL
- `alert(message, severity, source)` — publish SYSTEM_ALERT
- `health_critical(check, detail, source)` — publish HEALTH_CRITICAL
- `agent_done(task_id, task, state, summary)` — publish AGENT_DONE
- `calendar_reminder(event_title, start_time, minutes_until)` — publish CALENDAR_REMINDER
- `intent_detected(intent, user_input, emotion, urgency)` — publish INTENT_DETECTED
- `memory_updated(key, category)` — publish MEMORY_UPDATED
- `session_ended(session_id, summary)` — publish SESSION_ENDED
## Imports From
config, errors
## Imported By
agent, background_daemon, orchestrator, intent_dispatch, telegram_bot, proactive, self_improve
## Status
OK
## Notes
`bus` singleton exported at module level. All subscribers run synchronously in publish thread.
