# calendar_reader.py
## Purpose
Google Calendar integration — read events and create new entries via OAuth.
## Key Functions
- `get_service()` — build authenticated Google Calendar API client
- `get_events(days_ahead, max_results)` — fetch upcoming events
- `format_events(events)` — format event list for display
- `get_today_briefing()` — Result with today's agenda
- `get_week_briefing()` — Result with week's agenda
- `create_event(title, date_str, time_str, duration_minutes)` — add calendar event
## Imports From
errors
## Imported By
orchestrator, intent_dispatch
## Status
OK
## Notes
OAuth credentials from config `get_gmail_creds()`. Token auto-refreshes.
