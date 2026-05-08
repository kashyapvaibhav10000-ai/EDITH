# model_manager.py
## Purpose
Ollama model lifecycle — switch, pre-warm, per-intent override, list loaded models.
## Key Functions
- `ModelManager` class:
  - `switch_model(model_name)` — change active Ollama model
  - `pre_warm(model_name)` — load model into RAM without generating tokens
  - `list_loaded()` — list currently loaded Ollama models
  - `set_intent_override(intent, model)` — override model for specific intent
  - `get_model_for_intent(intent)` — resolve model with override precedence
## Imports From
config
## Imported By
orchestrator, smart_router
## Status
OK
## Notes
Phase 3.3. Pre-warm eliminates cold-start latency for frequently used models.
