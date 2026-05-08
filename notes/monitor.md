# monitor.py
## Purpose
Proactive system monitoring — disk, RAM, CPU, phone battery, weather, break reminders.
## Key Functions
- `check_disk(threshold)` — alert if disk usage > threshold%
- `check_ram()` / `check_cpu()` — return usage dicts
- `check_phone_battery()` — KDE Connect battery query
- `check_weather()` — current weather summary
- `check_breaks(last_break)` — alert if no break in N minutes
- `get_system_status()` — aggregate all checks into status dict
- `get_full_proactive_alerts(last_break_time)` — run all checks, return alert list
- `is_resource_constrained()` / `get_resource_mode()` — low-resource mode detection
- `backup_chromadb()` — trigger ChromaDB backup
## Imports From
config
## Imported By
background_daemon (periodic monitoring loop)
## Status
OK
## Notes
Uses psutil. Resource-constrained mode disables heavy ML features.
