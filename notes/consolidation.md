# consolidation.py
## Purpose
Memory consolidation "dream state" — merges redundant ChromaDB profile observations during idle time.
## Key Functions
- `run_consolidation()` — retrieve all observations, LLM-merge duplicates, rewrite collection
- `_needs_consolidation()` — check if enough new observations since last run
- `_get_all_observations()` — dump full profile collection
- `_get_profile_collection()` — get ChromaDB profile collection handle
## Imports From
config, smart_router
## Imported By
background_daemon (nightly maintenance)
## Status
OK
## Notes
Triggered after 15+ min idle. Reduces ChromaDB bloat over long sessions.
