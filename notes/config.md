# config.py
## Purpose
Single source of truth for all paths, model names, constants, and shared utilities.
## Key Functions
- `get_chroma_client(path)` — create/return ChromaDB persistent client
- `get_logger(name)` — configure and return named logger
- `safe_ollama_call(model, prompt, timeout)` — Ollama chat with timeout + error handling
- `safe_ollama_generate(model, prompt, timeout)` — Ollama generate variant
- `get_gmail_creds()` — load/refresh OAuth2 Google credentials
- `detect_optimal_models()` — check Ollama for available models, pick best fit
- `_get_vault_secret(key, default)` — load secret from vault (vault-first pattern)
- `_ensure_x11_auth()` — inject XAUTHORITY for display access
- `OllamaError` — custom exception for Ollama failures
## Imports From
errors
## Imported By
virtually all modules
## Status
OK
## Notes
PRIVATE_INTENTS list used by smart_router to force local routing. All API keys load via vault-first then .env fallback.
