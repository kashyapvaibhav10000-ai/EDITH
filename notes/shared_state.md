# shared_state.py
## Purpose
Shared OrderedDict conversation history to prevent circular imports between chat_server and voice.
## Key Functions
- `add_to_history(role, content)` — append message to capped OrderedDict
- `get_history()` — return current history OrderedDict
- `clear_history()` — reset history
- `get_recent_context(max_items)` — return last N items as list
## Imports From
none
## Imported By
chat_server, voice, orchestrator
## Status
OK
## Notes
M9 module. Simple state container — no persistence. History cap prevents unbounded RAM growth.
