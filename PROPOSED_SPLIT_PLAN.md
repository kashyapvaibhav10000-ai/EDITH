# PROPOSED SPLIT PLAN WITH INTEGRATION MAP

## Overview
20 new module extractions from 5 core files. Each extraction maintains backward compatibility through thin wrapper pattern in original file.

---

## Extraction Plan: By File

### CHAT_SERVER.PY (2786 → ~400 lines)

**Extract 1: voice_routes.py (NEW, 400 lines)**
```
Imports from chat_server:
  - FastAPI @app
  - orchestrator.chat_stream()
  - voice.speak(), voice.listen()
  - smart_memory, episodic_memory
  
Imports TO chat_server:
  - from voice_routes import register_voice_routes(app)
  
Functions moving:
  - _get_voice_memory_context() [helper]
  - _track_widget_msg() [helper]
  - _persist_exchange() [helper]
  - POST /api/voice/transcribe
  - POST /api/voice/respond
  - POST /api/voice/mic-lock
  - POST /api/voice/mic-unlock
  - POST /api/voice/warmup-chatterbox
  - POST /api/voice/stop-tts
  - POST /api/voice/barge-in-complete
  - GET /api/voice/barge-in-status
  - GET /api/voice-status
Integration:
  @app.include_router(voice_router)  # OR call register_voice_routes(app) in __main__
```

**Extract 2: dashboard_routes.py (NEW, 250 lines)**
```
Imports from chat_server:
  - FastAPI @app
  - dashboard.get_system_stats(), etc.
  - orchestrator
  
Functions moving:
  - GET /api/health-check
  - GET /api/system-status
  - GET /api/status
  - GET /api/stats
  - GET /api/costs
  - GET /api/provider-latencies
  - GET /api/monitor_schedule
  - _memory_monitor() [background task]
Integration:
  @app.include_router(dashboard_router)
```

**Extract 3: mcp_routes.py (NEW, 250 lines)**
```
Imports from chat_server:
  - FastAPI @app, APIRouter
  - mcp_bridge (existing)
  - tools.verify_path() (security)
  
Functions moving:
  - All 7 /api/mcp/* routes
  - MCP state management
Integration:
  @app.include_router(mcp_router)
```

**Extract 4: repo_routes.py (NEW, 300 lines)**
```
Imports from chat_server:
  - FastAPI @app, APIRouter
  - repo_dna.analyze_repo()
  - data_analyst
  
Functions moving:
  - All 15 /api/repo/* routes
  - Repo analysis dispatcher
Integration:
  @app.include_router(repo_router)
```

**Remaining in chat_server.py:** ~400 lines
```
- /api/chat, /api/chat/stream [primary]
- /, /dashboard (HTML serving)
- /tg_webhook, /webhook/* [webhooks]
- /api/feedback, /api/phone, /api/weather-status, /api/last-memory
- /api/devpanel/* [dev panel]
- /api/sessions/*
- /api/traces/*
- Middleware: api_key_middleware, rate_limit_middleware
- FastAPI setup, CORS, etc.
```

---

### INTENT_DISPATCH.PY (1750 → ~900 lines)

**Extract 1: communication_handlers.py (NEW, 80 lines)**
```
Functions moving:
  - _handle_email()
  - _handle_unread_email()
  - _handle_sms()
  - _handle_phone()
  - _handle_call()
  - _handle_whatsapp()
Dependencies:
  - email_reader (existing)
  - phone (existing)
  Import from intent_dispatch:
  - DispatchContext [dataclass]
Integration:
  from communication_handlers import (
    _handle_email, _handle_unread_email, ..., _handle_whatsapp
  )
  Then add to INTENT_HANDLERS dict in intent_dispatch.py
```

**Extract 2: file_handlers.py (NEW, 150 lines)**
```
Functions moving:
  - _handle_file_query()
  - _handle_create_file()
  - _handle_delete_file()
  - _handle_mcp()
Dependencies:
  - tools (sandbox, file ops)
  - mcp_bridge
Integration:
  from file_handlers import (
    _handle_file_query, _handle_create_file, _handle_delete_file, _handle_mcp
  )
  Add to INTENT_HANDLERS dict
```

**Extract 3: system_handlers.py (NEW, 300 lines)**
```
Functions moving:
  - _run_local_exec() [ENTIRE FUNCTION + helpers]
    - Process monitoring
    - System info
    - Network diagnostics
    - Privilege checks
    - Duplicate finding
    - File search
    - Generic command execution
Dependencies:
  - command_runner (newly created in Item 7)
  - psutil (optional, for rich stats)
Integration:
  from system_handlers import _run_local_exec
  Export in intent_dispatch for shell handler to use
```

**Extract 4: intelligence_handlers.py (NEW, 280 lines)**
```
Functions moving:
  - _handle_agent()
  - _handle_council()
  - _handle_decision()
  - _handle_self_improve()
  - _handle_profile()
  - _handle_rag()
  - _handle_data_analysis()
  - _handle_system_health()
  - _handle_repo_analyze()
  - _handle_image_gen()
  - _handle_video_summarize()
Dependencies:
  - agent, council, life_os, cognitive_profile, self_improve
  - rag, data_analyst
  - image_gen, video_summarizer
Integration:
  from intelligence_handlers import (
    _handle_agent, _handle_council, ..., _handle_video_summarize
  )
  Add to INTENT_HANDLERS dict
```

**Remaining in intent_dispatch.py:** ~900 lines
```
- dispatch(ctx) [main dispatcher]
- _dispatch_single(ctx) [router]
- execute_pending_action(action) [HITL executor]
- INTENT_HANDLERS [dispatch table, import all handlers]
- _handle_search()
- _handle_weather()
- _handle_calendar_*() [3 functions]
- _handle_morning_briefing(), _handle_briefing()
- _handle_vision()
- _handle_open_app()
- _handle_shell()
- _handle_session_end()
- _handle_wake()
- _handle_compact()
- _handle_think_level()
- _handle_trace_toggle()
- _handle_agent_stop()
- _handle_list_skills()
- _handle_chat_fallback()
- Imports from new files
```

---

### DASHBOARD.PY (1537 → ~200 lines)

**Extract 1: dashboard_backend.py (NEW, 100 lines)**
```
Functions moving:
  - get_system_stats()       [memory, CPU, processes]
  - get_active_model()       [current model]
  - get_ollama_models()      [available models]
  - get_recent_logs()        [last N log entries]
  - get_edith_modules()      [loaded modules]
  - get_mcp_status()         [MCP server state]
Dependencies:
  - psutil
  - chromadb
  - config
  - devlog
Integration:
  from dashboard_backend import (
    get_system_stats, get_active_model, ..., get_mcp_status
  )
  Used by dashboard_routes.py
```

**Extract 2: dashboard_routes.py (NEW, 60 lines)**
```
Endpoints:
  - GET /api/stats
  - GET /api/devpanel/modules
  - POST /api/devpanel/query
Dependencies:
  - FastAPI router
  - dashboard_backend functions
Integration:
  @app.include_router(dashboard_router)
  Imported by chat_server.py
```

**Extract 3: dashboard_ui.html (NEW, 1377 lines)**
```
Content:
  - Full HTML template (lines 121-1457)
  - Embedded CSS (560 lines)
  - Embedded JavaScript (560 lines)
  
Integration:
  In dashboard.py:
    @app.get("/dashboard", response_class=HTMLResponse)
    def dashboard():
        with open("dashboard_ui.html") as f:
            return f.read()
```

**Remaining in dashboard.py:** ~200 lines
```
- import FastAPI, etc.
- GET / route [home page]
- GET /dashboard route [serve dashboard_ui.html]
- Minimal glue code
```

---

### ORCHESTRATOR.PY (1186 → ~650 lines)

**Extract 1: orchestrator_session.py (NEW, 150 lines)**
```
Classes: HistoryManager
Functions moving:
  - class HistoryManager [entire class]
  - HistoryManager._load_history()
  - HistoryManager.compact_history()
  - HistoryManager._append_session_jsonl()
  - remember(key, value)
  - recall(query)
  - Memory cleanup/lifecycle management
Dependencies:
  - SQLite (session DB)
  - ChromaDB (semantic recall)
Integration:
  from orchestrator_session import HistoryManager, remember, recall
  Used by orchestrator_core.py
```

**Extract 2: orchestrator_safety.py (NEW, 100 lines)**
```
Functions moving:
  - _danger_scan(user_input)
  - _classify_scope(user_input)
  - _maybe_create_skill(task_id, summary)
Dependencies:
  - tools.execute_verified_action()
  - life_os
Integration:
  from orchestrator_safety import _danger_scan, _classify_scope, _maybe_create_skill
  Used by orchestrator_core.py
```

**Extract 3: orchestrator_streaming.py (NEW, 250 lines)**
```
Functions moving:
  - chat_stream(user_input, intent, context, system_prompt_override)
  - Stream-specific helpers
  - _split_sentences() [if exists]
  - Token-by-token yield logic
Dependencies:
  - orchestrator_core.chat() [base logic]
  - smart_router.smart_call_stream()
Integration:
  from orchestrator_streaming import chat_stream
  Called directly by chat_server.py
```

**Extract 4: orchestrator_core.py (NEW, 500 lines)**
```
Functions moving:
  - chat(user_input, intent, device, source) [main orchestrator]
  - handle_vision_intent(intent, user_input)
  - _post_turn_reflection(user_input, response)
  - _verify_response(query, response)
  - parse_time(t)
  - handle_intent(intent, user_input, reply)
Dependencies:
  - All cognitive modules
  - intent_dispatch
  - smart_router
  - Imports from orchestrator_session, orchestrator_safety
Integration:
  from orchestrator_core import chat, handle_vision_intent
  Called by chat_server.py
```

**Remaining in orchestrator.py:** ~650 lines
```
- Voice I/O: speak(), speak_stream(), listen()
- Events: set_last_intent(), _emit_intent(), etc.
- Entry: _idle_monitor_loop(), main()
- Imports from extracted modules
- Re-export public functions for backward compatibility
```

---

### SMART_ROUTER.PY (1044 → ~250 lines)

**Extract 1: provider_config.py (NEW, 70 lines)**
```
Functions moving:
  - _require_key(key_value, key_name)
  - _routing_chains()
  - _score_complexity(prompt)
  - detect_pii(text)
  - _has_key(provider_name)
  - _PII_PATTERNS [regex]
Dependencies:
  - config (API keys)
  - os (env vars)
Integration:
  from provider_config import _require_key, _routing_chains, ..., detect_pii
  Used by provider_implementations, router_health, router_core
```

**Extract 2: router_cache.py (NEW, 40 lines)**
```
Functions moving:
  - _context_fingerprint(prompt, intent)
  - _cache_get(fingerprint)
  - _cache_set(fingerprint, response)
  - _response_cache [OrderedDict]
Integration:
  from router_cache import _cache_get, _cache_set, _context_fingerprint
  Used by router_core.py
```

**Extract 3: provider_implementations.py (NEW, 300 lines)**
```
Functions moving:
  - _call_groq(prompt, system)
  - _call_gemini(prompt, system)
  - _call_nvidia(prompt, system)
  - _call_openrouter(prompt, system)
  - _call_ollama(prompt, system)
  - _call_groq_stream() [+4 more streaming variants]
  - _PROVIDER_CALLS [dict mapping]
  - _PROVIDER_STREAM_CALLS [dict mapping]
Dependencies:
  - groq, google.generativeai, requests, ollama
  - provider_config._require_key()
Integration:
  from provider_implementations import (
    _PROVIDER_CALLS, _PROVIDER_STREAM_CALLS, _call_groq, ..., _call_ollama
  )
  Used by router_core.py
```

**Extract 4: router_health.py (NEW, 150 lines)**
```
Functions moving:
  - _call_with_latency_track(fn, args)
  - _get_fastest_provider(providers)
  - get_provider_latency_stats()
  - get_provider_leaderboard()
  - _log_latency_leaderboard()
  - _has_internet()
  - _is_provider_cooled_down(provider_name)
  - _mark_provider_failed(provider_name)
  - _init_usage_db()
  - _log_api_cost(provider, cost)
  - _reset_daily_if_needed()
  - _is_under_daily_limit(provider_name)
  - get_last_call_stats()
  - _provider_failures [state dict]
  - _daily_calls [state dict]
  - _response_times [state dict]
  - _provider_latencies [state dict]
Dependencies:
  - SQLite (usage DB)
  - threading.Lock
Integration:
  from router_health import (
    _call_with_latency_track, _is_provider_cooled_down, _mark_provider_failed,
    ..., get_last_call_stats
  )
  Used by router_core.py
```

**Extract 5: router_core.py (NEW, 350 lines)**
```
Functions moving:
  - smart_call(prompt, intent, context, system_prompt)
  - smart_call_stream(prompt, intent, context, system_prompt)
  - smart_chat(prompt, system)
  - smart_reason(prompt, system)
  - smart_code(prompt, system)
  - router_status()
  - _get_tuner_weights()
  - _apply_tuner_weights(chain)
Dependencies:
  - Imports all 4 router_* modules
  - provider_implementations, router_cache, router_health, provider_config
Integration:
  from router_core import smart_call, smart_call_stream, smart_chat, ..., router_status
  Used by orchestrator_core, intent_dispatch, etc.
```

**Remaining in smart_router.py:** ~250 lines
```
- Import all submodules
- Re-export all public functions for backward compatibility:
  smart_call, smart_call_stream, smart_chat, smart_reason, smart_code,
  router_status, get_last_call_stats, get_provider_latency_stats,
  get_provider_leaderboard, detect_pii
- Optional: __all__ list for explicit exports
```

---

## Dependency Graph (After Splits)

```
chat_server.py (root)
  ├─ import voice_routes
  ├─ import dashboard_routes
  ├─ import mcp_routes
  ├─ import repo_routes
  └─ import api_auth [already extracted, Item 6]

voice_routes.py
  ├─ import orchestrator.chat_stream
  ├─ import voice
  └─ import smart_memory

dashboard_routes.py
  ├─ import dashboard_backend
  └─ import orchestrator

mcp_routes.py
  └─ import mcp_bridge

repo_routes.py
  └─ import repo_dna

intent_dispatch.py (root for handlers)
  ├─ import communication_handlers
  ├─ import file_handlers
  ├─ import system_handlers
  ├─ import intelligence_handlers
  └─ import command_runner [already created, Item 7]

orchestrator.py (root for chat flow)
  ├─ import orchestrator_core
  ├─ import orchestrator_streaming
  ├─ import orchestrator_session
  └─ import orchestrator_safety

orchestrator_core.py
  ├─ import orchestrator_session
  ├─ import orchestrator_safety
  ├─ import smart_router.smart_call
  ├─ import intent_dispatch.dispatch
  └─ [many cognitive modules]

smart_router.py (root for routing)
  ├─ import provider_implementations
  ├─ import router_cache
  ├─ import router_health
  ├─ import provider_config
  └─ import router_core

provider_implementations.py
  └─ import provider_config._require_key

router_core.py
  ├─ import provider_implementations
  ├─ import router_cache
  ├─ import router_health
  └─ import provider_config
```

**KEY PRINCIPLE:** No cross-imports between extractions in different files. Each extraction imports only from its parent or from utility/config modules.

---

## Implementation Checklist

For each extraction, follow the 5-step pattern from REFACTOR_TEMPLATE.md:

### Step 1: Create new file
- Copy functions + dependencies
- Add docstrings
- Test imports

### Step 2: Update parent file imports
- Add: `from new_module import ...`
- Add to registry (INTENT_HANDLERS, router setup, etc.)

### Step 3: Run import test
```bash
python -c "import intent_dispatch; print('OK')"
```

### Step 4: Run functional test
- Call at least one function from new module
- Verify output correct

### Step 5: Commit
```bash
git add .
git commit -m "Extract: <new_module_name> from <parent_module>.py"
```

---

## Risk Mitigation

| Risk | Mitigation |
|------|-----------|
| Circular imports | Use explicit import hierarchy (root always at top level) |
| Missing dependencies | Mock external APIs in test mode; use try/except with fallback |
| State management | Keep state in root module; extracted modules use pure functions |
| API breakage | Use thin wrappers in original file; re-export all public functions |
| Testing coverage | Unit test each extraction independently before merging |
| Large commits | Commit each extraction individually (20 commits total) |

---

## Timeline Estimate

**Phase 1 (Easy, 1-2 weeks):**
1. Extract chat_server.py → voice_routes.py
2. Extract dashboard.py (HTML + backend)
3. Extract smart_router.py → provider_config.py + router_cache.py

**Phase 2 (Medium, 2-3 weeks):**
4. Extract chat_server.py → dashboard_routes.py, mcp_routes.py
5. Extract orchestrator.py → orchestrator_session.py + orchestrator_safety.py

**Phase 3 (Complex, 3-4 weeks):**
6. Extract intent_dispatch.py (all 4 handler modules)
7. Extract orchestrator.py → orchestrator_streaming.py + orchestrator_core.py
8. Extract smart_router.py → provider_implementations.py + router_health.py + router_core.py

**Total: 6-8 weeks, 20 atomic commits**

---

# AWAITING YOUR APPROVAL

Please review and confirm:
1. ✅ Do the proposed splits align with your codebase understanding?
2. ✅ Which phase should we start with (Phase 1 / 2 / 3)?
3. ✅ Any adjustments to the proposed extraction boundaries?
4. ✅ Should I proceed with Phase 1 immediately once approved?

**User directive remembered:** "Wait for my approval before touching any file" — Respected. No changes made yet.
