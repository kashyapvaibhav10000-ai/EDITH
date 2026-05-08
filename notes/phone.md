# phone.py
## Purpose
KDE Connect integration — SMS, ring, notifications, battery, file share, calls.
## Key Functions
- `send_sms(number, message)` — send SMS via kdeconnect-cli
- `ring_phone()` — trigger phone ring
- `get_notifications()` — fetch phone notifications
- `phone_status()` — full phone status dict
- `get_battery()` — battery percentage
- `initiate_call(number)` — start phone call
- `send_ping()` — connectivity check
- `share_file(filepath)` — push file to phone
- `kdeconnect(command)` — raw CLI wrapper
- `_kdeconnect_ip_fallback(endpoint, data)` — HTTP API fallback if CLI fails
## Imports From
config, errors
## Imported By
orchestrator, monitor, intent_dispatch
## Status
OK
## Notes
Phase 4.9/5.3. IP fallback uses KDE Connect HTTP API on port 1716.
