# dashboard.py

## Purpose
Legacy dashboard backend — functionality now lives in chat_server.py

## Key Functions
- `get_system_stats()` — RAM, CPU, disk usage via psutil
- `get_active_model()` — queries Ollama `/api/ps` for loaded model name
- `get_ollama_models()` — lists installed Ollama models via `/api/tags`
- `get_recent_logs()` — last 8 lines from `logs/security_audit.log`
- `get_edith_modules()` — checks existence of 16 key EDITH `.py` files
- `get_mcp_status()` — delegates to `mcp_bridge.get_mcp_status()`
- `api_stats()` — GET `/api/stats` — aggregates all above into one JSON response
- `dashboard()` — GET `/` — 307 redirect to `http://127.0.0.1:8001/dashboard`
- `devpanel_modules()` — GET `/api/devpanel/modules` — lists all `.py` files with line counts
- `devpanel_query()` — POST `/api/devpanel/query` — forwards query + file context to chat_server LLM

## Imports From
- `mcp_bridge` (lazy, inside `get_mcp_status`)
- stdlib: `fastapi`, `psutil`, `subprocess`, `json`, `os`, `datetime`, `glob`, `asyncio`, `urllib.request`

## Imported By
- `chat_server.py` (lazy: `import dashboard as _dash` at line 1029)

## Status
WARN — Legacy. Replacement: chat_server.py dashboard endpoints

## Notes
Do not delete until all importers confirmed migrated to chat_server.py routes
