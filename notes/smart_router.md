# smart_router.py
## Purpose
4-tier privacy-aware AI routing: Groq → Gemini → NVIDIA → OpenRouter → Ollama fallback.
## Key Functions
- `smart_call(prompt, intent, force_local, model_hint)` — main routing entry point
- `detect_pii(text)` — detect personal data, force local if found
- `_has_internet()` — connectivity check
- `_score_complexity(query)` — simple/medium/complex classification
- `_get_fastest_provider(candidates)` — pick lowest-latency provider from leaderboard
- `_call_with_latency_track(provider_name, call_fn, ...)` — wrap provider call with timing
- `get_provider_latency_stats()` / `get_provider_leaderboard()` — latency metrics
- `_log_api_cost(provider, model, prompt, response)` — cost tracking to SQLite
- `_apply_tuner_weights(chain)` — reorder routing chain based on tuner feedback
## Imports From
config, vault
## Imported By
cognitive_profile, consolidation, council, data_analyst, graph_memory, life_os, self_improve, video_summarizer, telegram_bot
## Status
OK
## Notes
PRIVATE_INTENTS from config always force Ollama. Groq gets bias for short queries (Item 14). Per-provider latency tracked in SQLite.
