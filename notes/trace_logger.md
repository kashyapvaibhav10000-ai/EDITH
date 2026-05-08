# trace_logger.py
## Purpose
Per-request trace logging — records intent, routing layers, latency, and feedback to SQLite.
## Key Functions
- `new_trace(user_input, intent, device)` — create trace record, return trace_id
- `log_layer(trace_id, layer, input_summary, ...)` — append routing layer event
- `complete_trace(trace_id, status, ...)` — finalize trace with outcome
- `set_feedback(trace_id, feedback)` — attach 👍👎 to trace
- `get_trace(trace_id)` — retrieve full trace dict
- `get_recent_traces(limit)` — last N traces
- `get_feedback_stats()` — aggregate feedback counts
## Imports From
db_pool, config
## Imported By
feedback_tagger, orchestrator, smart_router
## Status
OK
## Notes
SQLite via db_pool. Trace_id is UUID. Used by tuner to analyze routing decisions.
