# EDITH Module Index

| Module | Purpose |
|--------|---------|
| agent.py | State machine execution loop for multi-step agentic tasks with SQLite persistence |
| background_daemon.py | Watchdog daemon managing FastAPI + WakeListener subprocesses with nightly maintenance |
| calendar_reader.py | Google Calendar integration — read events and create new entries via OAuth |
| chat_server.py | FastAPI web server — primary EDITH interface on port 8000 with streaming and voice endpoints |
| chatterbox_worker.py | Subprocess worker for Chatterbox TTS — isolated process reading JSON from stdin |
| circuit_breaker.py | Per-service circuit breaker (CLOSED/OPEN/HALF_OPEN) for Ollama, SearXNG, cloud providers |
| cleanup.py | ChromaDB memory cleanup — prunes stale/duplicate embeddings from memory collection |
| code_rag.py | Code-aware RAG — indexes Python/JS codebase into ChromaDB for semantic code search |
| coding_style.py | Extracts personal coding style from git repos and answers questions in that style |
| cognitive_profile.py | Vision 1 — persistent user model tracking goals, patterns, behavioral drift |
| compound_dag.py | Detects multi-step compound intents and executes sub-tasks in DAG topological order |
| config.py | Single source of truth for all paths, model names, constants, and shared utilities |
| consolidation.py | Memory consolidation "dream state" — merges redundant ChromaDB observations during idle time |
| context.py | Shared DispatchContext dataclass passed to all intent handlers — eliminates circular imports |
| conversation_dna.py | Shapes response style based on time-of-day, device, session length, and detected emotion |
| council.py | Vision 4 — 4-persona debate (Strategist/Critic/Builder/Wildcard) for complex decisions |
| dashboard.py | Legacy FastAPI dashboard server (backward compat) — primary server is chat_server.py |
| data_analyst.py | Pandas-powered file analysis with matplotlib chart generation and AI insights |
| db_pool.py | Thread-safe SQLite connection pool with WAL mode — one pool per DB path |
| devlog.py | Developer changelog — logs changes/reasons/status, syncs to Simplenote and Telegram |
| edith_arch_updater.py | Boot script that AST-scans codebase and pushes architecture diagram to Joplin note |
| edith_email.py | Gmail compose/send via OAuth — AI-assisted email drafting with user confirmation |
| edith.py | Interactive CLI menu — entry point for manual module launch and smoke tests |
| edith_scanner.py | Standalone flow scanner — AST-scans all .py files and generates HTML visualization |
| edith_widget.py | PyQt6 system tray widget with floating chat overlay and hotkey activation |
| email_reader.py | IMAP email reader with AI summarization — inbox check via imapclient |
| episodic_memory.py | Stores full session conversations as episodes in ChromaDB for contextual recall |
| errors.py | Shared Result dataclass — typed OK/error return pattern used across all modules |
| event_bus.py | In-process pub/sub event bus — backbone for decoupled module communication |
| feedback_tagger.py | Links 👍👎 feedback to trace entries — feeds routing/model tuner |
| graph_memory.py | Knowledge graph (GraphRAG) using NetworkX — entity-relationship extraction from conversations |
| image_gen.py | AI image generation via Pollinations.ai API with Qwen prompt enhancement |
| intent_dispatch.py | Central dispatch table — maps intents to handlers, no circular imports, no elif chains |
| intent.py | Intent detection — 30+ regex patterns + optional ML classifier fallback |
| life_os.py | Vision 3 — simulates 5 decision branches for major life choices, tracks open loops |
| mcp_bridge.py | Persistent subprocess pool for MCP servers — JSON-RPC 2.0 over stdio |
| migrate_secrets_to_vault.py | One-shot migration script — moves .env secrets into Fernet-encrypted vault |
| ml_router.py | Emotion/urgency detection and response style routing based on query tone |
| model_manager.py | Ollama model lifecycle — switch, pre-warm, per-intent override, list loaded models |
| monitor.py | Proactive system monitoring — disk, RAM, CPU, phone battery, weather, break reminders |
| ocr.py | Tesseract OCR wrapper — extract text from images, screenshots, or clipboard |
| orchestrator.py | Core request handler — glues intent dispatch, memory, history, and all specialized modules |
| patch_devpanel.py | One-shot script to patch devpanel endpoints into dashboard.py (with backup) |
| phone.py | KDE Connect integration — SMS, ring, notifications, battery, file share, calls |
| proactive.py | Event-driven Telegram alerts — subscribes to event_bus, rate-limited push notifications |
| rag.py | LlamaIndex RAG over notes directory — semantic search and Q&A on personal documents |
| sandbox.py | Docker-based code sandbox — runs untrusted code with network disabled and resource limits |
| search.py | Multi-provider web search with daily quota tracking — SearXNG/Serper/Exa/Tavily/DDG |
| security_audit.py | System security audit — checks file permissions, open ports, exposed secrets |
| self_improve.py | Vision 2 — monitors ArXiv, proposes module upgrades, pushes proposals via event_bus |
| session.py | Session manager — start/end rituals tying all 4 Visions together with device tracking |
| shared_state.py | Shared OrderedDict conversation history to prevent circular imports between chat_server and voice |
| skills_loader.py | Loads SKILL.md files from skills/ directory — inject skill context into matching intents |
| smart_memory.py | Hot RAM + cold SQLite memory — constant ~100MB RAM with infinite cold storage |
| smart_router.py | 4-tier privacy-aware AI routing: Groq → Gemini → NVIDIA → OpenRouter → Ollama fallback |
| telegram_bot.py | Telegram bot — full EDITH terminal over Telegram with weekly briefings and drift alerts |
| test_harness.py | 20 pre-written smoke test scenarios covering intent, memory, council, search, and more |
| tools.py | Human-in-the-loop (HITL) file and shell operations — confirm before destructive actions |
| trace_logger.py | Per-request trace logging — records intent, routing layers, latency, and feedback to SQLite |
| tuner.py | Weekly routing tuner — adjusts provider weights based on feedback/latency data |
| validator.py | System health validator — checks network, Ollama, phone, calendar, disk, memory, vision, TTS |
| vault.py | Fernet-encrypted password/secret store with Argon2 KDF and file permission hardening |
| video_summarizer.py | YouTube video summarizer — download audio, Whisper transcribe, LLM summarize |
| vision.py | Image analysis via llava-phi3 (local) with cloud fallback — screenshots and photo analysis |
| voice.py | STT (Whisper/Groq/Sarvam) + TTS (Piper/Groq Orpheus/Chatterbox) with language detection |
| wake_listener.py | Always-on Vosk wake-word listener — detects "Hey EDITH" and triggers voice session |
| weather.py | Current weather via Open-Meteo API with automatic location detection |
| whatsapp.py | WhatsApp integration via whatsapp-bot Node.js subprocess (whatsapp-web.js) |
