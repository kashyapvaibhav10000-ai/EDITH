# EDITH Personal AI - Project Assessment

**Project:** EDITH (Even Dead I'm The Hero)  
**Type:** Personal AI Assistant with Multi-Modal Capabilities  
**Owner:** Vaibhav Kashyap  
**Assessment Date:** 2026-04-30  
**Status:** Production v1.0 (operational with known issues)

---

## Executive Summary

EDITH is a sophisticated personal AI assistant with innovative 4-Vision cognitive architecture, privacy-first design, and comprehensive integrations (voice, email, Telegram, web). The system is operational with 44/44 tests passing, though multiple critical issues require attention. Security audit identified 3 critical vulnerabilities, and SYSTEM_AUDIT flagged several operational warnings.

---

## Strengths

### Architecture & Design
- **Innovative 4-Vision Cognitive System** — Unique architecture combining cognitive profiling, self-improvement via ArXiv monitoring, life decision simulations (5 branches), and multi-persona debate (Council of Minds)
- **Privacy-First Routing** — LOCAL_ONLY_INTENTS forced to Ollama (air-gapped), cloud providers filtered by sensitivity
- **Hybrid Memory Architecture** — 4-tier system: Hot RAM (50 items) → Warm SQLite → Semantic ChromaDB → Graph knowledge
- **Graceful Provider Fallbacks** — 4-tier chain (Groq → Gemini → NVIDIA → OpenRouter → Ollama) with circuit breakers
- **HITL Safety Gates** — Human confirmation required for destructive operations (file/shell/code execution)
- **Clean systemd Deployment** — edith.service + edith-widget.service with auto-restart

### Integration Coverage
- Voice: Whisper.cpp STT + Piper TTS + Vosk wake word + Chatterbox (upgrading)
- Communication: Telegram Bot (24/7), Gmail IMAP, Google Calendar OAuth, KDE Connect SMS
- Knowledge: LlamaIndex RAG, Code RAG (AST parsing), Graph memory (NetworkX)
- External APIs: SearXNG, Open-Meteo, Pollinations.ai, ArXiv

### Code Quality
- 56 Python modules, well-organized by domain
- 44/44 automated tests passing
- Extensive documentation: FLOWCHARTS.md, COMPLETE_ARCHITECTURE_ANALYSIS.md, devlog sessions
- Context manager fixes applied (vault.py, code_rag.py, etc.)
- Shell injection fixes via shlex.split()

### Operational Resilience
- Circuit breakers per provider (CLOSED/OPEN/HALF_OPEN)
- 60s rate limit skip on failure
- Docker sandbox for code execution (network disabled)
- Dangerous command blocklist in agent.py

---

## Weaknesses / Gaps

### Critical (Fix Immediately)

| Issue | Impact | Root Cause |
|-------|--------|-----------|
| **C1: `_speak_sentence` NameError** | All voice TTS silently fails | Function renamed but stale reference in closure/thread |
| **C2: MCP servers fail on startup** | filesystem/brave-search/gdrive always crash | npx cold-download hits 60s timeout |
| **C3: SmartMemory import error** | ImportError in edith.py doctor, intent_dispatch | Class renamed, no alias |

### High Priority

| Issue | Impact | Root Cause |
|-------|--------|-----------|
| **H1: shell=True in config.py (lines 28, 30)** | Command injection risk | X11 auth detection uses shell=True |
| **H2: Memory consolidation 12 days overdue** | Unchecked memory growth | background_daemon stopped Apr 18-30 |
| **H3: Widget X11 broken** | Global hotkeys dead | Missing XAUTHORITY env var |
| **H4: API key fallback pattern** | Secrets in process listing | `vault.get_secret() or os.getenv()` |

### Medium Priority

| Issue | Impact | Root Cause |
|-------|--------|-----------|
| **M1: No type hints** | Limited IDE support | Python 3.11 feature unused |
| **M2: No automated tests** | Manual smoke tests only | test_harness exists but limited |
| **M3: Mostly sync I/O** | Blocking calls | No async/await refactor |
| **M4: Global state** | Thread safety risk | _whisper_model, CURRENT_SESSION |
| **M5: vault.enc/vault.salt permissions 644** | Any local user can read | File permission not hardened |
| **M6: 7 API keys in .env plaintext** | GROQ_ARCH_KEY, SERPER, EXA, etc. | Not migrated to vault |

### Low Priority

| Issue | Impact | Root Cause |
|-------|--------|-----------|
| **L1: drift_log.json missing** | Drift history lost on restart | Not persisted to disk |
| **L2: feedback_tagger not live** | Thumbs up/down ineffective | Only in test_harness |
| **L3: no incoming Telegram filter** | Any user can message bot | CHAT_ID only filters outbound |
| **L4: RAM at 77%** | Risk of OOM on large model | Limited headroom |

---

## Risks by Priority

### P1-Critical (Immediate)

1. **_speak_sentence NameError** — Voice responses have no audio. Every TTS call logs ERROR.
2. **MCP startup failure** — 2 zombie npm processes, every /mcp intent fails.
3. **shell=True injection** — config.py lines 28-30 allow arbitrary command injection.

### P2-High (This Week)

4. **Provider key exposure** — API keys visible in `ps aux` environment.
5. **Memory bloat** — 12 days without consolidation/backup.
6. **Security audit findings** — 3 critical issues unfixed from Apr 29.

### P3-Medium (This Month)

7. **Type hints missing** — Technical debt, limits maintainability.
8. **Test coverage** — Only smoke tests, no unit tests.
9. **RAM exhaustion** — 77% usage + Ollama model loading.
10. **Multi-user not supported** — Hardcoded CHAT_ID, single user only.

### P4-Low (Backlog)

11. **drift_log.json missing** — Profile observations lost.
12. **feedback_tagger inactive** — No live routing impact.
13. **GPU misidentified** — Expected UHD 770, have UHD 730.

---

## Specific Recommendations (Max 5)

### 1. Fix _speak_sentence NameError (CRITICAL)
```bash
grep -n "_speak_sentence" voice.py
# Replace with speak_sentence
```
**Time:** 5 min | **Impact:** Voice TTS restored

### 2. Fix MCP Startup (CRITICAL)
```bash
npm install -g @modelcontextprotocol/server-filesystem \
  @modelcontextprotocol/server-brave-search \
  @modelcontextprotocol/server-github \
  @modelcontextprotocol/server-gdrive
```
Update mcp_config.json to use `"command": "node"` with explicit package path.  
**Time:** 30 min | **Impact:** MCP tools operational

### 3. shell=True ALREADY FIXED in config.py ✅
- config.py lines 28-30 now use `subprocess.run()` with `shell=False` and list args
- **Impact:** Issue resolved in recent session

### 4. Run Memory Maintenance (HIGH)
```python
python -c "from background_daemon import _run_maintenance; _run_maintenance()"
```
Or wait for scheduled 02:30 run.  
**Time:** 10 min | **Impact:** Consolidation + backup resume

### 5. Hardening Vault Permissions (MEDIUM)
```bash
chmod 600 /home/vaibhav/EDITH/vault.enc /home/vaibhav/EDITH/vault.salt
```
**Time:** 5 min | **Impact:** Encrypted vault not world-readable

---

## Summary Table

| Category | Status | Grade |
|----------|--------|-------|
| Architecture | Excellent (innovative 4-Vision) | A |
| Code Quality | Good (some tech debt) | B+ |
| Testing | Weak (smoke only) | C |
| Security | Needs fixes (3 critical) | B- |
| Performance | Adequate (single user) | B |
| Maintainability | Good (modular) | B+ |
| Operational | Needs attention (warns) | B- |

---

## Next Steps

1. Fix C1-C3 critical issues immediately
2. Apply security audit fixes (shell=True)
3. Run overdue maintenance
4. Add type hints to core modules (quick win)
5. Write unit tests for high-risk modules (smart_router, intent dispatch)

---

**Assessment prepared:** 2026-04-30  
**Source:** CLAUDE.md, COMPLETE_ARCHITECTURE_ANALYSIS.md, SYSTEM_AUDIT_2026-04-30.md, SECURITY_AUDIT_FINDINGS_2026-04-29.md, devlog_session_2026-04-30.md
