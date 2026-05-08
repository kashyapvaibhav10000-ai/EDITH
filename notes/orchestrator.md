# orchestrator.py
## Purpose
Core request handler — glues intent dispatch, memory, history, and all specialized modules.
## Key Functions
- `chat(user_input, session_id, device)` — main sync chat entry point
- `chat_stream(user_input, session_id, device)` — streaming generator variant
- `handle_intent(intent, user_input, reply)` — post-response side effects (memory, profile)
- `remember(key, value)` / `recall(query, n)` — hot memory read/write
- `compact_history(history, max_turns)` — trim history to max_turns keeping system msg
- `_danger_scan(user_input)` — detect dangerous commands before execution
- `_classify_scope(user_input)` — local vs cloud scope classifier
- `HistoryManager` class — conversation history with JSONL session append
## Imports From
voice, tools, sandbox, search, email_reader, calendar_reader, data_analyst, agent, rag, vision, intent_dispatch
## Imported By
chat_server, telegram_bot
## Status
OK
## Notes
Circular import avoided by importing intent_dispatch at call time (not module top). History capped at max_turns via compact_history.
