# conversation_dna.py
## Purpose
Shapes response style based on time-of-day, device, session length, and detected emotion.
## Key Functions
- `get_response_modifiers(context)` — return dict with tone/depth/max_length/formality
- `_build_style_instruction(tone, depth, max_length, ...)` — compose system prompt injection
- `get_greeting_context()` — time-aware greeting prefix (morning/evening/etc)
## Imports From
config
## Imported By
orchestrator (prompt assembly)
## Status
OK
## Notes
Phase 2.6. No LLM call — pure rule-based signal reading.
