# background_daemon.py
## Purpose
Watchdog daemon managing FastAPI + WakeListener subprocesses with nightly maintenance.
## Key Functions
- `_start_subprocess(name, script)` — launch child process with restart tracking
- `_monitor_subprocesses()` — loop checking liveness, restart if dead
- `_run_nightly_maintenance()` — ChromaDB backup, log rotation, memory consolidation
- `_kde_heartbeat()` — ping KDE Connect to confirm desktop alive
- `_check_heartbeat_silence()` — alert if no heartbeat for threshold
- `_send_telegram_alert(message)` — Telegram push for critical daemon events
- `_prefetch_weather/email_summary/calendar_tomorrow/daily_report()` — background prefetch for faster first responses
- `_sd_notify(state)` — systemd integration
## Imports From
config, event_bus
## Imported By
edith.py (spawns via subprocess)
## Status
OK
## Notes
Subscribes to event_bus for HEALTH_CRITICAL events. Schedule library drives nightly jobs.
