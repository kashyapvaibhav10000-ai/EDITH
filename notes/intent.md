# intent.py
## Purpose
Intent detection — 30+ regex patterns + optional ML classifier fallback.
## Key Functions
- `detect_intent(text)` — main entry: regex match → ML fallback → return intent string
- `is_coding_request(text)` — fast check for coding intents
- `classify_intent_via_llm(user_input)` — LLM-based intent classification (slow path)
- `_ml_classify(text)` — sklearn/transformers ML model inference
- `_ensure_ml_model()` — lazy-load ML model on first call
- `ml_intent_status()` — return ML model load state + accuracy
- `_count_matches(text, patterns)` — regex match scorer
## Imports From
none (stdlib only — imports config lazily if ML enabled)
## Imported By
orchestrator, chat_server, telegram_bot
## Status
OK
## Notes
CODING_PATTERNS at module top. ML model optional — degrades gracefully to regex if not loaded.
