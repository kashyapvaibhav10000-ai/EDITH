# council.py
## Purpose
Vision 4 — 4-persona debate (Strategist/Critic/Builder/Wildcard) for complex decisions.
## Key Functions
- `run_council(query, context)` — fire all 4 personas in parallel, synthesize debate
- `quick_council(query)` — abbreviated 2-persona version for speed
- `_get_persona_memory(persona_key, query, n)` — recall past positions from ChromaDB
- `_save_persona_position(persona_key, query, position)` — persist each persona's view
## Imports From
config, smart_router
## Imported By
orchestrator, intent_dispatch
## Status
OK
## Notes
Uses concurrent.futures for parallel persona calls. Each persona has separate ChromaDB collection.
