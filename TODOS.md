## Refactor plan: chat_server.py → modular routers (FastAPI APIRouter)

### Step 1 — Create router modules (new files)
- `routes/system.py`: endpoints
  - `/api/health-check`
  - `/api/system-status`
  - `/api/recent_traces`
  - `/api/monitor_schedule`
  - `/dashboard`
  - `/api/costs`
  - `/api/provider-latencies`
  - `/api/stats`
  - `/api/status`
  - `/api/last-memory`
  - `/api/phone`
  - `/api/weather-status`
  - `/api/traces/recent`
  - `/api/logs/stream`
- `routes/mcp.py`: endpoints
  - `/api/mcp/status`
  - `/api/mcp/tools/{server_name}`
  - `/api/mcp/call`
  - `/api/mcp/config`
  - `/api/mcp/config/add`
  - `/api/mcp/config/toggle/{server_name}`
  - `/api/mcp/config/remove/{server_name}`
- `routes/webhooks.py`: endpoints
  - `/webhook/{source}`
  - `/tg_webhook`
- `routes/devpanel.py`: endpoints
  - `/api/devpanel/modules`
  - `/api/devpanel/query`
- `routes/sessions.py`: endpoints
  - `/api/sessions`
  - `/api/sessions/new`
  - `/api/sessions/{session_id}/messages`
- `routes/repo.py`: endpoints
  - `/api/feedback`
  - all `/api/repo/*` including adapt-preview/confirm/status, gap-plan, subtask-status, rate-adaptation, success-rate, alert-config, trend, multi-compare, self-audit, watch-check
  - includes required repo_dna imports and shared `_REPO_DNA_OK` checks
- Keep module-level shared state for repo_dna adaptation tracking:
  - `_adapt_results`, `_adapt_meta`
  - event_bus subscription to mark_adapted on AGENT_DONE

### Step 2 — Include routers from chat_server.py
- Replace extracted endpoint definitions with:
  - `app.include_router(system_router, prefix="")` etc. (no prefix, endpoints keep absolute paths)
- Keep in `chat_server.py`:
  - FastAPI init
  - shutdown event handler
  - middleware registration
  - `_ALLOWED_ORIGINS` and CORS
  - static mount
  - index `/` handler
  - memory monitor thread function + background startup behavior (inside __main__)
  - MCP token verification helper and bus subscriptions (if not moved)

### Step 3 — Widget history cap refactor
- Update `_MAX_WIDGET_HISTORY` from `10` → `50` in:
  - `routes/chat.py`
  - `voice_routes.py`
- Ensure trimming happens after every append (already does in both places; keep behavior consistent)

### Step 4 — Smoke tests
- Run existing smoke tests script(s) after refactor:
  - `./smoke_test_standalone.sh` (and/or any `SMOKE_TESTS.md` instructions)
