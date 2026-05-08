# EDITH Obsidian Vault Structure

---

## 1. Folder Structure

```
EDITH/
├── 00 - Index/
│   └── EDITH Home
├── 01 - Architecture/
│   ├── System Overview
│   ├── Request Lifecycle
│   ├── Entry Points
│   └── Circular Import Rules
├── 02 - Voice Pipeline/
│   ├── Voice Overview
│   ├── Wake Listener
│   ├── STT Engine (Whisper)
│   └── TTS Output
├── 03 - Memory System/
│   ├── Memory Overview
│   ├── Hot Memory (RAM)
│   ├── Warm Memory (SQLite)
│   ├── Semantic Memory (ChromaDB)
│   └── Graph Memory (NetworkX)
├── 04 - Agent System/
│   ├── Agent Overview
│   ├── Smart Router
│   ├── Intent Engine
│   ├── Intent Dispatch
│   └── ML Router
├── 05 - Cognition/
│   ├── Cognition Overview
│   ├── Cognitive Profile
│   ├── Council (4 Personas)
│   ├── Life OS (5 Branches)
│   └── Self Improve (ArXiv)
├── 06 - Execution Layer/
│   ├── Execution Overview
│   ├── Orchestrator
│   ├── Tools (HITL)
│   ├── Sandbox (Docker)
│   └── Dispatch Context
├── 07 - Comms/
│   ├── Telegram Bot
│   ├── Email Reader
│   ├── Calendar Reader
│   └── Search (SearXNG)
├── 08 - Dev Logs/
│   ├── Devlog Index
│   └── [YYYY-MM-DD] Session
├── 09 - System Gaps/
│   ├── Gaps Index
│   └── [Gap Name]
└── 10 - Roadmap/
    ├── Roadmap Index
    ├── Active Sprint
    └── Backlog
```

---

## 2. Notes (Full Spec)

---

### `00 - Index/EDITH Home`
**Purpose:** Master entry node. All roads start here.

**Key sections:**
- What is EDITH
- System status (link per subsystem)
- Quick nav

**Links:**
```
[[System Overview]]
[[Request Lifecycle]]
[[Memory Overview]]
[[Agent Overview]]
[[Voice Overview]]
[[Cognition Overview]]
[[Execution Overview]]
[[Roadmap Index]]
[[Gaps Index]]
[[Devlog Index]]
```

---

### `01 - Architecture/System Overview`
**Purpose:** Bird's-eye of all modules. No deep dives here — only links.

**Key sections:**
- Entry points (edith.py, background_daemon.py, chat_server.py)
- Module domains (routing, memory, cognition, comms, execution)
- Config files (.env, config.py, vault.enc)

**Links:**
```
[[Entry Points]]
[[Request Lifecycle]]
[[Smart Router]]
[[Memory Overview]]
[[Cognition Overview]]
[[Circular Import Rules]]
[[Dispatch Context]]
```

---

### `01 - Architecture/Request Lifecycle`
**Purpose:** Trace single request from input → response. Reference doc for debugging.

**Key sections:**
- Input sources (voice / Telegram / web)
- session.start_session()
- intent.detect_intent() — 30+ regex patterns
- smart_router.smart_call() — privacy check → cloud routing
- intent_dispatch.py — dispatch table
- ChromaDB write + cognitive_profile.update_profile()

**Links:**
```
[[Intent Engine]]
[[Smart Router]]
[[Intent Dispatch]]
[[Semantic Memory (ChromaDB)]]
[[Cognitive Profile]]
[[Dispatch Context]]
[[Session]]
```

---

### `01 - Architecture/Entry Points`
**Purpose:** Document all valid boot paths.

**Key sections:**
- `edith.py` → interactive menu (17 modules, option 99 = smoke tests)
- `background_daemon.py` → watchdog
- `chat_server.py` → FastAPI port 8000
- `wake_listener.py` → Vosk always-on voice
- `start_edith.sh` → full startup

**Links:**
```
[[System Overview]]
[[Wake Listener]]
[[Voice Overview]]
```

---

### `01 - Architecture/Circular Import Rules`
**Purpose:** Prevent re-introducing circular import bugs.

**Key sections:**
- Rule: new intent handlers → `intent_dispatch.py` only, not `orchestrator.py`
- Dispatch table pattern
- Known past violations

**Links:**
```
[[Intent Dispatch]]
[[Orchestrator]]
```

---

### `02 - Voice Pipeline/Voice Overview`
**Purpose:** Full voice stack, start to finish.

**Key sections:**
- Always-on wake detection
- STT → intent → response → TTS
- Failure modes (VAD false positives, Whisper timeout)

**Links:**
```
[[Wake Listener]]
[[STT Engine (Whisper)]]
[[TTS Output]]
[[Intent Engine]]
[[Entry Points]]
```

---

### `02 - Voice Pipeline/Wake Listener`
**Purpose:** Document Vosk-based always-on detection.

**Key sections:**
- Model used, sample rate, threshold
- Trigger phrases
- CPU cost baseline
- Edge cases (background noise, partial match)

**Links:**
```
[[Voice Overview]]
[[STT Engine (Whisper)]]
```

---

### `02 - Voice Pipeline/STT Engine (Whisper)`
**Purpose:** Whisper.cpp integration spec.

**Key sections:**
- Model size used (tiny/base/small?)
- Invocation path from voice.py
- Latency target
- GPU vs CPU path

**Links:**
```
[[Wake Listener]]
[[Voice Overview]]
[[TTS Output]]
```

---

### `02 - Voice Pipeline/TTS Output`
**Purpose:** Text-to-speech output layer.

**Key sections:**
- Engine used
- Voice profile config
- Async vs blocking call
- Widget integration (edith_widget.py)

**Links:**
```
[[Voice Overview]]
[[STT Engine (Whisper)]]
```

---

### `03 - Memory System/Memory Overview`
**Purpose:** All 4 tiers at a glance. Decision logic for which tier to read/write.

**Key sections:**
- Tier table (Hot → Warm → Semantic → Graph)
- Write path logic
- Read fallback order
- Consolidation trigger

**Links:**
```
[[Hot Memory (RAM)]]
[[Warm Memory (SQLite)]]
[[Semantic Memory (ChromaDB)]]
[[Graph Memory (NetworkX)]]
[[Request Lifecycle]]
```

---

### `03 - Memory System/Hot Memory (RAM)`
**Purpose:** Spec for `smart_memory.py` in-process cache.

**Key sections:**
- OrderedDict, 50 item cap, ~100MB
- Eviction policy
- TTL? Or LRU?
- Invalidation on session end

**Links:**
```
[[Memory Overview]]
[[Warm Memory (SQLite)]]
[[Session]]
```

---

### `03 - Memory System/Warm Memory (SQLite)`
**Purpose:** Spec for `episodic_memory.py` persistent store.

**Key sections:**
- DB path: `memory_archive.db`
- FTS indexed columns
- Schema
- Query patterns
- WAL mode (db-wal, db-shm files present)

**Links:**
```
[[Memory Overview]]
[[Hot Memory (RAM)]]
[[Semantic Memory (ChromaDB)]]
```

---

### `03 - Memory System/Semantic Memory (ChromaDB)`
**Purpose:** Vector embedding store via `rag.py` and `code_rag.py`.

**Key sections:**
- LlamaIndex integration
- Embedding model
- Collection names
- Write trigger (after each response)
- RAG query flow

**Links:**
```
[[Memory Overview]]
[[Graph Memory (NetworkX)]]
[[Request Lifecycle]]
```

---

### `03 - Memory System/Graph Memory (NetworkX)`
**Purpose:** Relationship graph via `graph_memory.py`.

**Key sections:**
- File: `edith_graph.json`
- Node types (person, concept, event, module)
- Edge types (relates_to, caused_by, depends_on)
- When written vs queried

**Links:**
```
[[Memory Overview]]
[[Semantic Memory (ChromaDB)]]
[[Cognitive Profile]]
```

---

### `04 - Agent System/Agent Overview`
**Purpose:** Routing + intent stack overview. How EDITH decides what to do.

**Key sections:**
- Intent → router → dispatch chain
- Privacy classification flow
- Provider fallback chain (Groq → Gemini → NVIDIA → OpenRouter → Ollama)

**Links:**
```
[[Intent Engine]]
[[Smart Router]]
[[Intent Dispatch]]
[[ML Router]]
[[Request Lifecycle]]
```

---

### `04 - Agent System/Smart Router`
**Purpose:** Provider selection logic in `smart_router.py`.

**Key sections:**
- Privacy-classified intents → force Ollama
- Groq bias for short queries
- Per-provider latency tracking
- Fallback chain

**Links:**
```
[[Agent Overview]]
[[Intent Engine]]
[[ML Router]]
```

---

### `04 - Agent System/Intent Engine`
**Purpose:** Pattern matching in `intent.py`.

**Key sections:**
- 30+ regex patterns
- Pattern categories
- Adding new intents (link to Circular Import Rules)
- Edge case: ambiguous match

**Links:**
```
[[Agent Overview]]
[[Intent Dispatch]]
[[Smart Router]]
[[Circular Import Rules]]
```

---

### `04 - Agent System/Intent Dispatch`
**Purpose:** Dispatch table in `intent_dispatch.py`. Single source of handler routing.

**Key sections:**
- Table structure (intent_key → handler_fn)
- How to add new handler
- `DispatchContext` passing

**Links:**
```
[[Intent Engine]]
[[Dispatch Context]]
[[Circular Import Rules]]
[[Orchestrator]]
```

---

### `04 - Agent System/ML Router`
**Purpose:** ML-based routing in `ml_router.py` (vs regex).

**Key sections:**
- When ML router fires vs intent engine
- Model used
- Training data source
- Confidence threshold

**Links:**
```
[[Smart Router]]
[[Agent Overview]]
```

---

### `05 - Cognition/Cognition Overview`
**Purpose:** 4-Vision system map. Routed through `orchestrator.py`.

**Key sections:**
- Vision 1: Cognitive Profile
- Vision 2: Self Improve
- Vision 3: Life OS
- Vision 4: Council
- Orchestrator as coordinator

**Links:**
```
[[Orchestrator]]
[[Cognitive Profile]]
[[Self Improve (ArXiv)]]
[[Life OS (5 Branches)]]
[[Council (4 Personas)]]
```

---

### `05 - Cognition/Cognitive Profile`
**Purpose:** `cognitive_profile.py` — persistent user model.

**Key sections:**
- Persistent goals
- Behavioral drift detection
- Update trigger (end of session)
- Fields tracked

**Links:**
```
[[Cognition Overview]]
[[Graph Memory (NetworkX)]]
[[Request Lifecycle]]
```

---

### `05 - Cognition/Council (4 Personas)`
**Purpose:** `council.py` — multi-persona deliberation.

**Key sections:**
- Strategist, Critic, Builder, Wildcard
- Trigger condition (complex/ambiguous requests)
- Debate format
- Output structure

**Links:**
```
[[Cognition Overview]]
[[Life OS (5 Branches)]]
[[Orchestrator]]
```

---

### `05 - Cognition/Life OS (5 Branches)`
**Purpose:** `life_os.py` — simulate decision branches.

**Key sections:**
- 5 life branch simulation
- Input: major decision context
- Output: branch comparison
- When to invoke

**Links:**
```
[[Cognition Overview]]
[[Council (4 Personas)]]
```

---

### `05 - Cognition/Self Improve (ArXiv)`
**Purpose:** `self_improve.py` — autonomous upgrade proposals.

**Key sections:**
- ArXiv scan frequency
- Relevance filter (AI/agents/memory)
- Event bus push path
- Telegram notification trigger

**Links:**
```
[[Cognition Overview]]
[[Telegram Bot]]
[[Event Bus]]
```

---

### `06 - Execution Layer/Execution Overview`
**Purpose:** How EDITH executes real actions safely.

**Key sections:**
- HITL gates (tools.py)
- Docker sandbox (network-disabled)
- Approved action categories
- Blocked action categories

**Links:**
```
[[Orchestrator]]
[[Tools (HITL)]]
[[Sandbox (Docker)]]
[[Dispatch Context]]
```

---

### `06 - Execution Layer/Orchestrator`
**Purpose:** `orchestrator.py` — central coordinator.

**Key sections:**
- Receives from intent_dispatch
- Coordinates 4-Vision calls
- Does NOT hold handler logic (circular import rule)

**Links:**
```
[[Execution Overview]]
[[Cognition Overview]]
[[Intent Dispatch]]
[[Circular Import Rules]]
```

---

### `06 - Execution Layer/Tools (HITL)`
**Purpose:** Human-in-the-loop gates in `tools.py`.

**Key sections:**
- Which actions require confirmation
- Approval flow
- Timeout behavior
- Bypass conditions (none — by design)

**Links:**
```
[[Execution Overview]]
[[Sandbox (Docker)]]
```

---

### `06 - Execution Layer/Sandbox (Docker)`
**Purpose:** `sandbox.py` — isolated execution.

**Key sections:**
- Network disabled
- Volume mounts
- Timeout
- Cleanup on exit

**Links:**
```
[[Execution Overview]]
[[Tools (HITL)]]
```

---

### `06 - Execution Layer/Dispatch Context`
**Purpose:** `context.py` — shared state object passed to all handlers.

**Key sections:**
- `DispatchContext` dataclass fields
- Rule: add new fields here, not as fn args
- Lifetime (per request)

**Links:**
```
[[Intent Dispatch]]
[[Orchestrator]]
[[Request Lifecycle]]
```

---

### `07 - Comms/Telegram Bot`
**Purpose:** `telegram_bot.py` — inbound/outbound Telegram.

**Key sections:**
- Inbound message → intent pipeline
- Outbound push (self_improve notifications)
- Auth (token in vault)
- Command list

**Links:**
```
[[Agent Overview]]
[[Self Improve (ArXiv)]]
[[Smart Router]]
```

---

### `07 - Comms/Email Reader`
**Purpose:** `email_reader.py` + `edith_email.py` — Gmail integration.

**Key sections:**
- OAuth flow (token.json / credentials.json — never commit)
- Prefetch on startup
- Summarization path
- Label/filter logic

**Links:**
```
[[Calendar Reader]]
[[Smart Router]]
```

---

### `07 - Comms/Calendar Reader`
**Purpose:** `calendar_reader.py` — Google Calendar.

**Key sections:**
- OAuth (shared token with email)
- Tomorrow prefetch
- Event → intent trigger
- Reminder logic

**Links:**
```
[[Email Reader]]
[[Smart Router]]
```

---

### `07 - Comms/Search (SearXNG)`
**Purpose:** `search.py` — privacy-first web search.

**Key sections:**
- SearXNG config location (`searxng-config/`)
- Query → result → summarize path
- Privacy: no external tracking
- Fallback if SearXNG down

**Links:**
```
[[Agent Overview]]
[[Smart Router]]
```

---

### `08 - Dev Logs/Devlog Index`
**Purpose:** Index of all dev sessions. Chronological log of changes.

**Key sections:**
- Table: date | focus area | key changes
- Link to each session note

**Links:**
```
[[EDITH Home]]
[[Gaps Index]]
[[Roadmap Index]]
```

---

### `08 - Dev Logs/[YYYY-MM-DD] Session`
**Purpose:** Single session record.

**Key sections:**
- What changed
- What broke
- Decision log (why X over Y)
- Open threads → link to gap notes

**Links:**
```
[[Devlog Index]]
[[Gaps Index]]
[[Active Sprint]]
```

---

### `09 - System Gaps/Gaps Index`
**Purpose:** Known weaknesses, missing features, tech debt.

**Key sections:**
- Table: gap | severity | module | linked note
- Status: open / in progress / resolved

**Links:**
```
[[EDITH Home]]
[[Roadmap Index]]
[[Devlog Index]]
```

---

### `09 - System Gaps/[Gap Name]`
**Purpose:** Single gap, atomic.

**Key sections:**
- Symptom
- Root cause (if known)
- Affected modules
- Proposed fix
- Priority

**Links:**
```
[[Gaps Index]]
[[Active Sprint]]
[[Backlog]]
```

---

### `10 - Roadmap/Roadmap Index`
**Purpose:** Strategic view of where EDITH goes.

**Key sections:**
- Vision statement
- Milestones (v1.0 done, v1.x, v2.0)
- Link to Active Sprint + Backlog

**Links:**
```
[[EDITH Home]]
[[Active Sprint]]
[[Backlog]]
[[Gaps Index]]
```

---

### `10 - Roadmap/Active Sprint`
**Purpose:** Current work items. Refreshed each sprint.

**Key sections:**
- Sprint goal
- Items (checklist)
- Blocked items → link to gap notes

**Links:**
```
[[Roadmap Index]]
[[Backlog]]
[[Gaps Index]]
[[Devlog Index]]
```

---

### `10 - Roadmap/Backlog`
**Purpose:** Unscheduled future work.

**Key sections:**
- Feature ideas
- Refactor candidates
- Research items (ArXiv links)

**Links:**
```
[[Roadmap Index]]
[[Active Sprint]]
[[Self Improve (ArXiv)]]
```

---

## Graph Density Notes

- Every note links minimum 3 others
- `EDITH Home` = master hub
- `Request Lifecycle` + `Memory Overview` + `Agent Overview` = secondary hubs
- Cognition notes cluster tightly around `Orchestrator`
- Gap notes always connect up to roadmap, sideways to modules
