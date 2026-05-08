# chat_server.py
## Purpose
FastAPI web server — primary EDITH interface on port 8000 with streaming, voice endpoints.
## Key Functions
- `chat_stream_endpoint(req)` — SSE streaming chat response
- `chat_endpoint(req)` — standard JSON chat
- `voice_transcribe_endpoint(req)` — STT: audio → text
- `voice_respond_endpoint(req)` — STT + response
- `stop_tts_endpoint()` — interrupt active TTS
- `rate_limit_middleware(req, call_next)` — per-IP rate limiting
- `_get_voice_memory_context(user_input)` — inject relevant memories into prompt
- `_handle_followup(user_input, fu_type)` — handle short follow-up queries
- `_memory_monitor()` — background RAM watchdog
## Imports From
orchestrator, voice, config, shared_state
## Imported By
background_daemon (spawns as subprocess)
## Status
OK
## Notes
CORS enabled for all origins. MCP admin endpoints gated by `_check_mcp_admin()`.
