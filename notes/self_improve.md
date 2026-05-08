# self_improve.py
## Purpose
Vision 2 — monitors ArXiv, proposes module upgrades, pushes proposals via event_bus.
## Key Functions
- `run_self_improvement()` — fetch papers → generate proposal → publish to event_bus
- `run_scheduled_improvement()` — wrapper for scheduled trigger
- `fetch_arxiv_abstracts(query, max_results)` — HTTP fetch ArXiv API, parse XML
- `propose_upgrade(papers)` — LLM generates upgrade proposals from abstracts
- `score_proposal(proposal)` — 0.0–1.0 relevance score
- `get_upgrade_history()` / `get_upgrade_stats()` — upgrade log read
- `_save_upgrade_log()` / `_load_upgrade_log()` — JSON persistence
## Imports From
config, smart_router
## Imported By
session (triggered at session end), background_daemon (weekly schedule)
## Status
OK
## Notes
Publishes SELF_IMPROVE_PROPOSAL to event_bus → proactive.py → Telegram. ArXiv query configurable.
