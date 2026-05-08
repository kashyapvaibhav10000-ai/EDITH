# session.py
## Purpose
Session manager — start/end rituals tying all 4 Visions together with device tracking.
## Key Functions
- `start_session(device)` — init session, return session_id, run continuity checks
- `end_session()` — profile update + drift check + open loops + episode + graph ingest
- `track_query(user_input, device)` — log query to session
- `get_session_id()` / `get_session_device()` — current session accessors
- `transfer_session(new_device)` / `resume_session(session_id)` — cross-device continuity
- `get_recent_sessions(limit)` / `session_status()` — session history
- `set_context_snapshot(key, value)` / `get_context_snapshot(key, default)` — per-session KV store
## Imports From
db_pool, config, cognitive_profile, self_improve, life_os, episodic_memory, graph_memory
## Imported By
chat_server, telegram_bot, intent_dispatch, orchestrator
## Status
OK
## Notes
SQLite via db_pool. `end_session()` is the convergence point for all 4 Visions.
