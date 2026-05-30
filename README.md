<div align="center">

# ⚡ EDITH

### *Even Dead I'm The Hero*

> A personal AI operating system. Not a chatbot. Not a wrapper. A daemon that knows your life.

![Python](https://img.shields.io/badge/Python-3.11-blue?style=flat-square&logo=python)
![FastAPI](https://img.shields.io/badge/FastAPI-async-green?style=flat-square&logo=fastapi)
![License](https://img.shields.io/badge/license-personal-red?style=flat-square)
![Status](https://img.shields.io/badge/status-active-brightgreen?style=flat-square)
![Platform](https://img.shields.io/badge/platform-Linux-lightgrey?style=flat-square&logo=linux)

> 🗂️ **50+ modules** • 🧠 **4-tier memory** • 🎙️ **3 TTS engines** • ⚡ **30+ intents** • 🔒 **zero GPU required**

**[Features](#-features) • [Architecture](#-architecture) • [Setup](#-setup--installation) • [API](#-api-endpoints) • [Memory](#-memory-system) • [Roadmap](#-roadmap)**

</div>

---

A personal AI operating system built by one developer, for one developer. Not a chatbot. Not a wrapper around ChatGPT. A full-stack AI daemon that runs on your hardware, knows your life, and gets smarter over time.

Built by Vaibhav Kashyap. Production v1.0.

---

## ⚡ Quick Start

```bash
git clone https://github.com/kashyapvaibhav10000-ai/EDITH ~/EDITH
cd ~/EDITH && cp .env.example .env   # add your API keys
./start.sh                           # EDITH boots on http://localhost:8001
```

> **First run?** You'll also need to [initialize the vault](#3-initialize-the-vault) and add your API keys before `./start.sh` will fully work.

---

## 🤔 What is EDITH

EDITH is a privacy-first, local-first AI assistant that runs as a background daemon on Linux. It handles voice commands, web search, email, calendar, phone control, file operations, code execution, and long-term memory — all through a single conversational interface.

The design philosophy: EDITH should feel like a brilliant friend who happens to know everything about your projects, your schedule, and your thinking patterns. Not a generic assistant that forgets you after every session.

**Key properties:**

- 🧠 **Persistent memory** across sessions — four-tier storage (RAM → SQLite → ChromaDB → graph)
- 🔒 **Privacy-classified routing** — sensitive intents (vault, shell, email) never leave your machine
- 🎙️ **Multi-modal** — voice in, voice out, screen vision, image generation
- 🔬 **Self-improving** — monitors ArXiv, proposes its own upgrades, tracks behavioral drift
- 💻 **No GPU required** — runs entirely on free-tier cloud LLM APIs with local Piper TTS

---

## 🏗️ Architecture

### Request Lifecycle

```
Input (voice / Telegram / web widget)
  │
  ├─ wake_listener.py     Vosk always-on wake word detection
  ├─ telegram_bot.py      Telegram message handler
  └─ chat_server.py       FastAPI web UI (port 8001)
         │
         ▼
  session.start_session()          Session tracking + device fingerprint
         │
         ▼
  intent.detect_intent()           30+ regex patterns → intent constant
         │
         ▼
  orchestrator.recall()            4-tier memory recall (RAM + SQLite + ChromaDB + graph)
         │
         ▼
  smart_router.smart_call()        Privacy check → cloud routing
         │
         ├─ PRIVATE intents ──────► Ollama (local, never leaves machine)
         └─ PUBLIC intents ───────► Groq → Gemini → NVIDIA → OpenRouter
                                    (first available, with cooldown + circuit breaker)
         │
         ▼
  intent_dispatch.dispatch()       Dispatch table → specialized handler
         │
         ├─ handlers/email.py
         ├─ handlers/shell.py
         ├─ handlers/calendar.py
         ├─ handlers/search.py
         ├─ handlers/phone.py
         ├─ handlers/memory_handler.py
         ├─ handlers/system.py
         ├─ handlers/mcp.py
         └─ handlers/misc.py       (vision, agent, council, image_gen, etc.)
         │
         ▼
  response + smart_memory.remember()   Write to hot RAM + cold SQLite
  graph_memory.extract_and_store()     Extract knowledge triples
  session.end_session()
  cognitive_profile.update_profile()   Behavioral drift tracking
```

### 🔀 LLM Routing Chain

```
smart_router.smart_call()
  │
  ├─ Privacy check: vault/shell/email → Ollama (local only)
  │
  └─ Cloud chain (first available):
       1. Groq          llama-3.3-70b-versatile       (limit: 150/day)
       2. Gemini        gemini-2.0-flash               (limit: 250/day)
       3. NVIDIA NIM    meta/llama-3.1-70b-instruct    (limit:  80/day)
       4. OpenRouter    meta-llama/llama-3.3-70b-instruct:free  (limit: 80/day)
       5. Ollama        local fallback (if configured)

Each provider has:
  - 60s cooldown on failure, up to 5 min max
  - Circuit breaker (CLOSED → OPEN → HALF_OPEN)
  - Per-provider latency tracking
```

### 🧠 4-Vision Cognitive System

All routed through `orchestrator.py`:

| Vision | Module | What it does |
|--------|--------|--------------|
| Vision 1 | `cognitive_profile.py` | Persistent user goals, behavioral drift detection, prime directive |
| Vision 2 | `self_improve.py` | ArXiv monitor, proposes module upgrades, tracks open loops |
| Vision 3 | `life_os.py` | Simulates 5 life branches for major decisions, weekly briefings |
| Vision 4 | `council.py` | 4-persona debate: Strategist, Critic, Builder, Wildcard |

---

## ✨ Features

### 💬 Conversation & Intelligence

- 🔄 Multi-turn conversation with full session memory
- 🔀 Compound intent detection — "check email and then tell me the weather" executes as a DAG
- 🧠 Context-aware responses using recalled memories injected into every prompt
- 📊 Behavioral drift detection — EDITH notices when your goals shift

### 🎙️ Voice

- 👂 Always-on wake word detection via Vosk (offline, no cloud)
- 🗣️ STT: Groq Whisper large-v3-turbo (fast) with local tiny.en fallback
- 🔊 TTS: Piper (offline, en_GB-cori-high voice) or Groq Orpheus or Chatterbox voice clone
- ⚡ Barge-in support — interrupt EDITH mid-sentence
- 🖥️ PyQt6 desktop widget with real-time waveform

### 🧠 Memory

- ⚡ Hot RAM cache (50 items, ~100MB cap) for instant recall
- 🗄️ SQLite archive with full-text search for long-term storage
- 🔍 ChromaDB vector embeddings for semantic similarity search
- 🕸️ NetworkX knowledge graph for entity relationships
- 📖 Episodic memory — remembers past conversation sessions
- 🔄 Automatic consolidation during idle periods

### 📋 Productivity

- 📧 Email: read inbox, check unread, compose (Gmail OAuth)
- 📅 Calendar: today's schedule, week view, create events (Google Calendar)
- 📱 Phone: KDE Connect battery, notifications, ring, SMS
- 💬 WhatsApp: send messages via bridge
- 🔎 Web search: SearXNG (self-hosted, privacy-preserving)
- 🌤️ Weather: current conditions with IST timezone awareness

### 🖥️ System & Files

- 🛡️ Shell command execution with HITL safety gates
- 📁 File operations: create, read, delete, query directory contents
- 🐳 Docker sandbox for untrusted code execution (network-disabled)
- 🔌 MCP (Model Context Protocol) server integration
- 👁️ Screen vision via llava-phi3 (analyze screenshots)
- 🎨 Image generation

### 🤖 Intelligence Tools

- 📚 RAG over personal notes (LlamaIndex + ChromaDB)
- 💻 Code RAG over your project files
- 📊 Data analysis: CSV/Excel with chart generation
- 🧬 Repo DNA: competitive intelligence — analyze GitHub repos, find steal-worthy patterns
- 🏛️ Council of Minds: 4-persona debate for complex decisions
- 🤖 Agent mode: multi-step task planning and execution

### 🔗 Integrations

- ✈️ Telegram bot (alerts, briefings, remote control)
- 🪝 Webhook receiver (GitHub, calendar, generic push events)
- 📲 KDE Connect (phone bridge)
- 📓 DevLog: automatic development journal with Simplenote sync

---

## 🛠️ Tech Stack

| Layer | Technology |
|-------|-----------|
| Web framework | FastAPI + uvicorn |
| LLM providers | Groq, Google Gemini, NVIDIA NIM, OpenRouter |
| Local LLM | Ollama (optional, for private intents) |
| STT | Groq Whisper / local Vosk / whisper.cpp |
| TTS | Piper (offline) / Groq Orpheus / Chatterbox |
| Vector DB | ChromaDB |
| Graph DB | NetworkX (JSON-persisted) |
| Relational DB | SQLite (sessions, memory archive, traces) |
| RAG | LlamaIndex |
| Desktop UI | PyQt6 |
| Search | SearXNG (self-hosted Docker) |
| Secrets | Fernet-encrypted vault (`vault.enc`) |
| Sandbox | Docker (network-disabled code execution) |
| Language | Python 3.11 |

---

## 📁 Project Structure

```
EDITH/
├── chat_server.py          FastAPI app factory (thin — all routes in routes/)
├── orchestrator.py         Core chat loop, memory recall, session management
├── intent_dispatch.py      Dispatch table — routes intents to handlers
├── intent.py               Intent detection (30+ regex patterns)
├── agent.py                Multi-step task planning and execution
├── background_daemon.py    Watchdog daemon (proactive checks, consolidation)
├── telegram_bot.py         Telegram bot handler
├── start.sh                Startup script (SearXNG + daemon + server)
│
├── core/                   Infrastructure
│   ├── config.py           Paths, model names, constants, logging
│   ├── errors.py           Result type (ok/error monad)
│   ├── vault.py            Fernet-encrypted secret store
│   ├── smart_router.py     4-tier LLM routing with circuit breakers
│   ├── provider_config.py  Per-provider model and rate-limit config
│   └── circuit_breaker.py  Per-provider circuit breaker state
│
├── memory/                 Memory subsystem
│   ├── smart_memory.py     Hot RAM + cold SQLite hybrid store
│   ├── graph_memory.py     NetworkX knowledge graph
│   ├── rag.py              LlamaIndex RAG over notes
│   └── code_rag.py         RAG over project source files
│
├── utils/                  Utility tools
│   ├── vision.py           Screenshot analysis (llava-phi3)
│   ├── image_gen.py        Image generation
│   ├── coding_style.py     Coding personality extraction
│   ├── security_audit.py   Codebase security scanner
│   └── tuner.py            LLM response quality tuner
│
├── routes/                 FastAPI route modules
│   ├── chat.py             POST /api/chat, POST /api/chat/stream
│   ├── dashboard.py        GET /dashboard, /api/status, /api/costs
│   ├── memory.py           GET /api/last-memory, /api/traces/recent
│   ├── logs.py             GET /api/logs/stream (SSE)
│   ├── health.py           GET /api/health-check, /api/phone, /api/weather-status
│   ├── mcp.py              /api/mcp/* (MCP server management)
│   ├── sessions.py         /api/sessions/*, /webhook/*, /tg_webhook
│   └── repo.py             /api/repo/* (Repo DNA endpoints)
│
├── handlers/               Intent handler modules
│   ├── email.py            email, unread_email
│   ├── shell.py            shell, create_file, delete_file, file_query
│   ├── calendar.py         calendar_today, calendar_week, calendar_create
│   ├── search.py           search, lookup, weather
│   ├── phone.py            call, sms, phone, whatsapp
│   ├── memory_handler.py   rag, profile, briefing
│   ├── system.py           wake, session_end, system_health
│   ├── mcp.py              mcp
│   ├── misc.py             vision, agent, council, image_gen, etc.
│   ├── meta.py             identity, compact, think_level, trace_toggle
│   ├── helpers.py          Shared extraction helpers
│   ├── local_exec.py       Local system/file op detection
│   └── pending_action.py   HITL confirmed action executor
│
├── middleware/             FastAPI middleware
│   ├── logging.py          Request/response logging
│   ├── rate_limit.py       Per-IP rate limiting
│   └── auth.py             API key authentication
│
├── tests/                  Test suite
│   ├── test_intent_dispatch.py   35 intent detection tests
│   └── test_voice_pipeline.py    Voice pipeline tests
│
├── voices/                 Piper TTS voice models
│   ├── en_GB-cori-high.onnx
│   └── en_US-lessac-medium.onnx
│
├── skills/                 Loadable skill modules
├── scripts/                Utility scripts
├── static/                 Web UI static assets
├── edith_ui_new.html       Main chat UI
├── edith_dashboard.html    System dashboard
└── .env.example            Environment variable template
```

---

## 🚀 Setup & Installation

### Hardware Requirements

| Component | Minimum | Recommended |
|-----------|---------|-------------|
| OS | Linux (Debian/Ubuntu) | Manjaro/Arch |
| RAM | **8GB** | 16GB |
| CPU | Any x86_64 | — |
| GPU | **Not required** | — |
| Disk | ~2.5GB | — |
| Microphone | Optional (voice mode) | Required for voice |
| Docker | Required (SearXNG + sandbox) | — |

> All LLM inference is cloud API. No GPU needed.

### 1. Clone and set up Python environment

```bash
git clone https://github.com/kashyapvaibhav10000-ai/EDITH ~/EDITH
cd ~/EDITH

python3.11 -m venv ~/edith-env
source ~/edith-env/bin/activate
pip install -r requirements.txt
```

For local hardware node (voice, PyQt6 widget):
```bash
pip install -r requirements-local.txt
```

### 2. Configure environment

```bash
cp .env.example .env
# Edit .env with your API keys — see Configuration section
```

### 3. Initialize the vault

EDITH stores sensitive secrets in a Fernet-encrypted vault (`vault.enc`). You must unlock it before first run:

```bash
source ~/edith-env/bin/activate
python vault.py unlock          # prompts for vault password
python vault.py set GROQ_API_KEY your_key_here
python vault.py set GEMINI_API_KEY your_key_here
python vault.py set TELEGRAM_BOT_TOKEN your_token_here
# ... add other keys
python vault.py list            # verify keys are stored
```

The vault password is never stored — you enter it at startup. On systemd deployments, set `VAULT_PASSWORD` in the service environment.

### 4. Start SearXNG (web search)

```bash
docker run -d --name searxng -p 8080:8080 searxng/searxng
```

### 5. Download voice models (optional, for offline TTS)

Piper models are already included in `voices/`. For Vosk wake word detection:

```bash
mkdir -p ~/EDITH/models
wget https://alphacephei.com/vosk/models/vosk-model-small-en-us-0.15.zip
unzip vosk-model-small-en-us-0.15.zip -d ~/EDITH/models/
```

---

## ⚙️ Configuration

All configuration lives in `.env`. Copy `.env.example` and fill in your values.

### Required Keys

| Key | Description |
|-----|-------------|
| `GROQ_API_KEY` | Groq API key (primary LLM provider — free tier) |
| `GEMINI_API_KEY` | Google Gemini API key (fallback) |
| `NVIDIA_API_KEY` | NVIDIA NIM API key (fallback) |
| `OPENROUTER_API_KEY` | OpenRouter API key (final fallback) |
| `TELEGRAM_BOT_TOKEN` | Telegram bot token for remote control and alerts |
| `BRIDGE_SECRET` | Shared secret between local and cloud nodes |

### Optional Keys

| Key | Description |
|-----|-------------|
| `GMAIL_SERVICE_ACCOUNT_JSON` | Path to Google service account JSON (email + calendar) |
| `KDE_DEVICE_ID` | KDE Connect device ID for phone integration |
| `WHATSAPP_PHONE_NUMBER` | WhatsApp number for messaging |
| `LOCAL_BRIDGE_URL` | URL of local hardware node (for cloud→local TTS) |
| `CLOUD_URL` | URL of cloud node (for local→cloud routing) |
| `MCP_ADMIN_TOKEN` | Admin token for MCP server mutation endpoints |
| `EDITH_WEBHOOK_TOKEN` | Token for webhook endpoint authentication |

### Voice Options

| Key | Default | Description |
|-----|---------|-------------|
| `USE_GROQ_TTS` | `true` | Use Groq Orpheus TTS (faster, cloud) |
| `USE_CHATTERBOX` | `false` | Use Chatterbox voice clone (friend.wav) |
| `PREFER_FAST_TTS` | `true` | Prefer speed over quality |

---

## ▶️ Starting EDITH

### Full startup (recommended)

```bash
./start.sh
```

This starts SearXNG (if not running), activates the venv, launches `background_daemon.py`, and keeps the process alive with cleanup on exit.

### Manual startup

```bash
source ~/edith-env/bin/activate

# Start background daemon (proactive checks, memory consolidation)
python background_daemon.py &

# Start web server
python chat_server.py
# → http://localhost:8001
```

### Systemd service

```bash
cp edith.service ~/.config/systemd/user/
systemctl --user enable edith
systemctl --user start edith
systemctl --user status edith
```

### Access

| Interface | URL |
|-----------|-----|
| 💬 Web UI | http://localhost:8001 |
| 📊 Dashboard | http://localhost:8001/dashboard |
| 📖 API docs | http://localhost:8001/docs |

---

## 🎙️ Voice Pipeline

```
Microphone
  │
  ▼
wake_listener.py          Vosk offline wake word detection
  │  (detects "hey edith" or configured trigger)
  ▼
voice.py                  Audio capture (PyAudio)
  │
  ▼
STT (Speech-to-Text)
  ├─ Primary:   Groq Whisper large-v3-turbo (cloud, ~300ms)
  └─ Fallback:  whisper.cpp tiny.en (local, ~800ms)
  │
  ▼
orchestrator.chat()       Full processing pipeline
  │
  ▼
TTS (Text-to-Speech)      Sentence-streaming (speaks while generating)
  ├─ Option 1:  Piper offline (en_GB-cori-high, ~50ms/sentence)
  ├─ Option 2:  Groq Orpheus TTS (cloud, natural prosody)
  └─ Option 3:  Chatterbox voice clone (friend.wav, opt-in)
  │
  ▼
aplay / PyAudio           Audio output
```

**Barge-in**: User can interrupt EDITH mid-sentence. `_barge_in_triggered` event stops current TTS and restarts the listen loop.

**Cross-process sync**: `CrossProcessEvent` uses both `threading.Event` and a file flag so the widget, daemon, and wake listener stay in sync across processes.

---

## 🌐 API Endpoints

### Chat

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/api/chat` | Send message, get JSON response |
| `POST` | `/api/chat/stream` | Send message, get SSE token stream |

Request body: `{"message": "your input", "session_id": "optional"}`

Stream events: `start` → `transcript` → `token` (repeated) → `done`

### Dashboard & Status

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/dashboard` | Web dashboard UI |
| `GET` | `/api/status` | System health, provider status, circuit breakers |
| `GET` | `/api/costs` | 7-day API call costs by provider |
| `GET` | `/api/provider-latencies` | Per-provider response times |
| `GET` | `/api/monitor_schedule` | Maintenance schedule and last run times |
| `GET` | `/api/stats` | System stats, active model, recent logs |

### Memory & Traces

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/last-memory` | Last 3 recalled memories |
| `GET` | `/api/traces/recent` | Last N routing traces |
| `POST` | `/api/feedback` | Tag a trace thumbs_up/thumbs_down |

### Health

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/health-check` | Full system validation report |
| `GET` | `/api/phone` | KDE Connect battery + last notification |
| `GET` | `/api/weather-status` | Current weather |

### MCP (Model Context Protocol)

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/mcp/status` | All MCP server statuses |
| `GET` | `/api/mcp/tools/{server}` | Tools available on a server |
| `POST` | `/api/mcp/call` | Call a tool (requires `X-Admin-Token`) |
| `GET` | `/api/mcp/config` | Full MCP config |
| `POST` | `/api/mcp/config/add` | Add/update a server |
| `POST` | `/api/mcp/config/toggle/{name}` | Enable/disable a server |

### Sessions

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/sessions` | All sessions grouped by day |
| `POST` | `/api/sessions/new` | Create a new session |
| `GET` | `/api/sessions/{id}/messages` | Full conversation history |

### Webhooks

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/webhook/{source}` | Push events (github, telegram, calendar, alert) |
| `POST` | `/tg_webhook` | Telegram Bot API webhook (cloud node only) |

### Repo DNA

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/api/repo/analyze` | Analyze a GitHub repo for steal-worthy patterns |
| `GET` | `/api/repo/analyses` | All cached analyses |
| `POST` | `/api/repo/compare` | Head-to-head comparison with EDITH |
| `POST` | `/api/repo/adapt-preview` | Preview code adaptation |
| `POST` | `/api/repo/adapt-confirm` | Execute adaptation via agent |
| `POST` | `/api/repo/self-audit` | Audit EDITH against her own CLAUDE.md |

---

## 🧠 Memory System

EDITH uses four memory tiers, all queried on every recall:

### Tier 1 — ⚡ Hot RAM (`smart_memory.py`)
- `OrderedDict` capped at 50 items / ~100MB
- Sub-millisecond recall
- Evicted to SQLite when full

### Tier 2 — 🗄️ Warm SQLite (`memory_archive.db`)
- Full-text search indexed
- Stores all memories that age out of RAM
- Also stores API usage, feedback, and cost tracking

### Tier 3 — 🔍 Semantic ChromaDB (`memory/rag.py`)
- Vector embeddings for similarity search
- Indexes personal notes directory
- Separate index for project source code (`memory/code_rag.py`)

### Tier 4 — 🕸️ Knowledge Graph (`memory/graph_memory.py`)
- NetworkX directed graph, persisted as `edith_graph.json`
- Triples extracted from every conversation (subject → relation → object)
- Queried by entity name with configurable depth
- Previously write-only — now wired into `recall()` (fixed May 2026)

### Recall Flow

```python
def recall(query, n=3):
    results = smart_memory.recall(query, n=n)   # Tier 1+2
    graph_facts = query_graph(query, depth=1)    # Tier 4
    if graph_facts:
        results.append({"value": f"[Graph facts]: {graph_facts}", "source": "graph"})
    if results:
        return results
    # Fallback: ChromaDB direct query (Tier 3)
    return collection.query(query_texts=[query], n_results=n)
```

Memory context is injected into every chat request via `DispatchContext.memory_context`.

---

## 🔒 Security

| Mechanism | Details |
|-----------|---------|
| 🔐 **Vault** | All API keys in `vault.enc` (Fernet encryption). Never plaintext in `.env` for production. Password required at startup. |
| 🛡️ **HITL gates** | Shell commands, file deletion, agent execution require explicit `YES` before running. |
| 🐳 **Sandbox** | Untrusted code runs in Docker with `--network none`. No internet, no host filesystem. |
| 🔒 **Privacy routing** | `vault`, `shell`, `email` intents → local Ollama only. Never sent to cloud. |
| 🎯 **Input scope** | Every input classified as `safe`, `action`, or `dangerous` before dispatch. |
| 🔑 **MCP admin token** | Mutation endpoints require `X-Admin-Token` header. |
| ⏱️ **Rate limiting** | Per-IP rate limiting middleware on all API endpoints. |
| 🌐 **CORS** | Configurable via `EDITH_ALLOWED_ORIGINS`. Defaults to localhost only. |

---

## 🔧 Development

### Running tests

```bash
source ~/edith-env/bin/activate
pytest tests/ -v
```

Current test coverage:
- `tests/test_intent_dispatch.py` — 35 intent detection tests
- `tests/test_voice_pipeline.py` — voice pipeline tests

### Smoke tests

```bash
bash smoke_test_standalone.sh
```

### Adding a new intent

1. Add regex pattern to `intent.py`
2. Add handler function to appropriate file in `handlers/`
3. Add entry to `INTENT_HANDLERS` dict in `intent_dispatch.py`
4. Add test case to `tests/test_intent_dispatch.py`

### Adding a new API endpoint

Create or extend a file in `routes/`, then include the router in `chat_server.py`:

```python
from routes.mymodule import router as mymodule_router
app.include_router(mymodule_router)
```

### Shared context

All handlers receive a `DispatchContext` dataclass (`context.py`). Add new fields there — not as function arguments — to keep the interface stable.

### Logging

```python
from config import get_logger
log = get_logger("my_module")
log.info("message")
```

Logs go to `logs/edith.log` and stream via `/api/logs/stream` (SSE).

### Code style

EDITH uses no linter config by default. The codebase is a solo project — consistency over convention. When in doubt, match the surrounding code.

---

## 🗺️ Roadmap

### Near-term
- [ ] 🔔 Proactive notifications — EDITH surfaces relevant memories without being asked
- [ ] 🔀 Better compound intent handling — parallel DAG execution for independent sub-tasks
- [ ] 🦙 Ollama integration for fully offline operation
- [ ] 📱 Mobile app (React Native) replacing the PyQt6 widget

### Memory
- [ ] ⚖️ Memory importance scoring — not all memories are equal
- [ ] 🔗 Cross-session entity resolution — "my project" means the same thing across sessions
- [ ] 📉 Forgetting curve — graceful decay of low-importance memories

### Voice
- [ ] ⚡ Streaming STT — start processing before the user finishes speaking
- [ ] 😊 Emotion detection from voice tone
- [ ] 👥 Multi-speaker diarization for meeting transcription

### Intelligence
- [ ] 📅 Longer planning horizon in agent mode (currently single-session)
- [ ] 🎯 Self-evaluation — EDITH rates her own responses and learns from low scores
- [ ] 🛒 Skill marketplace — share and install community-built skill modules

### Infrastructure
- [ ] 🧪 Proper test coverage (currently ~35 tests, need ~200)
- [ ] 🐳 Docker Compose for one-command full deployment
- [ ] 📈 Metrics dashboard (Prometheus + Grafana)

---

<div align="center">

*EDITH is a solo project. It's opinionated, occasionally rough around the edges, and built to solve real problems for one specific person. If it solves problems for you too, great.*

</div>
