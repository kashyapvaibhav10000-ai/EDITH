# life_os.py
## Purpose
Vision 3 — simulates 5 decision branches for major life choices, tracks open loops.
## Key Functions
- `simulate_decision(decision, context)` — LLM generates 5 parallel outcome simulations
- `weekly_briefing()` — synthesize open loops + profile + recent queries into weekly report
- `add_open_loop(description)` — add unresolved item to ChromaDB open_loops collection
- `close_open_loop(loop_text)` — mark loop resolved
- `get_open_loops()` / `format_open_loops()` — list active unresolved items
## Imports From
config, smart_router, cognitive_profile
## Imported By
session (weekly briefing at session end), intent_dispatch
## Status
OK
## Notes
Open loops stored in ChromaDB. Weekly briefing triggers on Mondays via session.end_session().
