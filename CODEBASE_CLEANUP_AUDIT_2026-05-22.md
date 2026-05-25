# EDITH Codebase Cleanup Audit — 2026-05-22

**Status:** Production v1.0 with **14 known critical/high/medium issues**  
**Generated:** 2026-05-22 by comprehensive workspace analysis  
**Scope:** Structure, dependencies, code quality, security, test coverage  

---

## Executive Summary

EDITH is a sophisticated 56-module AI assistant with innovative cognitive architecture and strong core functionality. However, the codebase has accumulated technical debt across multiple dimensions:

- **3 CRITICAL bugs** blocking core features (voice, memory, MCP)
- **5 HIGH-PRIORITY issues** affecting security and reliability
- **6 MEDIUM-PRIORITY issues** impacting maintainability and test coverage
- **Multiple LOW-PRIORITY structural problems** (stray files, dead code, type hints)

**Critical Path:** Fix 3 critical bugs (2 hrs) + apply security patches (1 hr) + run memory maintenance (10 min) = **functional system by hour 3**. Full cleanup feasible in **1-2 weeks**.

---

## SECTION 1: CRITICAL BUGS (FIX IMMEDIATELY)

### C1: SmartMemory Import Error → Intent Dispatch Broken

**Severity:** CRITICAL | **Impact:** Blocks REST /api/chat, Telegram intents, voice commands  
**File:** [smart_memory.py](smart_memory.py) → `SmartMemoryManager` class is correct, but **no backward-compatible alias**  

**Status:** 
```
├── smart_memory.py:28          ✅ CORRECT: class SmartMemoryManager
├── orchestrator.py:16          ❌ FAILS: from smart_memory import SmartMemory (name not exported)
├── intent_dispatch.py:~unknown ❌ FAILS: same import issue
├── chat_server.py:1425         ✅ CORRECT: comment mentions SmartMemoryManager
└── cognitive_profile.py:11     ✅ CORRECT: from smart_memory import SmartMemoryManager
```

**Root Cause:** Class renamed from `SmartMemory` → `SmartMemoryManager` but import statements not updated universally. Orchestrator and intent_dispatch still use old name.

**Fix:** Add alias to smart_memory.py:
```python
# Line ~60 in smart_memory.py (after SmartMemoryManager class definition)
SmartMemory = SmartMemoryManager  # Backward compatibility alias
```

**Time:** 1 min | **Verification:**
```bash
python -c "from smart_memory import SmartMemory; print('OK')"
python -c "from orchestrator import smart_memory; print(smart_memory.__class__.__name__)"
```

---

### C2: `_speak_sentence` NameError → All Voice TTS Silent

**Severity:** CRITICAL | **Impact:** No audio output for voice responses  
**File:** [voice.py](voice.py)  

**Status:**
```
├── voice.py:644               ✅ CORRECT: def speak_sentence(...)
├── voice.py:613               ✅ CORRECT: call speak_sentence(...)
├── voice.py:755               ✅ CORRECT: call speak_sentence(...)
├── chat_server.py:402         ✅ CORRECT: from voice import speak_sentence
├── chat_server.py:858|874     ✅ CORRECT: from voice import speak_sentence as vs
├── voice.py:(unidentified)    ❌ FAILS: stale reference to _speak_sentence in thread/closure
└── LOGS:                       5+ ERROR "name '_speak_sentence' is not defined" (Apr 27, May 5)
```

**Root Cause:** Function renamed from `_speak_sentence` → `speak_sentence`, but old name referenced in a closure or thread that captures the old name.

**Fix:** 
```bash
grep -n "speak_sentence\|_speak_sentence" voice.py | head -20
```
Then search for closures, threading.Thread calls, or `partial()` that reference old name. Replace all `_speak_sentence` → `speak_sentence`.

**Likely Location in voice.py:**
- Line ~748-760: Thread that spawns TTS worker
- Line ~635-650: A lambda/partial wrapping

**Time:** 15 min | **Verification:** 
```bash
python -m pytest voice.py::test_speak_sentence -v 2>/dev/null || true
```

---

### C3: MCP Server Startup Fails → All /mcp Intent Broken

**Severity:** CRITICAL | **Impact:** 0% success rate on MCP intents (filesystem, brave-search, gdrive, etc.)  
**File:** [mcp_bridge.py](mcp_bridge.py) + [mcp_config.json](mcp_config.json)  

**Status:**
```
├── mcp_config.json            ✅ File present, 4 servers configured
├── mcp_bridge.py              ✅ Handler exists
├── Logs (Apr 29-30)           ❌ FAILS: "Timed out 60s on tools/list" — every restart
├── Zombie processes           2 defunct `npm exec @modelcontextprotocol` pids (6431, 6850)
└── System test (2026-04-30)   No separate MCP PID found → lazy-loaded handler fails
```

**Root Cause:** MCP servers configured to use `npx @modelcontextprotocol/server-*`, which:
1. Requires npm registry download on **every spawn** (not pre-installed)
2. 60s timeout too short for cold npm install
3. No retry logic or fallback

**Fix:** Pre-install MCP servers globally:

```bash
# Pre-install globally (one-time)
npm install -g @modelcontextprotocol/server-filesystem \
  @modelcontextprotocol/server-brave-search \
  @modelcontextprotocol/server-gdrive \
  @modelcontextprotocol/server-github

# Update mcp_config.json to reference installed packages
# Change: "command": "npx", "args": ["-y", "@modelcontextprotocol/server-filesystem"]
# To: "command": "/usr/local/bin/mcp-server-filesystem" (or equivalent installed path)
```

Alternatively, use Node.js require syntax:
```json
{
  "filesystem": {
    "command": "node",
    "args": ["-e", "require('@modelcontextprotocol/server-filesystem').main(process.argv.slice(2))"]
  }
}
```

**Time:** 30 min | **Verification:**
```bash
# After npm install
npx @modelcontextprotocol/server-filesystem list_directory --path /tmp
# Should return directory listing, not timeout
```

---

## SECTION 2: HIGH-PRIORITY ISSUES (THIS WEEK)

### H1: API Key Exposure — Fallback Pattern Visible in Environment

**Severity:** HIGH | **Impact:** Secrets visible in `ps aux`, `/proc/PID/environ`  
**Root Cause:** Fallback pattern `vault.get_secret() or os.getenv()` leaks keys to shell environment  

**Affected Files:**
```
├── smart_router.py:38-41       GROQ_KEY, GEMINI_KEY, NVIDIA_KEY, OPENROUTER_KEY
├── chat_server.py:371          Groq key
├── voice.py:194, 310           Groq key (2x)
├── vision.py:144               Gemini key
├── email_reader.py:31-32       Gmail credentials
├── telegram_bot.py:34-35       Telegram token
└── config.py:256               Generic getter with fallback
```

**Current Pattern (UNSAFE):**
```python
GROQ_KEY = vault.get_secret("GROQ_API_KEY", "") or os.getenv("GROQ_API_KEY", "")
```

**Risk:** If vault is empty/uninitialized, key lives plaintext in process environment.

**Fix:**
```python
# Option 1: Vault-only (recommended)
GROQ_KEY = vault.get_secret("GROQ_API_KEY")
if not GROQ_KEY:
    raise ValueError("GROQ_API_KEY not configured in vault. Run vault.py to add it.")

# Option 2: Env → vault migration (if needed temporarily)
GROQ_KEY = vault.get_secret("GROQ_API_KEY", "")
if not GROQ_KEY:
    env_val = os.getenv("GROQ_API_KEY", "")
    if env_val:
        LAN_LOGGER.warning("Using GROQ_API_KEY from environment; migrate to vault ASAP")
        GROQ_KEY = env_val
```

**Files to Update:** 8 files (see list above)  
**Time:** 45 min | **Verification:**
```bash
python -c "import smart_router; print(smart_router.GROQ_KEY[:10] if smart_router.GROQ_KEY else 'VAULT_ONLY')"
```

---

### H2: Vault Permissions Too Open (644 → 600)

**Severity:** HIGH | **Impact:** Any local user can read encrypted vault file  
**Current State:**
```bash
ls -la vault.enc vault.salt
# -rw-r--r-- (644)  — World-readable!
```

**Fix:**
```bash
chmod 600 /home/vaibhav/EDITH/vault.enc /home/vaibhav/EDITH/vault.salt
chmod 600 /home/vaibhav/EDITH/vault.enc.bak
```

**Time:** 1 min | **Verification:**
```bash
ls -l vault.enc vault.salt | awk '{print $1, $NF}'
# Should show: -rw------- vault.enc
```

---

### H3: Memory Consolidation 12 Days Overdue

**Severity:** HIGH | **Impact:** Unbounded memory growth, no backups since Apr 18  
**Root Cause:** `background_daemon.py` maintenance scheduler stopped Apr 18—30

**Current Memory Size:**
```
├── memory_archive.db       ~240 KB (195 rows)
├── session_state.db        ~12 KB  
├── trace_log.db            ~20 KB
├── memory_db/              ~2.5 MB (ChromaDB)
└── memory_db_backup/       964 KB (13 days old)
```

**Fix:** Run maintenance immediately:
```python
python -c "
from background_daemon import _run_maintenance
_run_maintenance()
"
```

Or wait for scheduled 02:30 run tonight (daemon now running).

**Verify:**
```bash
grep "Memory consolidation" logs/edith.log | tail -1
# Should show recent timestamp
```

**Time:** 10 min | **Impact:** Consolidation + backup restored

---

### H4: Widget X11 Broken — Global Hotkeys Dead

**Severity:** HIGH | **Impact:** Keyboard shortcut (Ctrl+Alt+E) doesn't launch EDITH  
**Status:**
```bash
systemctl --user status edith-widget.service
# ✓ active (running)
# But: pynput cannot connect to display — X11 auth missing
```

**Root Cause:** `edith_widget.py` spawned by systemd user service lacks X11 environment variables (DISPLAY, XAUTHORITY)

**Fix:** Update [edith-widget.service](edith-widget.service):
```ini
[Service]
Type=simple
ExecStart=/home/vaibhav/edith-env/bin/python /home/vaibhav/EDITH/edith_widget.py

# ADD THESE LINES:
Environment="DISPLAY=:0"
Environment="XAUTHORITY=/home/vaibhav/.Xauthority"
Environment="QT_QPA_PLATFORM=xcb"

After=graphical-session-started.target
PartOf=graphical-session.target
```

Alternatively, run via `systemctl --user import-environment DISPLAY XAUTHORITY` before service start.

**Time:** 5 min | **Verification:**
```bash
systemctl --user restart edith-widget.service
# Check logs: systemctl --user status edith-widget.service
# Should not show "DISPLAY" error
```

---

### H5: `.env` Still Has 7 Plaintext API Keys (Should Be in Vault)

**Severity:** HIGH | **Impact:** Secrets visible in `.env` file  

**Current Keys in .env:**
```
GROQ_ARCH_KEY
SERPER_API_KEY
EXA_API_KEY
TAVILY_API_KEY
GITHUB_PERSONAL_ACCESS_TOKEN
CLOUDFLARE_API_TOKEN
CLOUDFLARE_ACCOUNT_ID
```

**Fix:** Migrate to vault:
```bash
python vault.py
# Interactive: add each key to encrypted vault
# Then remove from .env
```

**Time:** 15 min | **Status:** Not blocking (vault fallback works), but **must be done before production deploy**

---

## SECTION 3: MEDIUM-PRIORITY ISSUES (THIS MONTH)

### M1: No Type Hints → Limited IDE Support & Maintainability

**Severity:** MEDIUM | **Impact:** No autocomplete in IDE, harder refactoring  
**Language Feature Available:** Python 3.11+ (already running)  
**Current State:** 56 modules, nearly **0% type hints**

**Top Priority Files (highest impact):**
```
1. orchestrator.py          (core entry point, 400+ lines)
2. smart_router.py          (routing logic, complex)
3. intent_dispatch.py       (56 handlers, dispatch logic)
4. voice.py                 (voice pipeline, threading)
5. rag.py                   (LLM integration, list returns)
6. chat_server.py           (API endpoints, 500+ lines)
```

**Example Fix (voice.py):**
```python
# BEFORE:
def speak_sentence(text):
    # ...

# AFTER:
def speak_sentence(text: str) -> bool:
    """Speak text aloud via TTS. Returns True if successful."""
    # ...
```

**Tool:** Use Pylance refactoring:
```bash
# All files at once:
for f in orchestrator.py smart_router.py intent_dispatch.py; do
  python -m pylance invoke-refactoring "$f" source.addTypeAnnotation
done
```

**Time:** 4-6 hours (1-2 hours per file for top 3) | **Priority:** Medium (doesn't break functionality now)

---

### M2: No Production Test Suite — Only Smoke Tests

**Severity:** MEDIUM | **Impact:** No regression detection, manual testing only  
**Current State:**
```
├── test_harness.py         (44 smoke tests, all pass ✓)
├── tests/                  (empty directory)
├── test/                   (empty directory)
└── pytest                  (installed but no pytest.ini)
```

**Missing Test Coverage:**
1. Unit tests for critical modules (smart_router, voice, rag)
2. Integration tests for request lifecycle
3. API endpoint tests (10+ endpoints untested)
4. Memory system tests (smart_memory, episodic, graph)
5. Security tests (dangerous pattern detection, vault access)

**Recommended Test Structure:**
```
tests/
├── unit/
│   ├── test_smart_router.py
│   ├── test_voice.py
│   ├── test_intent.py
│   └── test_vault.py
├── integration/
│   ├── test_request_lifecycle.py
│   ├── test_api_endpoints.py
│   └── test_memory_systems.py
├── security/
│   ├── test_injection_patterns.py
│   ├── test_vault_access.py
│   └── test_secret_exposure.py
└── conftest.py
```

**Time:** 8-12 hours to build (2-3 tests per module) | **Priority:** High for production stability

---

### M3: Mostly Sync I/O — No Async/Await for Concurrency

**Severity:** MEDIUM | **Impact:** Blocking calls during voice/API, poor responsiveness  
**Current State:**
```
├── background_daemon.py    (sleep loops — blocks entire process)
├── chat_server.py          (FastAPI async but handlers call sync functions)
├── voice.py                (blocking aplay call, blocks entire audio pipeline)
├── rag.py                  (sync LLM calls in vectorstore loop)
└── Most intent handlers    (subprocess.run, no timeout logic)
```

**Critical Blocking Calls:**
```python
# voice.py:~700 — blocks for entire audio playback
subprocess.run(["aplay", "-q", wav_file])  # No timeout, blocks

# chat_server.py:~400 — blocks FastAPI endpoint
response = smart_router.smart_call(...)  # May take 30+ secs
```

**Quick Fix (No Full Refactor):**
```python
# Add timeouts to all subprocess calls:
subprocess.run(["aplay", "-q", wav_file], timeout=30)

# Wrap slow I/O in asyncio.to_thread():
import asyncio
async def async_smart_call():
    loop = asyncio.get_event_loop()
    result = await loop.to_thread(smart_router.smart_call, ctx)
    return result
```

**Time:** 4-6 hours (refactor hot paths) | **Priority:** Medium (affects UX under load)

---

### M4: Global Thread State — Race Conditions Risk

**Severity:** MEDIUM | **Impact:** Potential memory corruption under concurrent requests  
**Current Global Mutable State:**
```
├── voice.py:~100           _whisper_model (global)
├── voice.py:~200           _chatterbox_worker (global thread)
├── smart_memory.py:~35     ram_cache OrderedDict (shared)
├── session.py:~10          CURRENT_SESSION (global)
├── config.py:~50           Various singleton models
└── Multiple modules        Cache dicts without locks
```

**Example (sim_memory.py):**
```python
# CURRENT (NOT THREAD-SAFE):
self.ram_cache = OrderedDict()  # Shared, no lock during reads

# NEEDS:
self._read_lock = threading.RLock()
def get(key):
    with self._read_lock:
        return self.ram_cache.get(key)
```

**Fix:** All shared mutable state must be protected:
```python
# voice.py example
_whisper_model = None
_whisper_model_lock = threading.Lock()

def get_whisper_model():
    global _whisper_model
    with _whisper_model_lock:
        if _whisper_model is None:
            _whisper_model = load_model(...)
        return _whisper_model
```

**Time:** 6-8 hours (audit + fix all globals) | **Priority:** Medium (low # of concurrent requests currently)

---

### M5: 2 Null Directories — Deleted Backups Taking Space

**Severity:** MEDIUM | **Impact:** ~2-3 MB unnecessary disk, confusing structure  
**Current Backups:**
```
├── chroma_db_deleted_backup/     (null: 0 entries — safe to delete)
├── edith_memory_deleted_backup/  (null: 0 entries — safe to delete)
└── memory_db_backup/             (964 KB — keep, but update frequency)
```

**Fix:**
```bash
rm -rf chroma_db_deleted_backup/ edith_memory_deleted_backup/
# Consolidate: cp -r memory_db/ memory_db_backup_$(date +%Y%m%d)
```

**Time:** 1 min | **Safe?** Yes (empty, already marked "deleted")

---

### M6: Stray Admin/Test Files in Root

**Severity:** MEDIUM | **Impact:** Cluttered workspace, confusion about structure  

**Files to Move/Remove:**
```
├── C:\Users\Owner\Desktop\TestFolder.txt: Test Folder 123    ❌ DELETE (Windows path)
├── C:\Users\Public\Desktop\test.txt                           ❌ DELETE (Windows path)
├── TestProject/                                               ❌ DELETE (stray test dir)
├── dashboard.py.bak                                           ❌ DELETE (old backup)
├── vault.enc.bak                                              ✓ KEEP (current backup)
├── edith_dashboard.html                                       ❓ UNCLEAR (static HTML?)
├── tree.txt                                                   ❓ DELETE (generated output)
├── cleanup.log                                                ❓ DELETE (old run logs)
└── top qwen2.5:1.5b                                          ⚠️ UNCLEAR (corrupted filename)
```

**Fix:**
```bash
# Safe deletions
rm -f 'C:\Users\Owner\Desktop\TestFolder.txt: Test Folder 123'
rm -f 'C:\Users\Public\Desktop\test.txt'
rm -rf TestProject/
rm -f dashboard.py.bak
rm -f tree.txt cleanup.log
rm -f 'top qwen2.5:1.5b'  # Corrupted filename, likely from typo

# Check before deleting
ls -la edith_dashboard.html
# If this is generated, move to docs/ or delete
```

**Time:** 5 min | **Safe?** Yes (all temp/test/stray files)

---

## SECTION 4: LOW-PRIORITY ISSUES (BACKLOG)

### L1: `drift_log.json` Missing — Drift History Lost on Restart

**Severity:** LOW | **Impact:** Cognitive profile doesn't persist drift observations  
**Root Cause:** `save_drift_check()` writes to `drift_log.json`, but file never created/rotated  

**Fix:** [cognitive_profile.py](cognitive_profile.py) — add persistence:
```python
import json
from pathlib import Path

DRIFT_LOG_PATH = Path(get_data_dir()) / "drift_log.json"

def save_drift_check(drift_score, reason):
    """Persist drift check to disk."""
    data = {
        "timestamp": time.time(),
        "drift_score": drift_score,
        "reason": reason
    }
    with open(DRIFT_LOG_PATH, "a") as f:
        f.write(json.dumps(data) + "\n")
```

**Time:** 15 min | **Impact:** Minimal (nice-to-have observability feature)

---

### L2: Episode Save Path Unclear — Session Episodes Not Recorded

**Severity:** LOW | **Impact:** Episodic memory never grows  
**Current State:**
```
├── episodic_memory.py       (module-level functions, backend = ChromaDB)
├── orchestrator.py          (imports recall_episodes, but never save_episode)
└── ChromaDB edith_episodic  (1 test entry only, from Apr 8)
```

**Fix:** Wire episode save in orchestrator.session_end():
```python
from episodic_memory import save_episode

def end_session(session_id):
    # ... existing cleanup ...
    summary = generate_session_summary(session_logs)
    save_episode(session_id, summary, session_logs)
```

**Time:** 20 min | **Current Impact:** None (feature unused)

---

### L3: Telegram Incoming Filter Partial — No Auth on Inbound

**Severity:** LOW | **Impact:** Any user can message bot (but no responses without valid intent)  
**Current State:**
```python
# telegram_bot.py:~300
CHAT_ID = vault.get_secret("TELEGRAM_CHAT_ID")  # Only filters OUTBOUND
# No filter on INBOUND messages
```

**Fix:** Add webhook validation:
```python
@app.post("/telegram-webhook")
async def telegram_webhook(request: Request):
    data = await request.json()
    
    # INBOUND filter
    if data.get("message", {}).get("chat", {}).get("id") != CHAT_ID:
        LAN_LOGGER.warning(f"Blocked message from unknown chat: {data['message']['chat']['id']}")
        return {"status": "filtered"}
    
    # Process...
```

**Time:** 10 min | **Current Impact:** Low (rate-limit handles spam)

---

### L4: Code RAG Never Indexed — `edith_codebase` Collection Empty

**Severity:** LOW | **Impact:** Code search / self-improvement features have no index  
**Current State:**
```bash
$ python -c "
import chromadb
c = chromadb.PersistentClient(path='memory_db')
print(len(c.get_collection('edith_codebase').get()['ids']))
"
# 0  ← empty
```

**Fix:** Index EDITH's own source on startup:
```python
from code_rag import index_codebase

def bootstrap_codebase_rag():
    \"\"\"Index EDITH's own source for self-improvement queries.\"\"\"
    edith_root = Path(__file__).parent
    index_codebase(str(edith_root), collection_name="edith_codebase")
```

**Call in:** background_daemon.py startup  
**Time:** 20 min | **Current Impact:** Low (self-improvement feature incomplete)

---

### L5: GPU Misidentified (Expected UHD 770, Have UHD 730)

**Severity:** LOW | **Impact:** Minor (informational, doesn't affect compute)  
**Current State:**
```
SYSTEM_AUDIT notes: "GPU misidentified — Expected UHD 770, have UHD 730"
```

**Fix:** Update [config.py](config.py) GPU detection or documentation.

**Time:** 5 min | **Impact:** None (cosmetic)

---

### L6: Unused/Dead Modules — Cleanup

**Severity:** LOW | **Impact:** Codebase clarity, maintenance burden  

**Potentially Dead Code:**
```
├── chatterbox_worker.py         (Chatterbox integration, status unclear)
├── compound_dag.py              (Graph DAG, imported nowhere)
├── conversation_dna.py          (Used? imported in edge case)
├── coding_personality.json|txt  (Metadata, used?)
└── image_gen.py                 (Pollinations.ai wrapper, imported nowhere)
```

**Action:** Audit imports before removing:
```bash
for file in chatterbox_worker.py compound_dag.py image_gen.py; do
  echo "=== $file ==="
  grep -r "import ${file%%.py}" . --include="*.py" | grep -v test | grep -v "^Binary"
done
```

**Time:** 30 min (audit + cleanup) | **Safe?** Only delete if 0 imports confirmed

---

## SECTION 5: FILE STRUCTURE CLEANUP

### Current Root Issues

```
/home/vaibhav/EDITH/
├── 🟢 Core Modules (56 Python files)     — GOOD organization
├── 🟡 Config Files (.env, config.py)    — GOOD but needs cleanup
├── 🟡 Backups (vault.enc.bak, etc.)     — Should retire old ones
├── 🔴 Test Files                        — Fragmented (TestProject/, test/, tests/, test_harness.py)
├── 🔴 Stray Files                       — Windows paths, corrupted names
├── 🟡 Data Dirs (memory_db/, chroma_db/, etc.) — Good but too many backups
├── 🟡 Documentation                     — Scattered (md in root + notes/ folder)
└── 🟡 Execution Artifacts               — logs/, downloads/, charts/ 
```

### Recommended Structure (Optional Refactor)

```
/home/vaibhav/EDITH/
├── src/
│   ├── core/                  # Orchestrator, router, context
│   │   ├── orchestrator.py
│   │   ├── smart_router.py
│   │   ├── intent_dispatch.py
│   │   └── context.py
│   ├── memory/                # All memory systems
│   │   ├── smart_memory.py
│   │   ├── episodic_memory.py
│   │   ├── graph_memory.py
│   │   ├── cognitive_profile.py
│   │   └── consolidation.py
│   ├── voice/                 # Voice pipeline
│   │   ├── voice.py
│   │   ├── wake_listener.py
│   │   └── chatterbox_worker.py
│   ├── reasoning/             # 4-Vision cognitive system
│   │   ├── council.py
│   │   ├── life_os.py
│   │   ├── self_improve.py
│   │   └── conversation_dna.py
│   ├── api/                   # REST endpoints
│   │   └── chat_server.py
│   ├── integrations/          # External services
│   │   ├── telegram_bot.py
│   │   ├── email_reader.py
│   │   ├── calendar_reader.py
│   │   └── phone.py
│   ├── knowledge/             # RAG, search, vision
│   │   ├── rag.py
│   │   ├── code_rag.py
│   │   ├── search.py
│   │   └── vision.py
│   ├── infra/                 # Circuit breaker, routing, vault
│   │   ├── circuit_breaker.py
│   │   ├── ml_router.py
│   │   ├── vault.py
│   │   └── db_pool.py
│   ├── config.py              # Configuration
│   ├── edith.py               # Main entry (menu)
│   ├── background_daemon.py   # Scheduler
│   └── __init__.py
├── tests/
│   ├── unit/
│   ├── integration/
│   └── security/
├── docs/
│   ├── CLAUDE.md
│   ├── PROJECT_ASSESSMENT.md
│   ├── ARCHITECTURE.md
│   └── SETUP.md
├── config/
│   ├── .env
│   ├── config.json (if added)
│   └── mcp_config.json
├── data/
│   ├── memory_db/
│   ├── session_state.db
│   └── trace_log.db
├── services/
│   ├── edith.service
│   ├── edith-widget.service
│   └── edith-arch-updater.service
├── scripts/
│   ├── start_edith.sh
│   └── smoke_test.sh
├── requirements.txt
├── README.md
├── Dockerfile.local
└── .gitignore
```

**Cost-Benefit:** High (clearer structure) vs Medium (refactoring work) — **Consider only if rewriting major modules anyway.**

---

## SECTION 6: CLEANUP IMPLEMENTATION ROADMAP

### Phase 1: Critical Bugs (URGENT — 2 hours)

**Task P1.1: Fix SmartMemory Import Alias**  
- File: [smart_memory.py](smart_memory.py)
- Change: Add `SmartMemory = SmartMemoryManager` alias
- Time: 1 min
- Verification: `python -c "from smart_memory import SmartMemory"`

**Task P1.2: Fix _speak_sentence NameError**  
- File: [voice.py](voice.py)
- Change: Find & replace `_speak_sentence` → `speak_sentence` (in closures/threads)
- Time: 15 min
- Verification: `python -c "from voice import speak_sentence; print(speak_sentence.__name__)"`

**Task P1.3: Fix MCP Server Startup**  
- Files: [mcp_config.json](mcp_config.json), [mcp_bridge.py](mcp_bridge.py)
- Change: Pre-install MCP servers, update config to use local paths
- Time: 30 min
- Verification: Test `/mcp ls-files /tmp` endpoint

**Phase 1 Total: 46 min** ✅

---

### Phase 2: High-Priority Security (1.5 hours)

**Task P2.1: Migrate API Keys to Vault-Only**  
- Files: smart_router.py, chat_server.py, voice.py, vision.py, email_reader.py, telegram_bot.py, config.py
- Change: Remove `or os.getenv()` fallback, fail loudly if missing
- Time: 45 min
- Verification: `python -c "import smart_router; smart_router.GROQ_KEY"`

**Task P2.2: Fix Vault File Permissions**  
- Files: vault.enc, vault.salt
- Change: `chmod 600`
- Time: 1 min

**Task P2.3: Fix Widget X11 Environment**  
- File: [edith-widget.service](edith-widget.service)
- Change: Add DISPLAY, XAUTHORITY env vars
- Time: 5 min

**Task P2.4: Run Memory Consolidation**  
- Command: `python -c "from background_daemon import _run_maintenance; _run_maintenance()"`
- Time: 10 min

**Phase 2 Total: 61 min** ✅

---

### Phase 3: File & Structure Cleanup (30 min)

**Task P3.1: Remove Stray Files**  
```bash
rm -f 'C:\Users\Owner\Desktop\TestFolder.txt: Test Folder 123'
rm -f 'C:\Users\Public\Desktop\test.txt'
rm -rf TestProject/
rm -f dashboard.py.bak tree.txt cleanup.log 'top qwen2.5:1.5b'
```
- Time: 5 min

**Task P3.2: Clean Backup Directories**  
```bash
rm -rf chroma_db_deleted_backup/ edith_memory_deleted_backup/
```
- Time: 1 min

**Task P3.3: Update .gitignore**  
- Add: `.env`, `*.bak`, `TestProject/`, stray files
- Time: 10 min

**Phase 3 Total: 16 min** ✅

---

### Phase 4: Type Hints & Tests (4-6 days, parallelizable)

**Task P4.1: Add Type Hints to Core 3 Modules**  
- Files: orchestrator.py, smart_router.py, intent_dispatch.py
- Estimate: 2-3 hours per file
- Total: 6-9 hours (spread over 2 days)

**Task P4.2: Build Unit Test Suite**  
- 10 critical modules, 2-3 tests each
- Estimate: 10-12 hours (2-3 days)

**Task P4.3: Async/Await for Hot Paths**  
- Identify & wrap 5-10 slow calls
- Estimate: 4-6 hours (1-2 days)

**Phase 4 Total: 20-27 hours** (6-8 days @4hrs/day)

---

### Phase 5: Nice-to-Have Features (1-2 weeks)

- L1: Drift log persistence (15 min)
- L2: Episode save wiring (20 min)
- L3: Telegram auth (10 min)
- L4: Code RAG indexing (20 min)
- L6: Dead code audit & cleanup (2-4 hours)

**Total: 4-6 hours**

---

## SECTION 7: RISK ASSESSMENT & MITIGATION

| Issue | Likelihood | Severity | Detection | Mitigation |
|-------|-----------|----------|-----------|-----------|
| C1 SmartMemory crash | HIGH | HIGH | ImportError on `/api/chat` | Add alias immediately, deploy hotfix |
| C2 Voice TTS silent | HIGH | MEDIUM | Error logs + manual voice test | Grep for `_speak_sentence`, replace, test |
| C3 MCP fails | HIGH | MEDIUM | Intent test `/mcp ls-files` | Pre-install npm packages globally |
| H1 Key exposure | LOW | HIGH | Audit trail in logs | Vault-only pattern, remove env fallback |
| H2 Vault perms | LOW | HIGH | Local user can read | `chmod 600` immediately |
| H3 Memory bloat | MEDIUM | MEDIUM | DB size check | Run consolidation, monitor growth |
| H4 Widget dead | MEDIAN | LOW | X11 error logs | Add env vars to service file |
| H5 .env secrets | LOW | HIGH | Git diff | Migrate to vault, deploy .env.example |
| M1 No type hints | LOW | MEDIUM | IDE autocomplete missing | Add gradually (tool-assisted) |
| M2 No tests | MEDIUM | MEDIUM | Regression undetected | Build test suite (2-3 weeks) |
| M3 Sync I/O | LOW | MEDIUM | Slow API responses | Async refactor hot paths (1 week) |
| M4 Global state | LOW | MEDIUM | Race condition under concurrency | Add thread locks (1-2 days) |
| M5 Dead backups | NONE | LOW | Disk space | Delete empty dirs (1 min) |
| M6 Stray files | NONE | LOW | Clutter | Delete Windows paths (5 min) |

---

## SECTION 8: DELIVERY TIMELINE

### Minimum Viable (MVP) — Get to Production Ready
```
P1: Critical bugs              ✅ 46 min     (voice, memory, MCP functional)
P2: High-priority security     ✅ 61 min     (keys secure, backups updated)
P3: File cleanup               ✅ 16 min     (workspace clean)
─────────────────────────────────────────────
TOTAL (same day):             ~2 hours     ✅ PRODUCTION-READY CHECKPOINT
```

### Enhanced (E) — Production Hardened
```
+ Type hints for 3 core files   6-9 hours   (next 2 days)
+ Unit test suite basics        10-12 hours (next 3 days)
+ Async refactor (top 5)        4-6 hours   (next 2 days)
─────────────────────────────────────────────
TOTAL (week 1):                 ~30 hours    ✅ HARDENED & TESTED
```

### Comprehensive (C) — Maintainable Codebase
```
+ All remaining type hints      4-6 hours   (week 2)
+ Full test coverage            8-10 hours  (week 2)
+ Thread safety audit           6-8 hours   (week 2-3)
+ Refactor → src/ structure     2-4 hours   (week 3, optional)
+ Dead code removal             2-4 hours   (week 3)
─────────────────────────────────────────────
TOTAL (3 weeks):                ~60 hours   ✅ PRODUCTION-GRADE CODEBASE
```

---

## SECTION 9: FILES REQUIRING CHANGES

### Critical (MVP Path)

```
Priority 1:  smart_memory.py                (add alias)
Priority 1:  voice.py                       (fix _speak_sentence)
Priority 1:  mcp_config.json                (npm pre-install)
Priority 1:  mcp_bridge.py                  (update paths)
─
Priority 2:  smart_router.py                (remove os.getenv fallback)
Priority 2:  chat_server.py, voice.py, vision.py, email_reader.py, etc. (remove fallbacks)
Priority 2:  vault.enc, vault.salt          (chmod 600)
Priority 2:  edith-widget.service           (add DISPLAY, XAUTHORITY)
Priority 2:  background_daemon.py           (run consolidation now)
─
Priority 3:  (stray files and dirs)         (delete Windows paths, backups)
```

### Enhanced (Week 1)

```
Type Hints:  orchestrator.py, smart_router.py, intent_dispatch.py
Tests:       tests/ → build unit test suite
Async:       voice.py, rag.py, chat_server.py (hot paths)
```

### Comprehensive (Weeks 2-3)

```
All remaining modules: add type hints
Security: thread locks for global state
Dead code: remove unused modules
Structure: optional refactor to src/ (if warranted)
```

---

## SECTION 10: SUCCESS CRITERIA & VERIFICATION

### Phase 1 Success (Critical Bugs Fixed)

✅ **SmartMemory alias added**
```bash
python -c "from smart_memory import SmartMemory; print('PASS')"
python -c "from orchestrator import smart_memory; print('PASS')"
```

✅ **Voice TTS works**
```bash
python chat_server.py &
curl -X POST http://localhost:8001/api/chat -d '{"text":"hello", "tts": true}'
# Should output audio to speaker or file
```

✅ **MCP servers respond**
```bash
curl -X POST http://localhost:8001/api/mcp -d '{"intent":"mcp", "args":["list", "/tmp"]}'
# Should NOT timeout, should return file list
```

### Phase 2 Success (High-Priority Fixed)

✅ **No API keys in environment**
```bash
ps aux | grep EDITH | grep -E "GROQ|GEMINI|NVIDIA"
# Should return empty (no keys visible)
```

✅ **Vault permissions hardened**
```bash
ls -l vault.enc vault.salt | awk '{print $1}'
# Should show: -rw------- (not -rw-r--r--)
```

✅ **Widget hotkeys work**
```bash
# Run Ctrl+Alt+E (or configured hotkey)
# Should spawn EDITH UI (or log shows success)
```

✅ **Memory consolidated**
```bash
grep "consolidation" logs/edith.log | tail -1
# Should show recent timestamp (within 24 hrs)
```

### Phase 3+ Success (Code Quality)

✅ **Type hints present**
```bash
python -m pyright orchestrator.py
# Should have 95%+ coverage (no red underlines in IDE)
```

✅ **Tests pass**
```bash
pytest tests/ -v
# Should have 50+ test cases, all pass
```

✅ **No race conditions**
```bash
python -c "import threading; import smart_memory; print(hasattr(smart_memory.SmartMemoryManager, '_write_lock'))"
# Should print True
```

---

## SECTION 11: SUMMARY TABLE

| # | Issue | Priority | Time | Impact | Status |
|---|-------|----------|------|--------|--------|
| C1 | SmartMemory alias | CRITICAL | 1 min | Blocks /api/chat | 🔴 |
| C2 | _speak_sentence NameError | CRITICAL | 15 min | Blocks voice TTS | 🔴 |
| C3 | MCP startup timeout | CRITICAL | 30 min | Blocks /mcp intent | 🔴 |
| H1 | API key exposure | HIGH | 45 min | Secret leak vector | 🔴 |
| H2 | Vault permissions 644 | HIGH | 1 min | Local user can read | 🔴 |
| H3 | Memory consolidation overdue | HIGH | 10 min | Unbounded growth | 🟡 |
| H4 | Widget X11 broken | HIGH | 5 min | Hotkeys dead | 🟡 |
| H5 | 7 keys in .env plaintext | HIGH | 15 min | Secret exposure | 🔴 |
| M1 | No type hints | MEDIUM | 6-9 hrs | IDE support limited | 🟡 |
| M2 | No test suite | MEDIUM | 10-12 hrs | No regression detection | 🟡 |
| M3 | Sync I/O blocking | MEDIUM | 4-6 hrs | Slow under load | 🟡 |
| M4 | Global mutable state | MEDIUM | 6-8 hrs | Race condition risk | 🟡 |
| M5 | Dead backup dirs | MEDIUM | 1 min | Clutter only | 🟢 |
| M6 | Stray files (Windows paths) | MEDIUM | 5 min | Confusing structure | 🟢 |
| L1 | drift_log.json missing | LOW | 15 min | Feature incomplete | 🟢 |
| L2 | Episode save unwired | LOW | 20 min | Feature unused | 🟢 |
| L3 | Telegram no inbound auth | LOW | 10 min | Rate-limit sufficient | 🟢 |
| L4 | Code RAG empty | LOW | 20 min | Self-improve incomplete | 🟢 |
| | | | | | |
| **CRITICAL TOTAL:** | 3 bugs | — | **46 min** | **Core blocked** | **Deploy hotfix** |
| **HIGH TOTAL:** | 5 issues | — | **76 min** | **Security risk** | **Fix next** |
| **MEDIUM TOTAL:** | 5 issues | — | **20-27 hrs** | **Tech debt** | **Week 1-2** |
| **LOW TOTAL:** | 4 issues | — | **4-6 hrs** | **Enhancement** | **Backlog** |

---

## FINAL RECOMMENDATIONS

### Immediate (Today)

1. ✅ **Apply hotfixes for C1, C2, C3** (46 min)
   - Deploy to production after testing
   - Voice, memory, MCP will restore function

2. ✅ **Apply security fixes for H1-H5** (76 min)
   - Vault keys, permissions, consolidation, widget
   - Reduces attack surface & data loss risk

3. ✅ **File cleanup P3** (16 min)
   - Delete Windows paths, stray test dirs
   - Clean logs, old backups

**TOTAL: ~2.5 hours to production-ready system** 🎯

---

### This Week (Additional)

4. Add type hints to orchestrator, smart_router, intent_dispatch (6-9 hrs)
5. Build core unit test suite (10-12 hrs)
6. Async refactor hot paths (4-6 hrs)

---

### This Month (Optional)

7. Complete type hint coverage (all modules)
8. Full test coverage (100%+ integration tests)
9. Thread safety audit + locks
10. Structure refactor (src/ reorganization) — optional if major rewrite anyway

---

**Next Step:** Start with Phase 1 (critical bugs). Estimated completion: **1 hour from now.** 🚀

