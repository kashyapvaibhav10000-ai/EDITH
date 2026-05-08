# EDITH Memory Audit — 2026-05-05

Generated: 2026-05-05 ~22:30 IST. Read-only inspection. Nothing modified.

---

## 1. Smart Memory (RAM + SQLite)

| Item | Value |
|---|---|
| Module | `smart_memory.py` → `SmartMemoryManager` / `SmartMemory` |
| Backend | SQLite `memory_archive.db` (shared DB) |
| RAM cache | 0 items (cold — fresh process, LRU cleared) |
| RAM cap | 50 items max, 100MB cap |
| SQLite rows | **195** |
| DB size | 61 KB |
| Schema | `id / key / value / category / timestamp / created_at` |
| Key format | `exchange_{hash}` for conversation turns |
| Sample entries | `"Vaibhav said: open google. EDITH replied: ..."` |
| Orchestrator wired | YES — `remember()`, `recall()`, `cleanup_old()`, `get_stats()` |
| **Status** | **OK** |

---

## 2. Memory Archive (SQLite cold storage)

| Item | Value |
|---|---|
| File | `memory_archive.db` |
| Tables | `memories`, `api_usage`, `api_costs`, `feedback` |
| Total memories | **195** |
| Last entry | `exchange_4970943985493731545` — "open /home/vaibhav/edith" |

### API Usage Today (2026-05-05)

| Provider | Calls | Daily Limit |
|---|---|---|
| groq | 2 | 150 |
| serper | 2 | — |
| nvidia | 1 | 80 |
| gemini | 0 | 250 |
| openrouter | 0 | 80 |
| ollama | 0 | ∞ |
| exa | 0 | — |
| tavily | 0 | — |
| searxng | 0 | — |
| duckduckgo | 0 | — |

**Status: OK**

---

## 3. ChromaDB (vector embeddings)

| Item | Value |
|---|---|
| Path | `memory_db/` (canonical) |
| Client | `chromadb.PersistentClient` via `config.get_chroma_client()` |
| Total embeddings | **110** across 10 collections |

### Collections

| Collection | Embeddings | Notes |
|---|---|---|
| `edith_memory` | **87** | Primary conversation memory |
| `edith_query_log` | 14 | User query history |
| `edith_open_loops` | 3 | Unresolved tasks/loops |
| `edith_episodic` | 1 | Thin — single test session |
| `edith_user_profile` | 1 | Minimal profile data |
| `edith_codebase` | **0** | EMPTY — code RAG never indexed |
| `persona_builder` | 1 | Council persona |
| `persona_strategist` | 1 | Council persona |
| `persona_critic` | 1 | Council persona |
| `persona_wildcard` | 1 | Council persona |

### Issues
- `edith_codebase` = 0 embeddings. `code_rag.py` never ran indexing on EDITH's own source.
- `edith_episodic` = 1 (test data only). Real sessions not producing episode saves.
- Persona collections each have only 1 embedding — not growing with usage.

**Status: WARN**

---

## 4. Cognitive Profile

| Item | Value |
|---|---|
| Module | `cognitive_profile.py` (module-level functions, no class) |
| Backend | ChromaDB `edith_user_profile` + `edith_query_log` collections |
| PRIME DIRECTIVE | `"Test directive 139623240181264"` — **placeholder, not real** |
| Recent queries | 5 stored, all `"test query"` — test data only |
| Drift score | **1.0** (maximum — profile nearly empty) |
| Orchestrator wired | YES — `get_prime_directive()`, `detect_drift()`, `get_full_profile()` |

### Issues
- PRIME DIRECTIVE is a test string. Should be set to actual user intent/goals.
- Query log filled with test data — not real usage queries.
- Drift = 1.0 is consequence of empty profile; self-resolves with actual use.

**Status: WARN — set real PRIME DIRECTIVE**

---

## 5. Session State (SQLite)

| Item | Value |
|---|---|
| File | `session_state.db` |
| Tables | `sessions` |
| Total sessions | **9** |
| Last 3 sessions | All device=`test`, status=`active`, 0 turns, Apr 24 2026 |
| Real sessions | 0 — all entries are test fixtures |

**Status: WARN — no real sessions recorded**

---

## 6. Episodic Memory

| Item | Value |
|---|---|
| Module | `episodic_memory.py` (module-level functions) |
| Backend | ChromaDB `edith_episodic` collection |
| Episode count | **1** |
| Only episode | `test_001` — 2026-04-08, summary: "User debugged Python, researched ML..." |
| Orchestrator wired | Partial — `recall_episodes()` imported; save path unclear |

### Issues
- Only 1 episode, and it's a test fixture from Apr 8.
- Real conversations not being saved as episodes.
- `save_episode()` likely never called from orchestrator after sessions end.

**Status: WARN — episode save path broken or never triggered**

---

## 7. Graph Memory

| Item | Value |
|---|---|
| Module | `graph_memory.py` (module-level functions) |
| Backend | NetworkX DiGraph → `memory_db/edith_graph.json` |
| Nodes | **11** |
| Edges | **10** |
| Top entities | `vaibhav(4)`, `edith(4)`, `ayurstock(3)`, `groq(2)`, `faster-whisper(1)` |
| Orchestrator wired | **NO** — not imported in `orchestrator.py` |

### Sample graph nodes
- vaibhav, edith, ayurstock, faster-whisper, piper tts

### Issues
- Graph not wired to orchestrator. Updates only from explicit calls or manual triggers.
- 11 nodes is minimal — `extract_and_store_triples()` not running on conversations.

**Status: INFO — orphaned from main loop**

---

## 8. Orchestrator Memory Wiring Map

```
orchestrator.py
├── SmartMemoryManager          ✅ WIRED — remember/recall/cleanup/stats
├── cognitive_profile           ✅ WIRED — prime_directive/detect_drift/full_profile
├── episodic_memory             ⚠️  PARTIAL — recall_episodes() only; save not confirmed
├── graph_memory                ❌ NOT IMPORTED — orphaned
└── ChromaDB                   ✅ INDIRECT — via episodic/cognitive/rag modules
```

---

## Summary Table

| System | Records | Status | Issue |
|---|---|---|---|
| SmartMemory (RAM) | 0 cached | OK | Cold cache (fresh process) |
| SmartMemory (SQLite) | 195 rows | OK | — |
| ChromaDB total | 110 embeddings | WARN | `edith_codebase`=0, episodic thin |
| Cognitive Profile | 1 profile | WARN | PRIME DIRECTIVE = test placeholder |
| Session State | 9 sessions | WARN | All test fixtures, no real sessions |
| Episodic Memory | 1 episode | WARN | Real sessions not producing episodes |
| Graph Memory | 11 nodes | INFO | Not wired to orchestrator |

---

## Priority Fix List

| # | Issue | Action |
|---|---|---|
| 1 | PRIME DIRECTIVE is placeholder | Run `python3 -c "from cognitive_profile import set_prime_directive; set_prime_directive('YOUR DIRECTIVE')"` |
| 2 | `edith_codebase` empty | Run `code_rag.py` indexing: `from code_rag import index_codebase; index_codebase()` |
| 3 | Episodes not saving | Audit `session.py` end-of-session hook — confirm `save_episode()` called |
| 4 | Graph not wired | Import `graph_memory.extract_and_store_triples` in orchestrator, call on each response |
| 5 | Session state all test | Not a bug — real sessions will populate over time |
