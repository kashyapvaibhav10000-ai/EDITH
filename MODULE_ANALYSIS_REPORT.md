# MODULE ANALYSIS REPORT
Date: 2026-05-24

This document contains a detailed analysis of the five largest EDITH modules and proposes specific split plans based on actual code structure.

---

## 1. CHAT_SERVER.PY (2786 lines)

### Route Groups Found (21 major groups):

**Group A: Core Chat** (64 lines)
- `POST /api/chat/stream` — streaming chat endpoint
- `POST /api/chat` — non-streaming chat

Helper functions:
- `_get_voice_memory_context()` — fetch ChromaDB context for voice
- `_get_last_exchange()` — session state
- `_is_followup()` — follow-up detection

**Group B: Voice I/O** (400 lines)
- `POST /api/voice/transcribe` — speech-to-text
- `POST /api/voice/respond` — voice query + TTS response
- `POST /api/voice/mic-lock` — lock microphone
- `POST /api/voice/mic-unlock` — unlock microphone
- `POST /api/voice/warmup-chatterbox` — GPU warmup
- `POST /api/voice/stop-tts` — stop playback
- `POST /api/voice/barge-in-complete` — barge-in signal
- `GET /api/voice/barge-in-status` — barge-in state
- `GET /api/voice-status` — voice pipeline state

Helper functions:
- `_track_widget_msg()` — session tracking
- `_persist_exchange()` — conversation history

**Group C: Dashboard & Status** (250 lines)
- `GET /` — home page HTML (auth check)
- `GET /dashboard` — dashboard HTML
- `GET /api/health-check` — health status
- `GET /api/system-status` — system info
- `GET /api/status` — combined status
- `GET /api/stats` — aggregated metrics
- `GET /api/costs` — LLM cost summary
- `GET /api/provider-latencies` — provider response times
- `GET /api/monitor_schedule` — monitor job schedule

Helper functions:
- `_memory_monitor()` — background memory watcher

**Group D: MCP (Model Context Protocol)** (250 lines)
- `GET /api/mcp/config` — MCP server config
- `GET /api/mcp/status` — MCP server status
- `GET /api/mcp/tools/{server_name}` — list tools
- `POST /api/mcp/config/add` — register MCP server
- `POST /api/mcp/call` — invoke MCP tool
- `POST /api/mcp/config/toggle/{server_name}` — enable/disable server
- `DELETE /api/mcp/config/remove/{server_name}` — unregister server

**Group E: Repository Analysis** (300 lines)
- `POST /api/repo/analyze` — analyze code changes
- `POST /api/repo/adapt-preview` — preview adaptations
- `POST /api/repo/adapt-confirm` — confirm adaptations
- `GET /api/repo/adapt-status/{task_id}` — adaptation progress
- `POST /api/repo/*` (11 total routes)
- Multiple repo workflow endpoints

**Group F: Traces & Logs** (120 lines)
- `GET /api/recent_traces` — recent traces
- `GET /api/traces/recent` — trace history
- `GET /api/logs/stream` — streaming logs

**Group G: Session Management** (80 lines)
- `GET /api/sessions` — list sessions
- `GET /api/sessions/{session_id}/messages` — session history
- `POST /api/sessions/new` — create session

**Group H: Miscellaneous Endpoints** (80 lines)
- `POST /api/feedback` — collect feedback
- `GET /api/phone` — phone status
- `GET /api/weather-status` — weather info
- `GET /api/last-memory` — recent memory
- `GET /api/devpanel/modules` — dev modules
- `POST /api/devpanel/query` — dev queries

**Group I: Webhooks** (40 lines)
- `POST /tg_webhook` — Telegram webhook
- `POST /webhook/{source}` — generic webhook

**Group J: Middleware** (100 lines)
- `api_key_middleware()` — auth via X-API-Key/Bearer
- `rate_limit_middleware()` — rate limiting

### Line Distribution:

| Group | Routes | Lines | Content |
|-------|--------|-------|---------|
| A: Core Chat | 2 | 64 | Main LLM chat |
| B: Voice | 9 | 400 | Voice pipeline |
| C: Dashboard | 9 | 250 | Status/metrics |
| D: MCP | 7 | 250 | Tool calling |
| E: Repos | 15 | 300 | Code analysis |
| F: Traces | 3 | 120 | Observability |
| G: Sessions | 3 | 80 | Session tracking |
| H: Misc | 6 | 80 | Sidebar APIs |
| I: Webhooks | 2 | 40 | Event hooks |
| J: Middleware | 2 | 100 | Auth + rate limit |

### Proposed Extraction:

**3-file split** (minimizes import complexity):

1. **voice_routes.py** (400 lines)
   - `POST /api/voice/transcribe`
   - `POST /api/voice/respond`
   - `POST /api/voice/mic-lock`
   - `POST /api/voice/mic-unlock`
   - `POST /api/voice/warmup-chatterbox`
   - `POST /api/voice/stop-tts`
   - `POST /api/voice/barge-in-complete`
   - `GET /api/voice/barge-in-status`
   - `GET /api/voice-status`
   - Helper: `_get_voice_memory_context()`

2. **dashboard_routes.py** (250 lines)
   - `GET /` (home HTML)
   - `GET /dashboard` (dashboard HTML)
   - `GET /api/health-check`
   - `GET /api/system-status`
   - `GET /api/status`
   - `GET /api/stats`
   - `GET /api/costs`
   - `GET /api/provider-latencies`
   - `GET /api/monitor_schedule`
   - Helper: `_memory_monitor()`

3. **mcp_routes.py** (250 lines)
   - All 7 `/api/mcp/*` routes
   - MCP management logic
   - Tool invocation wrappers

4. **repo_routes.py** (300 lines)
   - All 15 `/api/repo/*` routes
   - Repository analysis logic

**Remaining in chat_server.py:**
- Core chat: `/api/chat` and `/api/chat/stream` (primary responsibility)
- Sessions: `/api/sessions/*`
- Traces: `/api/traces/*`, `/api/logs/stream`
- Middleware: auth + rate limits
- Webhooks: `/tg_webhook`, `/webhook/*`
- Misc: `/api/feedback`, `/api/phone`, `/api/weather-status`, `/api/last-memory`, `/api/devpanel/*`

---

## 2. INTENT_DISPATCH.PY (1750 lines)

### Handler Categories Found (45 handlers + dispatch table):

**Category A: Communication** (80 lines)
- `_handle_email()`, `_handle_unread_email()` — Gmail integration
- `_handle_sms()`, `_handle_phone()`, `_handle_call()` — Phone/SMS
- `_handle_whatsapp()` — WhatsApp messaging

**Category B: File Operations** (150 lines)
- `_handle_file_query()` — list/search files
- `_handle_create_file()` — create file
- `_handle_delete_file()` — delete file
- `_handle_mcp()` — MCP filesystem integration

**Category C: System Operations** (300 lines)
- `_run_local_exec()` — central dispatcher for all local system ops
  - Process monitoring (ps, top, resource tracking)
  - System info (OS, kernel, CPU, RAM, disk)
  - Network diagnostics (ping, DNS, interfaces)
  - Privilege checks (whoami, sudo, permissions)
  - Duplicate file detection (fdupes, md5sum)
  - File finding/searching (find, locate)
  - Random file selection
  - Generic command execution

**Category D: Search & Web** (40 lines)
- `_handle_search()` — web search integration

**Category E: Productivity** (100 lines)
- `_handle_weather()` — weather API
- `_handle_calendar_today()`, `_handle_calendar_week()`, `_handle_calendar_create()` — Google Calendar
- `_handle_morning_briefing()`, `_handle_briefing()` — daily briefing

**Category F: Intelligence & Decision Making** (200 lines)
- `_handle_agent()` — autonomous agent runner
- `_handle_council()` — multi-agent debate
- `_handle_decision()` — life_os decision simulation
- `_handle_self_improve()` — self-improvement runner
- `_handle_profile()` — cognitive profile management
- `_handle_image_gen()`, `_handle_video_summarize()` — media tasks

**Category G: Knowledge & Analysis** (120 lines)
- `_handle_rag()` — retrieval-augmented generation
- `_handle_data_analysis()` — CSV/file analysis
- `_handle_system_health()` — repo health check
- `_handle_repo_analyze()` — repo analysis

**Category H: Application Control** (80 lines)
- `_handle_vision()` — screenshot analysis
- `_handle_open_app()` — launch applications
- `_handle_shell()` — direct shell commands

**Category I: Session & State** (60 lines)
- `_handle_session_end()` — session termination
- `_handle_wake()` — wake signal
- `_handle_compact()` — compress conversation

**Category J: Configuration** (60 lines)
- `_handle_think_level()` — toggle deep reasoning
- `_handle_trace_toggle()` — trace logging on/off
- `_handle_agent_stop()` — stop agent loop
- `_handle_list_skills()` — list loaded skills

**Category K: Fallback** (80 lines)
- `_handle_chat_fallback()` — default LLM response

### Key Entry Points:

1. **dispatch(ctx)** — main entry point (calls DAG executor for compound queries)
2. **_dispatch_single(ctx)** — route one intent via INTENT_HANDLERS table
3. **execute_pending_action(action)** — HITL confirmation execution
4. **_run_local_exec(user_input)** — local system ops dispatcher (returns None if not a local op)

### Proposed Extraction:

**4-file split** (clear functional boundaries):

1. **communication_handlers.py** (80 lines)
   - `_handle_email()`, `_handle_unread_email()`
   - `_handle_sms()`, `_handle_phone()`, `_handle_call()`
   - `_handle_whatsapp()`
   - `_handle_phone()` — phone integration

2. **file_handlers.py** (150 lines)
   - `_handle_file_query()`
   - `_handle_create_file()`
   - `_handle_delete_file()`
   - `_handle_mcp()` — filesystem MCP wrapper

3. **system_handlers.py** (300 lines)
   - **ENTIRE `_run_local_exec()` function** (refactored internally):
     - Processes/resources, sysinfo, network, privileges
     - File operations (duplicates, finding)
   - Helper patterns and detector functions

4. **intelligence_handlers.py** (280 lines)
   - `_handle_agent()`, `_handle_council()`
   - `_handle_decision()`, `_handle_self_improve()`
   - `_handle_profile()`
   - `_handle_rag()`, `_handle_data_analysis()`
   - `_handle_system_health()`, `_handle_repo_analyze()`
   - `_handle_image_gen()`, `_handle_video_summarize()`

**Remaining in intent_dispatch.py:**
- `dispatch()` — main DAG dispatcher
- `_dispatch_single()` — handler router
- `execute_pending_action()` — HITL executor
- `INTENT_HANDLERS` — dispatch table mapping
- Miscellaneous handlers: weather, calendar, search, vision, open_app, shell, session, wake, compact, config toggles, fallback

---

## 3. DASHBOARD.PY (1537 lines)

### Content Breakdown:

**Backend Logic** (~100 lines)
- `get_system_stats()` — memory, CPU, processes
- `get_active_model()` — current model in use
- `get_ollama_models()` — available Ollama models
- `get_recent_logs()` — last N log lines
- `get_edith_modules()` — loaded Python modules
- `get_mcp_status()` — MCP servers state

**API Routes** (~60 lines)
- `@app.get("/api/stats")` — expose system stats
- `@app.get("/api/devpanel/modules")` — dev panel data
- `@app.post("/api/devpanel/query")` — dev queries

**HTML/CSS/JavaScript** (~1377 lines)
- `@app.get("/", response_class=HTMLResponse)` — dashboard HTML
- Embedded CSS (lines 127–683, ~560 lines) — styling
- Embedded JavaScript (lines 913–1457, ~560 lines) — React/vanilla JS

### HTML Structure (lines 121–1457):
```
<html>
  <head>
    <style>...</style>  (560 lines of CSS)
  <body>
    <div id="root">...</div>
    <script>...</script>  (560 lines of JS)
</html>
```

### Proposed Extraction:

**3-file split** (clear HTML vs backend separation):

1. **dashboard_backend.py** (~100 lines)
   - `get_system_stats()`, `get_active_model()`, etc.
   - All helper functions
   - Pure business logic (no HTML)

2. **dashboard_routes.py** (~60 lines)
   - `@app.get("/api/stats")` — call backend + return JSON
   - `@app.get("/api/devpanel/modules")`
   - `@app.post("/api/devpanel/query")`
   - Wrappers around backend functions

3. **dashboard_ui.html** (~1377 lines, NEW file)
   - Move entire HTML template to standalone file
   - Reference from route: `return open("dashboard_ui.html").read()`
   - Enables joint work (frontend dev + backend dev)
   - Easier to update CSS/JS independently

**Remaining in dashboard.py:**
- `@app.get("/")` — home page
- Import + serve dashboard_ui.html
- Minimal glue code

---

## 4. ORCHESTRATOR.PY (1186 lines)

### Logical Sections Found:

**Section A: Voice I/O** (~30 lines)
- `speak(text)` — TTS via local bridge
- `speak_stream(sentences)` — streaming TTS
- `listen()` — STT (not implemented on cloud)

**Section B: Event Emission & Telemetry** (~60 lines)
- `set_last_intent(intent)` — track active intent
- `_emit_intent()` — telemetry event
- `_emit_memory_updated(key)` — memory change event
- `_emit_session_ended(session_id)` — session complete event

**Section C: History & Session Management** (~150 lines)
- `class HistoryManager` — manage conversation history
- `_load_history()` — load from disk/DB
- `compact_history()` — summarize old turns
- `_append_session_jsonl()` — write to session log
- `recall(query)` — retrieve relevant history
- Memory cleanup/scheduling

**Section D: Context & Parsing** (~60 lines)
- `remember(key, value)` — store in smart memory
- `parse_time(t)` — calendar time parsing
- `handle_intent(intent, user_input, reply)` — intent tracking

**Section E: Safety & Danger Scanning** (~100 lines)
- `_danger_scan(user_input)` — detect dangerous commands
- `_classify_scope(user_input)` — input category detection
- `_maybe_create_skill(task_id, summary)` — auto-skill generation

**Section F: Post-Turn Operations** (~80 lines)
- `_post_turn_reflection(user_input, response)` — after-chat analysis
- `_verify_response(query, response)` — response validation
- DAG chaining + cognitive profile updates

**Section G: Main Chat Logic** (~600 lines)
- `chat(user_input, intent, device, source)` — synchronous chat (entire orchestration flow)
- `chat_stream(user_input, intent, context, system_prompt_override)` — streaming chat
- `handle_vision_intent(intent, user_input)` — screenshot processing

**Section H: Monitoring & Entry** (~50 lines)
- `_idle_monitor_loop()` — background monitoring
- `main()` — CLI entry point

### Import Dependencies (40+ modules):
- tools, sandbox, search, email_reader, calendar_reader, data_analyst, agent, rag, vision, phone
- smart_memory, conversation_dna, session, council, life_os, cognitive_profile, self_improve
- smart_router, weather, episodic_memory, graph_memory, consolidation, devlog
- And more...

### Proposed Extraction:

**4-file split** (balance between independence and reusability):

1. **orchestrator_session.py** (~150 lines)
   - `class HistoryManager`
   - `_load_history()`, `compact_history()`, `_append_session_jsonl()`
   - `remember()`, `recall()`
   - Memory lifecycle + cleanup
   - **Purpose:** Encapsulate all session/history logic

2. **orchestrator_safety.py** (~100 lines)
   - `_danger_scan()`
   - `_classify_scope()`
   - `_maybe_create_skill()`
   - **Purpose:** Safety checks & skill auto-gen

3. **orchestrator_streaming.py** (~250 lines)
   - `chat_stream()` — all streaming logic
   - `_split_sentences()` — stream utilities
   - Stream-specific token yielding
   - **Purpose:** Separate streaming from sync chat

4. **orchestrator_core.py** (~500 lines)
   - `chat()` — main synchronous logic
   - `handle_vision_intent()`
   - `_post_turn_reflection()`, `_verify_response()`
   - `parse_time()`, `handle_intent()`
   - **Purpose:** Core chat coordination; imports other modules

**Utilities remain in orchestrator.py:**
- Voice I/O: `speak()`, `speak_stream()`, `listen()`
- Events: `set_last_intent()`, `_emit_*()` functions
- Entry: `_idle_monitor_loop()`, `main()`

---

## 5. SMART_ROUTER.PY (1044 lines)

### Layers Found:

**Layer 1: Configuration & Keys** (~50 lines)
- `_require_key(key_value, key_name)` — validate API keys
- `_routing_chains()` — get provider order (per intent)
- `_PII_PATTERNS` — regex for PII detection
- `detect_pii(text)` — find sensitive data

**Layer 2: State Management** (~80 lines)
- `_provider_failures` — circuit breaker state
- `_daily_calls` — usage counter
- `_response_cache` — semantic cache (OrderedDict)
- `_response_times` — latency history (deques)
- `_provider_latencies` — stats
- Threading lock for thread safety

**Layer 3: Health & Monitoring** (~100 lines)
- `_call_with_latency_track()` — measure response time
- `_get_fastest_provider()` — pick by latency
- `get_provider_latency_stats()` — return stats
- `get_provider_leaderboard()` — ranked providers
- `_log_latency_leaderboard()` — telemetry
- `_has_internet()` — network check

**Layer 4: Usage Tracking & Cost** (~80 lines)
- `_init_usage_db()` — initialize SQLite
- `_log_api_cost()` — track spend
- `_reset_daily_if_needed()` — reset counters daily
- `_is_under_daily_limit()` — check quota
- `_track_call()` — increment counter

**Layer 5: Provider State Machine** (~50 lines)
- `_is_provider_cooled_down()` — check retry backoff
- `_mark_provider_failed()` — mark failed + set backoff
- `get_last_call_stats()` — last call metadata
- `_get_tuner_weights()` — tuner adjustments
- `_apply_tuner_weights()` — apply adjustments to chain

**Layer 6: Caching** (~40 lines)
- `_context_fingerprint()` — hash prompt+intent
- `_cache_get()` — retrieve cached response
- `_cache_set()` — store cached response

**Layer 7: Score & Complexity** (~20 lines)
- `_score_complexity()` — query complexity classification
- `_has_key()` — check API key availability

**Layer 8: Provider Implementations** (~300 lines)
- `_call_groq(prompt, system)` — Groq engine call
- `_call_gemini(prompt, system)` — Google Gemini
- `_call_nvidia(prompt, system)` — NVIDIA API
- `_call_openrouter(prompt, system)` — OpenRouter
- `_call_ollama(prompt, system)` — Local Ollama
- Map: `_PROVIDER_CALLS` dictionary

**Layer 9: Streaming Provider Implementations** (~150 lines)
- `_call_groq_stream()`, `_call_gemini_stream()`, etc.
- Yield-based streaming
- Map: `_PROVIDER_STREAM_CALLS` dictionary

**Layer 10: Main Routing Logic** (~350 lines)
- `smart_call()` — main router (sync)
- `smart_call_stream()` — streaming router
- Complex per-intent routing logic
- Fallback chains, circuit breaking, cost tracking

**Layer 11: Convenience Functions** (~20 lines)
- `smart_chat()` — chat wrapper
- `smart_reason()` — reasoning wrapper
- `smart_code()` — code wrapper
- `router_status()` — diagnostic endpoint

### Dependency Graph:
```
smart_call() / smart_call_stream()
  ├─ _cache_get() / _cache_set()
  ├─ _has_internet()
  ├─ _get_fastest_provider()
  ├─ _is_provider_cooled_down()
  ├─ _is_under_daily_limit()
  ├─ For each provider in chain:
  │   ├─ _call_<provider>() / _call_<provider>_stream()
  │   ├─ _call_with_latency_track()
  │   ├─ _track_call()
  │   ├─ _log_api_cost()
  │   └─ _mark_provider_failed() [on error]
```

### Proposed Extraction:

**5-file split** (cleanest dependency layers):

1. **provider_implementations.py** (~300 lines)
   - `_call_groq()`, `_call_gemini()`, `_call_nvidia()`, `_call_openrouter()`, `_call_ollama()`
   - `_call_groq_stream()`, etc. (streaming variants)
   - `_PROVIDER_CALLS`, `_PROVIDER_STREAM_CALLS` maps
   - **Purpose:** Pure provider API wrappers (testable, reusable)

2. **provider_config.py** (~70 lines)
   - `_require_key()`, `_routing_chains()`, `_score_complexity()`
   - `detect_pii()`, `_PII_PATTERNS`
   - `_has_key()` — provider availability check
   - **Purpose:** Configuration + detection (no state)

3. **router_cache.py** (~40 lines)
   - `_context_fingerprint()`, `_cache_get()`, `_cache_set()`
   - `_response_cache` state
   - **Purpose:** Semantic caching layer (orthogonal to routing)

4. **router_health.py** (~150 lines)
   - Latency tracking: `_call_with_latency_track()`, stats/leaderboard
   - Provider state: `_is_provider_cooled_down()`, `_mark_provider_failed()`
   - Usage: `_init_usage_db()`, `_log_api_cost()`, `_reset_daily_if_needed()`, `_is_under_daily_limit()`
   - **Purpose:** Health + observability (circuit breaker, cost, latency)

5. **router_core.py** (~350 lines)
   - `smart_call()` — main router logic
   - `smart_call_stream()` — streaming router
   - Tuner weights: `_get_tuner_weights()`, `_apply_tuner_weights()`
   - Convenience: `smart_chat()`, `smart_reason()`, `smart_code()`
   - `router_status()`, `get_last_call_stats()`
   - **Purpose:** Main routing orchestration (imports from layers 1–4)

**Remaining in smart_router.py:**
- Import + re-export all public functions (backward compatibility)
- Or: Become a simple wrapper that imports from submodules

---

# SUMMARY TABLE

| Module | Current | Extractions | New Files | Benefit |
|--------|---------|-------------|-----------|---------|
| **chat_server.py** | 2786 L | voice_routes, dashboard_routes, mcp_routes, repo_routes | 4 | Clear route ownership |
| **intent_dispatch.py** | 1750 L | communication_handlers, file_handlers, system_handlers, intelligence_handlers | 4 | Category-based testing |
| **dashboard.py** | 1537 L | dashboard_backend, dashboard_routes, dashboard_ui.html | 3 | Frontend independent |
| **orchestrator.py** | 1186 L | orchestrator_session, orchestrator_safety, orchestrator_streaming, orchestrator_core | 4 | Concern separation |
| **smart_router.py** | 1044 L | provider_implementations, provider_config, router_cache, router_health, router_core | 5 | Layer isolation |
| **TOTAL** | **9,303** | **20 extractions** | **20 files** | ~1000 L per file avg |

---

# RISKS & MITIGATIONS

## Circular Import Risk ⚠️
- **Risk:** chat_server imports from voice_routes, dashboard_routes, etc., but they may import back from each other
- **Mitigation:** Define clear import hierarchy (chat_server is root, routes are leaves). No cross-imports between routes.

## API Stability ⚠️
- **Risk:** Extracting mcp_routes means importing mcp_bridge in multiple places
- **Mitigation:** Wrap mcp_bridge in a single place (mcp_routes.py), others import only what they need

## Testing Coverage ⚠️
- **Risk:** Extracting communication_handlers means email_reader, whatsapp, etc. must work in isolation
- **Mitigation:** Unit tests for each handler (mock external deps). Keep happy path tests simple.

## Migration Complexity ⚠️
- **Risk:** 20 extractions across 5 files = 20+ commits, 100+ changed files
- **Mitigation:** Do ONE file at a time. Test after each. See REFACTOR_TEMPLATE.md for detailed process.

---

# RECOMMENDATION: PHASED APPROACH

## Phase 1: Easy Wins (Low Risk)
1. **chat_server.py → voice_routes.py** ✓ Cleanest boundaries
2. **dashboard.py** ✓ Clear HTML/backend split (move HTML to `.html` file)
3. **smart_router.py → provider_config.py + router_cache.py** ✓ No circular deps

## Phase 2: Medium Complexity
4. **chat_server.py → dashboard_routes.py, mcp_routes.py** (test mcp_bridge isolation)
5. **orchestrator.py → orchestrator_session.py + orchestrator_safety.py** (minimal deps)

## Phase 3: Complex Refactors
6. **intent_dispatch.py** (45 handlers, 1 dispatch table)
7. **orchestrator.py → orchestrator_streaming.py + orchestrator_core.py** (interdependent)
8. **chat_server.py → repo_routes.py** + **smart_router.py → router_health.py + router_core.py** (integrate)

Total estimated work: 40-60 hours spread across 4-8 weeks (1-2 extractions per week).

---

# NEXT STEP

**Awaiting user approval.** Which phase would you like to start with? Or should I proceed with Phase 1 immediately?
