# context.py
## Purpose
Shared DispatchContext dataclass passed to all intent handlers — eliminates circular imports.
## Key Functions
- `DispatchContext` dataclass — fields: intent, user_input, session_id, device, history, etc.
## Imports From
none
## Imported By
intent_dispatch, orchestrator, chat_server
## Status
OK
## Notes
Add new cross-handler fields here, not as function arguments. Core circular-import prevention pattern.
