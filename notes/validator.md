# validator.py
## Purpose
System health validator — checks network, Ollama, phone, calendar, disk, memory, vision, TTS.
## Key Functions
- `validate_all(emit_events)` — run all validators, return results dict
- `validate_network()` — DNS + HTTP connectivity check
- `validate_ollama()` — Ollama API ping + model list
- `validate_phone()` — KDE Connect device reachability
- `validate_calendar()` — Google Calendar OAuth validity
- `validate_disk()` — free disk space check
- `validate_memory()` — RAM availability check
- `validate_vision_model()` — llava-phi3 model availability
- `validate_chatterbox()` — Chatterbox TTS venv check
- `format_health_report(results)` — format results dict as readable report
## Imports From
config, errors
## Imported By
edith.py (doctor option), background_daemon (startup check)
## Status
OK
## Notes
`emit_events=True` publishes HEALTH_CRITICAL events to event_bus for failing checks.
