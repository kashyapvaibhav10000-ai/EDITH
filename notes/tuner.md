# tuner.py
## Purpose
Weekly routing tuner — adjusts provider weights based on feedback/latency data.
## Key Functions
- `run_weekly_tune()` — analyze trace feedback, compute new provider weights, save
- `run_tuning_cycle()` — alias with more verbose output
- `get_weights()` — current provider weight dict
- `rollback(steps)` — revert to previous weight snapshot
- `get_tuner_history()` — list of past tuning runs with deltas
- `get_status()` — current weights + last run timestamp
## Imports From
config
## Imported By
smart_router (loads weights via `_get_tuner_weights()`), background_daemon (weekly schedule)
## Status
OK
## Notes
Weights stored in JSON at EDITH_PATH. Rollback available for bad tuning cycles.
