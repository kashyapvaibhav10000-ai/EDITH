# EDITH Codebase Audit - 2026-04-24

This audit is based on the live workspace at `/home/vaibhav/EDITH`, not only the older `COMPLETE_ARCHITECTURE_ANALYSIS.md`. I did not reproduce secret values. Environment variables are listed by name only.

## 1. Project Overview

EDITH is a local-first personal AI operating system for a single technical user. It combines chat, voice, Telegram, desktop widget, web dashboard, local memory, cloud/local LLM routing, code/RAG search, phone control, calendar/email access, screen vision, MCP tools, proactive monitoring, and a "4 Vision" cognitive layer.

The core problem it solves is personal AI continuity: one assistant that remembers context, routes sensitive work locally, performs multi-step tasks with confirmation, monitors system/life state, and can reason about decisions through multiple perspectives.

Target user: Vaibhav Kashyap, a solo technical user running Linux/KDE-style local infrastructure. This is not multi-tenant and has no public user-management model.

Project type: hybrid monolith plus supervised local services. The domain logic is mostly a Python monolith, while runtime surfaces are split across a FastAPI server, PyQt6 widget, terminal CLI, Telegram polling bot, wake-word listener, dashboard, and background daemon.

Tech stack:

| Area | Implementation |
|---|---|
| Language | Python 3.11 venv (`/home/vaibhav/edith-env`) |
| API/Web | FastAPI, Uvicorn, HTML/CSS/JS dashboards |
| UI | PyQt6 desktop widget; HTML dashboard/UI |
| LLM local | Ollama via `ollama` Python package |
| LLM cloud | Groq, Gemini, NVIDIA NIM, OpenRouter |
| RAG/vector | ChromaDB persistent clients; LlamaIndex for notes |
| Memory DB | SQLite (`memory_archive.db`, `session_state.db`, `trace_log.db`) |
| Graph | NetworkX persisted as JSON |
| Voice | Piper TTS, Whisper.cpp via `pywhispercpp`, Vosk wake listener, WebRTC VAD |
| Data | pandas, matplotlib |
| Automation | subprocess, schedule, systemd user services |
| External tooling | Docker, KDE Connect, yt-dlp, Tesseract, MCP servers via `npx` |

Repository size observed: 60 top-level Python files, roughly 21k lines across top-level Python, requirements, UI HTML, dashboard HTML, and the previous architecture document.

## 2. Folder And File Structure

Important folders:

| Folder | Role |
|---|---|
| Root `/home/vaibhav/EDITH` | Main Python modules, services, UI files, credentials/tokens, runtime DBs |
| `.claude/` | Local assistant configuration/skill material |
| `.vscode/` | IDE settings |
| `TestProject/`, `test/` | Placeholder/test directories; currently not a formal test suite |
| `__pycache__/` | Python bytecode cache |
| `charts/` | matplotlib chart outputs |
| `chroma_db/` | Alternate ChromaDB store; currently contains `edith_codebase` |
| `data/` | JSONL short-term session memory (`session_memory.jsonl`) |
| `downloads/` | YouTube audio/transcripts and other downloaded artifacts |
| `edith-env/` | Python virtual environment; should not be treated as source |
| `edith-memory/` | Older/alternate ChromaDB store with collection `edith` |
| `files/` | Copies of architecture updater service/script |
| `images/` | Generated image outputs |
| `logs/` | Runtime logs (`edith.log`, widget, daemon, MCP, security audit) |
| `memory_db/` | Main ChromaDB vector store plus `edith_graph.json` |
| `memory_db_backup/` | Background backup copy of `memory_db` |
| `models/` | Whisper/Vosk local speech models |
| `notes/` | Personal notes indexed by `rag.py` |
| `repos/ayurstock/` | Related external project included for code context; not the EDITH app itself |
| `searxng-config/` | Local SearXNG configuration |
| `voices/` | Piper voice models |
| `whisper.cpp/` | Vendored/external Whisper.cpp repo |
| `ollama-models` | Symlink to `/home/vaibhav/.ollama` |

Primary entry points:

| File | Role |
|---|---|
| `edith.py` | Terminal menu, system checks, smoke tests, module launcher |
| `orchestrator.py` | Core brain for terminal/chat flow; memory recall, danger scan, Council/direct response, session JSONL persistence |
| `chat_server.py` | Main FastAPI server on `127.0.0.1:8001`; widget/dashboard/API/MCP endpoints |
| `edith_widget.py` | PyQt6 desktop widget; Ctrl+Space workflow |
| `background_daemon.py` | systemd-notify daemon; starts and monitors `chat_server.py` and `wake_listener.py`; scheduled maintenance |
| `telegram_bot.py` | Telegram long-polling interface and scheduled briefings |
| `wake_listener.py` | Always-on Vosk wake-word listener |
| `dashboard.py` | Legacy/standalone dashboard server on port 8000 |

Core files by domain:

| Domain | Files |
|---|---|
| Configuration/common | `config.py`, `errors.py`, `context.py` |
| Intent/routing | `intent.py`, `intent_dispatch.py`, `smart_router.py`, `ml_router.py`, `conversation_dna.py` |
| Memory/cognition | `smart_memory.py`, `cognitive_profile.py`, `session.py`, `episodic_memory.py`, `graph_memory.py`, `consolidation.py` |
| Decision/council/self-improve | `council.py`, `life_os.py`, `self_improve.py` |
| I/O integrations | `voice.py`, `vision.py`, `ocr.py`, `search.py`, `weather.py`, `email_reader.py`, `edith_email.py`, `calendar_reader.py`, `phone.py`, `whatsapp.py` |
| Automation/safety | `agent.py`, `sandbox.py`, `tools.py`, `compound_dag.py`, `circuit_breaker.py`, `mcp_bridge.py` |
| Observability/tuning | `trace_logger.py`, `feedback_tagger.py`, `tuner.py`, `monitor.py`, `devlog.py`, `security_audit.py` |
| Knowledge/code | `rag.py`, `code_rag.py`, `coding_style.py`, `data_analyst.py`, `image_gen.py`, `video_summarizer.py` |
| Architecture tooling | `edith_arch_updater.py`, `edith_scanner.py`, generated `edith_flow.html`, `edith_map.html`, `edith_dashboard.html`, `edith_modules.json` |

Configuration files:

| File | Configures |
|---|---|
| `.env` | Non-secret/current environment overrides and API key names; actual observed names are listed in section 8 |
| `mcp_config.json` | MCP server commands, enabled flags, descriptions, allowed intent metadata |
| `requirements.txt` | Pinned Python packages |
| `.gitignore` | Excludes `.env`, tokens, vault, DBs, logs, env, generated artifacts |
| `.agentignore` | Agent ignore rules (`whisper.cpp/`, `edith-env/`, `__pycache__/`, `*.pyc`) |
| `edith.service` | systemd user service for `background_daemon.py` |
| `edith-widget.service` | systemd user service for desktop widget |
| `edith-arch-updater.service` | one-shot architecture auto-updater |
| `start_edith.sh` | Starts user service and widget |
| `credentials.json`, `token.json`, `token.pickle` | Google OAuth credential/token files |
| `vault.enc`, `vault.salt` | Encrypted vault data and Argon2 salt |

Stray/noisy files: two Windows-path-named zero-byte files exist at root; they are likely accidental artifacts and should be removed after confirmation.

## 3. Architecture And Design Patterns

The architecture is an event-driven personal AI control plane with a conductor/orchestrator core. It is not strict MVC/Clean Architecture; it is closer to modular monolith plus local micro-daemons.

Primary runtime flow:

`entry surface -> intent detection -> dispatch/orchestrator -> tool/LLM/memory -> response -> trace/memory/session persistence`

Layering is present but informal:

| Layer | Modules |
|---|---|
| Presentation | `edith.py`, `chat_server.py`, `edith_widget.py`, `dashboard.py`, `telegram_bot.py` |
| Intent/routing | `intent.py`, `intent_dispatch.py`, `smart_router.py`, `ml_router.py` |
| Business/cognitive | `orchestrator.py`, `council.py`, `life_os.py`, `self_improve.py`, `agent.py` |
| Memory/storage | `smart_memory.py`, `cognitive_profile.py`, `session.py`, `episodic_memory.py`, `graph_memory.py`, ChromaDB, SQLite |
| External I/O | `search.py`, `weather.py`, email/calendar/phone/vision/voice/MCP |
| Infra/observability | `background_daemon.py`, `monitor.py`, `trace_logger.py`, `feedback_tagger.py`, `tuner.py`, `circuit_breaker.py` |

Patterns found:

| Pattern | Example |
|---|---|
| Singleton | `config.get_chroma_client()` shared ChromaDB client |
| Dispatch table | `intent_dispatch.INTENT_HANDLERS` maps intent strings to handler functions |
| Strategy/routing | `smart_router.ROUTING_CHAINS` selects provider order by task type |
| Chain of responsibility | `smart_call()` tries cloud providers then Ollama fallback |
| LRU cache | `SmartMemoryManager.ram_cache` and `smart_router._response_cache` use `OrderedDict` |
| Circuit breaker | `CircuitBreaker` state machine with `CLOSED`, `OPEN`, `HALF_OPEN` |
| Observer-ish/session hooks | `session.end_session()` triggers profile update, drift check, episode save, graph ingest |
| Factory/process pool | `mcp_bridge._get_process()` starts/restarts per-server MCP subprocess wrappers |
| State machine | session status active/ended; circuit breaker states |
| Adapter | wrappers around Telegram, Gmail, Calendar, KDE Connect, SearXNG/search APIs |

Separation of concerns is strongest in `intent_dispatch.py`, `smart_router.py`, and the memory modules. It is weakest in `orchestrator.py`, which still contains UI prompts, memory management, persona prompt construction, routing, speech output, and terminal loop logic.

## 4. Data Flow

FastAPI widget request lifecycle:

1. UI sends `POST /api/chat` with `{ "message": "..." }`.
2. `chat_server.chat_endpoint()` checks pending HITL actions.
3. It detects follow-ups with `_is_followup()`.
4. It calls `intent.detect_intent()`.
5. It builds `DispatchContext(user_input, intent, source="widget", chat_fn=orchestrator.chat)`.
6. `intent_dispatch.dispatch()` invokes the mapped handler.
7. Handler either performs direct tool work or calls `ctx.chat_fn()`.
8. `orchestrator.chat()` runs danger scan, recalls smart memory and episodic memory, compresses context, computes Conversation DNA style, and calls `smart_router.smart_call()` or `quick_council()`.
9. `smart_router` enforces local-only intent routing, cache, provider daily limits, provider cooldown, and provider chain.
10. Response returns to chat server as `{ "reply": "...", "intent": "..." }`.
11. Widget history and session JSONL/memory are updated.

Terminal lifecycle:

1. `edith.py` launches `orchestrator.py`, or user runs `orchestrator.py` directly.
2. `orchestrator.main()` starts a session, schedules Chroma cleanup, starts DevLog and idle consolidation thread.
3. Each input is tracked via `session.track_query()`.
4. Compound inputs are split by `compound_dag.py`.
5. Vision-system/action intents are handled directly; general chat calls `orchestrator.chat()`.
6. Replies are printed and spoken through `voice.speak()`.
7. Exit triggers `session.end_session()`.

Telegram lifecycle:

1. `telegram_bot.poll_telegram()` long-polls `getUpdates`.
2. Chat ID is compared to configured `TELEGRAM_CHAT_ID`.
3. Text is tracked and routed through `DispatchContext` and `intent_dispatch.dispatch()`.
4. Responses are split into <=4000-character chunks and sent via `sendMessage`.

Data transformations:

| Input | Transformation | Output/storage |
|---|---|---|
| Natural language | Regex + ML + LLM fallback intent classification | intent string |
| User query | danger keywords + scope categorization | safety metadata/logs |
| User query | smart memory FTS/LIKE recall + episodic Chroma recall | context text |
| Retrieved chunks | `compress_context()` dedupe | compact LLM context |
| Prompt | smart router provider chain | assistant text |
| Session queries | profile proposal, drift report, episode, graph triples | SQLite/Chroma/JSON |
| Web search results | normalized `{title,url,snippet}` | LLM prompt context |
| Audio | VAD frames -> WAV -> Whisper segments | transcript |
| Screenshot/image | file capture -> Ollama/Gemini vision | description |
| CSV/Excel | pandas dataframe -> summary/chart/LLM analysis | text + PNG chart |

State is managed in RAM globals, SQLite, JSON, and ChromaDB. Important globals include `orchestrator.conversation_history`, `session._current_session`, `smart_router._response_cache`, `smart_router._provider_failures`, `intent_dispatch._pending_action`, `_widget_history`, `_managed_processes`, and voice TTS/mic events.

## 5. Database And Data Layer

Storage systems:

| Store | Path | Purpose |
|---|---|---|
| SQLite | `memory_archive.db` | smart memory, API usage, feedback |
| SQLite | `session_state.db` | session continuity |
| SQLite | `trace_log.db` | request traces |
| ChromaDB | `memory_db/` | main memory, profile, query log, personas, episodes, open loops |
| ChromaDB | `chroma_db/` | codebase vector index |
| ChromaDB | `edith-memory/` | legacy/alternate collection |
| JSON | `memory_db/edith_graph.json` | NetworkX node-link graph |
| JSONL | `data/session_memory.jsonl` | recent conversation history |
| JSON | `maintenance_state.json`, `coding_personality.json`, optional `prime_directive.json` | runtime state/config |

Observed Chroma collections:

| Store | Collection | Count | Dimension |
|---|---:|---:|---:|
| `memory_db` | `edith_memory` | 87 | 384 |
| `memory_db` | `edith_query_log` | 9 | 384 |
| `memory_db` | `edith_open_loops` | 3 | 384 |
| `memory_db` | `edith_episodic` | 1 | 384 |
| `memory_db` | `edith_user_profile` | 1 | 384 |
| `memory_db` | `persona_strategist/critic/builder/wildcard` | 1 each | 384 |
| `chroma_db` | `edith_codebase` | 1214 | 384 |
| `edith-memory` | `edith` | 7 | not inspected beyond count |

SQLite schemas:

`memory_archive.db`:

| Table | Fields |
|---|---|
| `memories` | `id`, `key`, `value`, `category`, `timestamp`, `created_at` |
| `memories_fts` | FTS5 virtual table over `key`, `value` |
| `api_usage` | `provider`, `date`, `call_count` |
| `feedback` | `trace_id`, `feedback`, `reason`, `created_at` |

`session_state.db`:

| Table | Fields |
|---|---|
| `sessions` | `session_id`, `device`, `start_time`, `last_active`, `query_count`, `queries_json`, `context_snapshot`, `status` |

`trace_log.db`:

| Table | Fields |
|---|---|
| `trace_index` | `trace_id`, `user_input`, `intent`, `device`, `created_at`, `completed_at`, `total_layers`, `final_status`, `feedback` |
| `traces` | `trace_id`, `layer`, `timestamp`, `input_summary`, `output_summary`, `confidence`, `status`, `metadata_json` |

Relationships are logical, not enforced by foreign keys:

| Relationship | Cardinality |
|---|---|
| Session -> queries | one-to-many in `queries_json` and query log |
| Trace index -> trace layers | one-to-many by `trace_id` |
| User profile -> observations | one-to-many by category/Chroma collection |
| Council persona -> persona memories | one-to-many per persona collection |
| Open loops -> user | many open loop documents for one user |
| Graph node -> graph edges | many-to-many through NetworkX directed edges |

Migrations are ad hoc: modules run `CREATE TABLE IF NOT EXISTS`; there is no Alembic/Prisma-style migration system for EDITH. Chroma collections are created lazily. Seed data is mostly implicit: default prime directive, test harness examples, existing vector data, and note files under `notes/`.

## 6. APIs And Interfaces

Main FastAPI server: `chat_server.py` on `127.0.0.1:8001`.

| Method | Route | Purpose | Shape |
|---|---|---|---|
| GET | `/` | Redirect to dashboard | Redirect to `http://127.0.0.1:8001/dashboard` |
| POST | `/api/chat/stream` | SSE token streaming | request `{message}`; stream `data: token`, `[DONE]` |
| POST | `/api/chat` | Main widget/API chat | request `{message}`; response `{reply, intent}` |
| GET | `/api/system-status` | Legacy redirect | redirects to `/api/status` |
| GET | `/api/recent_traces?limit=N` | API usage rows from archive DB | `{traces:[{provider,date,call_count}]}` |
| GET | `/api/monitor_schedule` | Maintenance schedule/state | timestamps + static schedule |
| POST | `/api/feedback` | Store thumbs feedback | request `{trace_id, feedback, reason?}`; `{ok}` |
| GET | `/dashboard` | Dashboard HTML | `edith_dashboard.html` |
| GET | `/api/stats` | Dashboard aggregate | system/model/log/module/MCP stats |
| GET | `/api/status` | Combined provider/system status | provider and circuit-breaker status |
| GET | `/api/last-memory` | Last 3 memories | `{memories:[...]}` |
| GET | `/api/phone` | KDE Connect phone summary | `{battery,status,last_notification}` |
| GET | `/api/weather-status` | Open-Meteo current weather | weather dict or error |
| GET | `/api/traces/recent?limit=N` | Recent trace index rows | `{traces:[...]}` |
| GET | `/api/logs/stream` | SSE log tail | last 100 lines then live lines |
| GET | `/api/mcp/status` | MCP status | server status dict |
| GET | `/api/mcp/tools/{server_name}` | MCP tool list | `{server, tools}` |
| POST | `/api/mcp/call` | Call MCP tool | request `{server, tool, arguments}` |
| GET | `/api/mcp/config` | Return MCP config | raw config JSON |
| POST | `/api/mcp/config/add` | Add/update MCP server | `{name, command, args, env_vars, ...}` |
| POST | `/api/mcp/config/toggle/{server_name}` | Toggle server | `{ok,name,enabled}` |
| DELETE | `/api/mcp/config/remove/{server_name}` | Remove server | `{ok,removed}` |

Legacy dashboard: `dashboard.py` on `127.0.0.1:8000`.

| Method | Route | Purpose |
|---|---|---|
| GET | `/api/stats` | system/model/log/module/MCP stats |
| GET | `/` | embedded dashboard HTML |

Event interfaces:

| Interface | Implementation |
|---|---|
| SSE chat stream | `/api/chat/stream` |
| SSE logs | `/api/logs/stream` |
| Telegram polling | `telegram_bot.poll_telegram()` long-polls Bot API |
| systemd watchdog | `background_daemon._sd_notify()` |
| Wake events | Vosk loop triggers greeting/widget hotkey |
| MCP | JSON-RPC 2.0 over persistent stdio subprocesses |

CLI/module interfaces:

| Command | Purpose |
|---|---|
| `python edith.py` | interactive main menu |
| `python orchestrator.py` | terminal EDITH chat loop |
| `python chat_server.py` | FastAPI server on 8001 |
| `python dashboard.py` | legacy dashboard on 8000 |
| `python telegram_bot.py` | menu for polling/briefing/scheduler |
| `python wake_listener.py` | wake listener |
| `python edith_widget.py` | desktop widget |
| `python code_rag.py --index` | intended code indexing, currently broken by syntax error |
| `python test_harness.py` | 20 scenario smoke harness |
| `python vault.py` | interactive vault menu |
| `python security_audit.py` | local security audit |

External APIs/services consumed:

Groq, Gemini, NVIDIA NIM, OpenRouter, local Ollama, Serper, Exa, Tavily, local SearXNG, DuckDuckGo/DDGS, Open-Meteo, ArXiv, Pollinations image API, Telegram Bot API, Gmail IMAP, Gmail API, Google Calendar API, KDE Connect CLI, Joplin clipper API, WhatsApp bridge, MCP servers (`server-filesystem`, GitHub, Google Drive, Cloudflare, optional Brave search), Docker daemon, Tesseract, yt-dlp, Piper, Whisper/Vosk.

## 7. Authentication And Authorization

Auth mechanisms:

| Area | Mechanism |
|---|---|
| Telegram | Bot token + `TELEGRAM_CHAT_ID` allowlist |
| Google Calendar | OAuth2 installed-app flow using `credentials.json` and `token.json` |
| Gmail API compose | OAuth token pickle (`token.pickle`) |
| Gmail IMAP | app password/env credentials |
| Cloud LLM/search | API keys in vault or env |
| Vault | Argon2-derived Fernet key from `EDITH_MASTER_KEY` or `~/.edith/vault_key` |
| Local FastAPI | No authentication; relies on localhost binding/CORS/rate limit |
| MCP config/call endpoints | No authentication; rely on localhost binding |

Authorization model: single-user implicit admin. There is no RBAC. Route-level protection is mostly absent; safety is intent/tool-level.

Privacy gates:

| Gate | Behavior |
|---|---|
| `smart_router.LOCAL_ONLY_INTENTS` | email, unread email, file creation, vault, shell, RAG, phone, call, SMS forced to Ollama |
| `intent_dispatch` pending actions | shell/create/delete/agent/WhatsApp can require YES/NO |
| `tools.py` | terminal HITL confirmations for file/shell operations |
| `mcp_bridge._check_privacy()` | blocks MCP only for `vault` and `shell` contexts |

Important security gap: `smart_router.detect_pii()` exists but is not called by `smart_call()`, so PII detection currently does not force local routing.

## 8. Configuration And Environment

Observed `.env` variable names:

`WHATSAPP_BRIDGE_URL`, `EDITH_CITY`, `EDITH_LAT`, `EDITH_LON`, `GROQ_ARCH_KEY`, `SERPER_API_KEY`, `EXA_API_KEY`, `TAVILY_API_KEY`, `GITHUB_PERSONAL_ACCESS_TOKEN`, `CLOUDFLARE_API_TOKEN`, `CLOUDFLARE_ACCOUNT_ID`.

Additional variables referenced by code/vault:

`GROQ_API_KEY`, `GEMINI_API_KEY`, `NVIDIA_API_KEY`, `OPENROUTER_API_KEY`, `TELEGRAM_TOKEN`, `TELEGRAM_CHAT_ID`, `GMAIL_ADDRESS`, `GMAIL_APP_PASSWORD`, `SIMPLENOTE_EMAIL`, `SIMPLENOTE_PASSWORD`, `EDITH_MASTER_KEY`, `JOPLIN_TOKEN`, `BRAVE_API_KEY`, `XAUTHORITY`, `DISPLAY`, `XDG_RUNTIME_DIR`, `PULSE_SERVER`, `NOTIFY_SOCKET`.

There are no explicit dev/staging/prod configs. The practical environments are:

| Mode | Characteristics |
|---|---|
| Local dev | Run modules directly; localhost services; manual CLI |
| Personal production | systemd user services, widget, daemon, wake listener, Telegram |
| Architecture updater | one-shot boot service depending on Joplin/network |

Secrets management is mixed. `vault.py` is a strong direction: Argon2 + Fernet, keyfile permission check, atomic encrypted writes, backup before overwrite. But some modules still read directly from `.env`, and local token files remain plaintext.

## 9. Key Functions And Logic

Most important functions/classes:

1. `chat_server.chat_endpoint()` - main widget API. Handles pending confirmations, follow-ups, intent detection, dispatch, widget history.
2. `intent.detect_intent()` - priority-ordered regex intent engine with ML and LLM fallbacks.
3. `intent_dispatch.dispatch()` - unified handler dispatch table replacing long if/elif chains for web/Telegram.
4. `orchestrator.chat()` - core response builder: danger scan, memory recall, episodic recall, context compression, Conversation DNA, Council/direct routing, memory persistence.
5. `smart_router.smart_call()` - provider chain, local-only privacy gate, cache, cooldowns, daily limits, offline handling.
6. `SmartMemoryManager.remember()/recall()` - hot RAM + SQLite FTS memory layer with recency scoring.
7. `session.end_session()` - profile update, drift check, open loops, episodic save, graph ingest, prime directive summary.
8. `council.run_council()` - parallel 4-persona reasoning plus synthesis.
9. `life_os.simulate_decision()` - 5-branch decision simulation using prime directive/profile.
10. `background_daemon._setup_schedule()` and `_watchdog_loop()` - local production supervision and scheduled maintenance.
11. `mcp_bridge._MCPProcess.send()` - persistent JSON-RPC request/response over stdio to MCP servers.
12. `trace_logger.new_trace()/log_layer()/complete_trace()` - trace persistence used by dashboard and feedback.

Non-obvious/tricky logic:

| Area | Detail |
|---|---|
| Response cache | `smart_router._context_fingerprint()` includes hourly time bucket and top entity, not just prompt hash |
| Context compression | `SequenceMatcher` dedupes memory chunks before LLM prompts |
| Intent priority | Weather/OCR/WhatsApp/wake/vision-system intents are checked before generic lookup/search |
| Provider routing | Cloud provider order varies by task type; local-only intent bypasses cloud |
| Wake listener | fuzzy wake-word matching includes deliberate phonetic misrecognitions |
| MCP | subprocesses are long-lived, with background stdout/stderr readers and per-request queues |
| Session | session DB stores only last 50 queries per session in `queries_json` |

## 10. Dependencies

Major dependencies:

| Dependency | Purpose |
|---|---|
| `fastapi`, `uvicorn`, `starlette` | API/dashboard server |
| `ollama` | local LLM calls |
| `chromadb` | vector memory/codebase store |
| `llama-index-*` | note RAG |
| `requests`, `httpx`, `aiohttp` | external API calls |
| `google-*` | Calendar/Gmail OAuth/API |
| `IMAPClient` | email inbox reading |
| `python-telegram-bot`, direct HTTP | Telegram integration |
| `PyQt6`, `pynput`, `python-xlib` | desktop widget/hotkeys |
| `pywhispercpp`, `openai-whisper`, `faster-whisper`, `vosk`, `PyAudio`, `webrtcvad`, `piper-tts` | voice/wake/STT/TTS |
| `pandas`, `matplotlib`, `openpyxl` | CSV/Excel/chart analysis |
| `networkx` | knowledge graph |
| `cryptography`, `argon2-cffi` | encrypted vault |
| `docker` | code sandbox |
| `psutil`, `schedule` | monitoring/scheduling |
| `scikit-learn` | ML intent classifier |
| `ddgs`, `duckduckgo_search` | fallback web search |
| `pytesseract`, `pillow` | OCR/image handling |
| `torch`, CUDA/NVIDIA packages | heavyweight ML stack, apparently mostly transitive/unused for current CPU-first EDITH |
| `pytest`, `pytest-asyncio` | test harness/dev testing |

Dependency status:

`pip check` reports no broken requirements. Live PyPI check showed many packages behind current versions, including `fastapi 0.135.3 -> 0.136.1`, `uvicorn 0.43.0 -> 0.46.0`, `chromadb 1.5.5 -> 1.5.8`, `pydantic 2.12.5 -> 2.13.3`, `python-dotenv 1.0.1 -> 1.2.2`, `cryptography 46.0.6 -> 46.0.7`, `openai 2.30.0 -> 2.32.0`, `protobuf 6.33.6 -> 7.34.1`, and `pip 24.0 -> 26.0.1`.

Risky dependency observations:

| Risk | Detail |
|---|---|
| Bloated environment | Requirements include many heavy CUDA/NVIDIA/Torch packages despite CPU-first stated hardware |
| Missing from requirements | `voice.py` imports `webrtcvad`; installed in venv but not listed in `requirements.txt` |
| Duplicate/overlapping stacks | multiple Whisper stacks, multiple search clients, LangChain/LangGraph/LlamaIndex/LiteLLM all present |
| No lock tooling | `requirements.txt` is pinned but not generated with hashes; no constraints/dev split |
| External repo noise | `whisper.cpp/` and `repos/ayurstock/` are in workspace and can pollute scans if not excluded |

## 11. Testing

Testing tools: `pytest` is installed, but the project uses a custom script, `test_harness.py`, rather than a conventional `tests/` suite.

Tests present:

| Type | Coverage |
|---|---|
| Smoke/system checks | `edith.py run_smoke_tests()` checks file/service existence and Ollama |
| Scenario harness | `test_harness.py` has 20 scenarios for config, intent, memory, DAG, circuit breaker, trace, feedback, tuner, monitor |
| Manual module tests | Many files have `if __name__ == "__main__"` interactive/manual tests |

Verification results from this audit:

| Command | Result |
|---|---|
| `python -m py_compile *.py` | failed: `code_rag.py` and `coding_style.py` syntax errors |
| `/home/vaibhav/edith-env/bin/python test_harness.py` | 17/20 passed |
| `/home/vaibhav/edith-env/bin/python -m pip check` | no broken requirements |

Failed harness cases:

| Test | Cause |
|---|---|
| Pre-intent danger scan | importing `orchestrator` imports `sandbox`, and `sandbox.py` calls `docker.from_env()` at import time; Docker socket permission error |
| Input scope classification | same import-time Docker side effect |
| WhatsApp stub module | `.env` has `WHATSAPP_BRIDGE_URL`, so test assumption "bridge not configured" is false |

Coverage is narrow and not measured. There is no CI coverage report, no pytest suite layout, and no mocking around external services.

## 12. Build, Deploy, CI/CD

Build process: none beyond virtualenv + `pip install -r requirements.txt`. There is no package metadata (`pyproject.toml`, `setup.py`) for EDITH itself.

Deployment:

| Mechanism | Role |
|---|---|
| `edith.service` | systemd user service running `background_daemon.py` with watchdog |
| `background_daemon.py` | starts and restarts `chat_server.py` and `wake_listener.py` |
| `edith-widget.service` | starts desktop widget after EDITH service |
| `start_edith.sh` | starts systemd service and launches widget if absent |
| `edith-arch-updater.service` | one-shot Joplin architecture updater |

There is no CI/CD pipeline in this workspace and no git repository detected at `/home/vaibhav/EDITH`.

Script/port mismatch:

| File | Behavior |
|---|---|
| `chat_server.py` | runs on port 8001 |
| `dashboard.py` | runs on port 8000 |
| `edith.py.open_dashboard()` | opens dashboard.py on 8000 |
| `chat_server.index()` | redirects root to 8001 dashboard |

## 13. Error Handling And Logging

Logging is centralized through `config.get_logger(name)`, which creates `edith.<name>` loggers, logs INFO to console, DEBUG to `logs/edith.log`.

Error handling patterns:

| Pattern | Examples |
|---|---|
| Broad try/except fallback | search providers, weather, email, vision, router providers |
| Graceful user messages | `intent_dispatch._friendly_error()` |
| Result wrapper | `errors.Result`, used in config/circuit/dispatch/trace-adjacent code |
| Provider cooldown | `smart_router._mark_provider_failed()` exponential cooldown |
| Circuit breaker | `circuit_breaker.py` health state |
| Scheduled alerting | background daemon sends Telegram/KDE notifications |

Monitoring/alerting:

`monitor.py` checks disk/RAM/CPU/phone/weather/breaks. `background_daemon.py` schedules maintenance, proactive checks, KDE heartbeat, and Telegram alert fallback. `/api/status`, `/api/logs/stream`, trace endpoints, and dashboard stats expose runtime status.

Weak spots:

| Weak spot | Detail |
|---|---|
| Excess broad exceptions | many errors are swallowed, hiding bugs |
| Import-time side effects | `sandbox.py` connects to Docker at import time |
| Inconsistent Result usage | most modules still return strings/tuples |
| Some background jobs call missing functions | `background_daemon._extract_daily_graph_triples()` imports nonexistent `graph_memory.extract_and_store_triples` |
| Terminal `input()` in server paths | confirmed create/delete can call `tools.write_file/delete_file`, which prompt on stdin and can hang web server |

## 14. Performance Considerations

Caching:

| Cache | Location |
|---|---|
| Smart memory RAM LRU | `SmartMemoryManager.ram_cache`, 50 items configured |
| Router response LRU | `smart_router._response_cache`, 100 entries, 1h TTL |
| Internet connectivity | `smart_router._internet_ok`, 30s TTL |
| Provider daily usage | SQLite `api_usage` + in-memory dict |
| Prefetch | background daemon weather/daily report cache |
| Whisper model | lazy singleton `_whisper_model` |
| MCP tools/processes | persistent subprocesses and `_tool_cache` |

Rate limiting/throttling:

| Mechanism | Detail |
|---|---|
| FastAPI middleware | 120 requests/minute per IP |
| Smart router daily limits | per-provider counters in `api_usage` |
| Search daily limits | Serper/Exa/Tavily/SearXNG/DDG limits |
| Provider cooldown | 60-300s exponential backoff |
| Telegram chunking | 4000 char chunks |
| Command timeouts | many subprocesses 5-30s |

Bottlenecks:

| Bottleneck | Impact |
|---|---|
| Mostly synchronous I/O | FastAPI handlers use `to_thread` in places but many modules block |
| Chroma/Ollama cold starts | first query/embedding/model load can be slow |
| Council | 4 parallel LLM calls plus synthesis; high latency/cost |
| Voice transcription | Whisper small on CPU can be slow |
| Dashboard imports | `/api/stats` imports dashboard module and runs subprocess curl |
| Requirements bloat | heavy ML/CUDA stack strains disk/install time |
| Global locks | single locks around router cache/usage and session DB can serialize under concurrent use |

## 15. Security

Security measures in place:

| Measure | Location |
|---|---|
| Localhost bind | `chat_server.py` runs `127.0.0.1:8001` |
| CORS allowlist | localhost origins only |
| API rate limiting | chat server middleware |
| Local-only LLM intents | `smart_router.LOCAL_ONLY_INTENTS` |
| Dangerous command patterns | `config.DANGEROUS_PATTERNS`, `agent.is_dangerous()` |
| HITL confirmations | `tools.py`, `intent_dispatch` pending actions, `agent.py` |
| Docker sandbox | `sandbox.py` network-disabled, memory-limited containers |
| Vault encryption | Argon2 + Fernet |
| `.gitignore` | excludes secrets/tokens/DB/log artifacts |
| MCP privacy guard | blocks vault/shell contexts |

Security concerns:

| Severity | Concern |
|---|---|
| High | Previous open architecture document included literal secrets/API keys; rotate any exposed keys and remove secret values from docs/history |
| High | FastAPI and MCP config endpoints are unauthenticated; if binding/CORS changes or local malware can call them, MCP server commands can be added/toggled |
| High | `smart_router.detect_pii()` is unused, so PII does not currently force local routing |
| High | MCP `allowed_intents` metadata is not enforced; only `vault` and `shell` are blocked |
| High | `sandbox.py` connects to Docker at import time and can break unrelated imports/tests |
| Medium | `intent_dispatch.execute_pending_action()` can run unsafe shell commands after YES without rechecking `agent.is_dangerous()` |
| Medium | Web-confirmed create/delete actions call `tools.py`, causing second terminal HITL and possible server hang |
| Medium | `phone.send_sms()` and `phone.initiate_call()` can execute after parsing complete request; not consistently HITL-gated |
| Medium | Local tokens and conversation DBs are plaintext at rest |
| Medium | `security_audit.py` uses `shell=True` with composed strings |
| Low | CORS is local, but no CSRF token/session model exists |

## 16. Code Quality And Conventions

Conventions:

| Area | Status |
|---|---|
| Naming | Mostly snake_case modules/functions, PascalCase classes, UPPER constants |
| Docstrings | Many modules have good top-level docstrings; function docstrings are inconsistent |
| Typing | Some newer modules use type hints; many older modules do not |
| Formatting | No Black/Ruff/isort config |
| Linting | No configured linter |
| Tests | custom harness only |
| Packaging | no project package/pyproject |

Quality strengths:

| Strength | Example |
|---|---|
| Modular feature grouping | separate files for voice/search/weather/profile/council/etc. |
| Good runtime pragmatism | graceful fallbacks, local-first defaults, systemd support |
| Observability exists | trace logger, dashboard, logs, feedback/tuner |
| Privacy direction is clear | local-only intent concept and vault |

Quality issues/code smells:

| Issue | Concrete example |
|---|---|
| Syntax errors | `code_rag.py` lines 33-39/45-48/60-63 and `coding_style.py` lines 70-82 are missing commas |
| Long god module | `orchestrator.py` is 866 lines and mixes CLI, prompting, memory, LLM, speech, and routing |
| Duplicate routing paths | terminal `handle_intent()` and web `intent_dispatch.py` overlap |
| Global mutable state | router, session, widget history, pending action, voice flags, daemon processes |
| Broad catches | many `except Exception: pass` blocks |
| Stale/generated docs | `edith_scanner.py` descriptions conflict with current code in places |
| Runtime docs drift | old analysis says port 8000 main server; current `chat_server.py` uses 8001 |
| No formal boundaries | external repos and vendored Whisper live inside same workspace |

## 17. What's Missing / Improvements

Highest priority fixes:

1. Fix syntax errors in `code_rag.py` and `coding_style.py`. These break code-indexing and coding-style flows immediately.
2. Move `docker.from_env()` inside `run_code_in_sandbox()` or lazy-init it. Importing `orchestrator` should not require Docker socket access.
3. Enforce PII detection in `smart_router.smart_call()` before provider routing.
4. Enforce `mcp_config.json` `allowed_intents`, and require HITL/auth for MCP config mutation endpoints.
5. Remove terminal `input()` from web execution paths; implement all HITL through request/response pending actions.
6. Rotate any secrets that appeared in previous documentation and scrub secret values from local docs/logs.
7. Unify ports and dashboard ownership: choose 8001-only or keep dashboard.py truly separate.
8. Add real pytest tests with mocks for Docker/Ollama/Chroma/network/Telegram/Google/KDE.

Medium-term improvements:

| Area | Improvement |
|---|---|
| Packaging | add `pyproject.toml`, package modules, split dev/prod requirements |
| Lint/format | add Ruff/Black/isort and run in CI |
| Migration | add schema versioning for SQLite and Chroma collection metadata |
| Async | migrate external HTTP calls to async clients where FastAPI path latency matters |
| Secrets | finish migration from `.env` to vault; encrypt conversation/memory at rest if needed |
| Observability | record provider used/cache hit/error in trace layers |
| Error model | use `Result` consistently instead of mixed strings/tuples |
| RAG | repair code RAG, isolate `repos/ayurstock`, add incremental indexing |
| CI | run `py_compile`, test harness/pytest, pip check, secret scan on commit |
| Docs | generate architecture docs from current code but redact secrets by design |

Overall assessment:

EDITH is an ambitious and fairly sophisticated local personal AI system with strong architectural instincts: local-first routing, multi-channel UX, persistent memory, scheduled maintenance, personas, tracing, feedback, and MCP extensibility. The main risk is not lack of features; it is control-plane hardening. The system has reached the point where import side effects, unauthenticated local control endpoints, duplicated execution paths, stale generated documentation, and missing automated tests are now the primary constraints on reliability and safety.
