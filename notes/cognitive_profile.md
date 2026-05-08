# cognitive_profile.py
## Purpose
Vision 1 — persistent user model tracking goals, patterns, behavioral drift.
## Key Functions
- `update_profile(observation, session_id)` — add observation to ChromaDB profile
- `query_profile(query, n)` — semantic search of stored observations
- `get_full_profile()` — return all profile observations as string
- `detect_drift()` — compare recent behavior vs stated goals, return summary
- `drift_score()` — 0.0–1.0 float measuring goal/behavior alignment
- `set_prime_directive(directive)` / `get_prime_directive()` — user's core stated goal
- `log_query(user_input, session_id)` / `get_recent_queries(n)` — query log
- `propose_profile_update(session_queries)` — LLM-generated profile observation
## Imports From
config, smart_router, smart_memory
## Imported By
session, life_os, orchestrator, telegram_bot
## Status
OK
## Notes
Drift log persisted to MEMORY_ARCHIVE_PATH. `save_drift_check()` timestamps each check.
