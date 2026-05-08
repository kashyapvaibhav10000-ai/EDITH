# intent_dispatch.py
## Purpose
Central dispatch table — maps intents to handlers, no circular imports, no elif chains.
## Key Functions
- `get/set/clear_pending_action()` — manage multi-turn confirmation state
- `_handle_weather/calendar_today/calendar_week/calendar_create(ctx)` — specific intent handlers
- `_extract_date/time/event_title/filepath/phone_number/sms_body(text)` — intent param extractors
- `_is_safe_command(cmd)` — command safety whitelist check
- `_friendly_error(intent, error)` — user-facing error message builder
- (dispatch table) — `HANDLERS` dict mapping intent string → handler function
## Imports From
config, context, errors, session, cognitive_profile, event_bus (+ many handler-specific imports)
## Imported By
orchestrator, chat_server
## Status
OK
## Notes
Phase 4 refactor. All new intent handlers go here, not in orchestrator. Prevents circular import with chat_server.
