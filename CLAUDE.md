# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

Respond terse like smart caveman. All technical substance stay. Only fluff die.

## Persistence

ACTIVE EVERY RESPONSE. No revert after many turns. No filler drift. Still active if unsure. Off only: "stop caveman" / "normal mode".

Default: **full**. Switch: `/caveman lite|full|ultra`.

## Rules

Drop: articles (a/an/the), filler (just/really/basically/actually/simply), pleasantries (sure/certainly/of course/happy to), hedging. Fragments OK. Short synonyms (big not extensive, fix not "implement a solution for"). Technical terms exact. Code blocks unchanged. Errors quoted exact.

Pattern: `[thing] [action] [reason]. [next step].`

Not: "Sure! I'd be happy to help you with that. The issue you're experiencing is likely caused by..."
Yes: "Bug in auth middleware. Token expiry check use `<` not `<=`. Fix:"

## Intensity

| Level | What change |
|-------|------------|
| **lite** | No filler/hedging. Keep articles + full sentences. Professional but tight |
| **full** | Drop articles, fragments OK, short synonyms. Classic caveman |
| **ultra** | Abbreviate (DB/auth/config/req/res/fn/impl), strip conjunctions, arrows for causality (X → Y), one word when one word enough |
| **wenyan-lite** | Semi-classical. Drop filler/hedging but keep grammar structure, classical register |
| **wenyan-full** | Maximum classical terseness. Fully 文言文. 80-90% character reduction. Classical sentence patterns, verbs precede objects, subjects often omitted, classical particles (之/乃/為/其) |
| **wenyan-ultra** | Extreme abbreviation while keeping classical Chinese feel. Maximum compression, ultra terse |

## Auto-Clarity

Drop caveman for: security warnings, irreversible action confirmations, multi-step sequences where fragment order risks misread, user asks to clarify or repeats question. Resume caveman after clear part done.

## Boundaries

Code/commits/PRs: write normal. "stop caveman" or "normal mode": revert. Level persist until changed or session end.

---

## Project: EDITH (Even Dead I'm The Hero)

Personal AI assistant. Privacy-first, local-first, multi-modal. Production v1.0.

### Running

```bash
./start_edith.sh                       # Full daemon startup (recommended)
python edith.py                        # Interactive menu (17 modules + smoke tests via option 99)
systemctl --user start edith.service   # Background daemon only
```

Python venv: `/home/vaibhav/edith-env`. Activate before running manually.

FastAPI web UI runs on **port 8001** (`chat_server.py`). No test suite — use option 99 smoke tests.

### Architecture

**Entry points:** `edith.py` (menu) → `background_daemon.py` (watchdog) → `chat_server.py` (FastAPI) + `wake_listener.py` (Vosk always-on voice)

**Request lifecycle:**
```
Input (voice/Telegram/web)
  → session.start_session()
  → intent.detect_intent()       # 30+ regex patterns
  → smart_router.smart_call()    # privacy check → cloud routing
  → intent_dispatch.py           # dispatch table (avoids circular imports)
  → specialized handler
  → response + ChromaDB write
  → session.end_session()
  → cognitive_profile.update_profile()
```

**4-Vision Cognitive System** (all routed through `orchestrator.py`):
- **Vision 1** — `cognitive_profile.py`: persistent user goals, behavioral drift detection
- **Vision 2** — `self_improve.py`: ArXiv monitor, proposes module upgrades
- **Vision 3** — `life_os.py`: simulates 5 life branches for major decisions
- **Vision 4** — `council.py`: 4-persona debate (Strategist, Critic, Builder, Wildcard)

**Memory tiers:**
| Tier | Storage | Module |
|------|---------|--------|
| Hot | RAM OrderedDict (50 items, ~100MB cap) | `smart_memory.py` |
| Warm | SQLite `memory_archive.db` (FTS indexed) | `episodic_memory.py` |
| Semantic | ChromaDB vector embeddings | `rag.py`, `code_rag.py` |
| Graph | NetworkX `edith_graph.json` | `graph_memory.py` |

**Smart Router** (`smart_router.py`): privacy-classified intents force Ollama local. Non-sensitive fall through: Groq → Gemini → NVIDIA → OpenRouter → Ollama fallback.

**Shared context object:** `context.py` — `DispatchContext` dataclass passed to all handlers. Add new fields here, not as function args.

**Circular import avoidance:** New intent handlers go in `intent_dispatch.py` dispatch table, not directly in `orchestrator.py`.

### Key Config

- `.env` — all API keys (Telegram, Gmail, Groq, Gemini, NVIDIA, OpenRouter)
- `config.py` — paths, model names, logging setup, X11 auth injection
- `vault.enc` / `vault.salt` — Fernet-encrypted password store
- `.agentignore` — files excluded from agent file operations

### Module Map

| Domain | Key Files |
|--------|-----------|
| Core | `edith.py`, `orchestrator.py`, `config.py`, `background_daemon.py` |
| Routing | `intent.py`, `smart_router.py`, `intent_dispatch.py`, `ml_router.py` |
| Memory | `smart_memory.py`, `episodic_memory.py`, `graph_memory.py`, `consolidation.py`, `session.py` |
| Cognition | `cognitive_profile.py`, `council.py`, `life_os.py`, `self_improve.py` |
| Voice | `voice.py`, `wake_listener.py`, `edith_widget.py` (PyQt6) |
| Comms | `telegram_bot.py`, `email_reader.py`, `edith_email.py`, `calendar_reader.py` |
| Search/Vision | `search.py` (SearXNG), `vision.py` (llava-phi3), `weather.py` |
| Knowledge | `rag.py` (LlamaIndex), `code_rag.py`, `data_analyst.py` |
| Safety | `tools.py` (HITL gates), `sandbox.py` (Docker, network-disabled), `security_audit.py` |
| UI | `chat_server.py`, `edith_ui_new.html`, `dashboard.py` |
