# weather.py
## Purpose
Current weather via Open-Meteo API with automatic location detection.
## Key Functions
- `get_current_weather()` — detect location + fetch weather, return Result
- `format_weather(weather)` — format weather dict as readable string
- `get_greeting()` — time + weather aware greeting string
- `_detect_location()` — IP geolocation via ip-api.com
## Imports From
config, errors
## Imported By
orchestrator, monitor, background_daemon (prefetch)
## Status
OK
## Notes
Open-Meteo is free, no API key. Location detection fails gracefully to config default.
