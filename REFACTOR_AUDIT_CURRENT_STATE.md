# EDITH Refactoring Audit — Current State Analysis

**Scan Date:** 2026-05-24  
**Scope:** Hardcoded paths, shell=True usage, and config.py approach

---

## 1. HARDCODED `/home/vaibhav` PATHS

### Summary
- **Total Matches:** 100+ across all file types
- **Files Affected:** 20+ unique files
- **Categories:** Shell scripts, systemd services, Python modules, config files

### Shell Scripts (.sh)

#### **smoke_test_standalone.sh**
```bash
Line 15:  EDITH_PATH="/home/vaibhav/EDITH"
Line 53:  sys.path.insert(0, "/home/vaibhav/EDITH")
```

#### **edith_arch_boot.sh** (root + files/ duplicate)
```bash
Line 2:   LOG="/home/vaibhav/EDITH/logs/arch_updater.log"
Line 3:   PYTHON="/home/vaibhav/edith-env/bin/python"
Line 4:   SCRIPT="/home/vaibhav/EDITH/edith_arch_updater.py"
```

#### **start_edith.sh**
```bash
Line 8-11: Python code loads .env from hardcoded path
           load_dotenv('/home/vaibhav/EDITH/.env')
Line 30:   nohup /home/vaibhav/edith-env/bin/python /home/vaibhav/EDITH/edith_widget.py > /dev/null 2>&1 &
```

---

### Systemd Service Files (.service)

#### **edith-widget.service**
```ini
Line 9:   ExecStart=/home/vaibhav/edith-env/bin/python /home/vaibhav/EDITH/edith_widget.py
Line 10:  WorkingDirectory=/home/vaibhav/EDITH
Line 18:  StandardOutput=append:/home/vaibhav/EDITH/logs/widget.log
Line 19:  StandardError=append:/home/vaibhav/EDITH/logs/widget.log
```

#### **edith.service**
```ini
Line 8:   ExecStart=/home/vaibhav/edith-env/bin/python /home/vaibhav/EDITH/background_daemon.py
Line 9:   WorkingDirectory=/home/vaibhav/EDITH
Line 18:  StandardOutput=append:/home/vaibhav/EDITH/logs/edith_daemon.log
Line 19:  StandardError=append:/home/vaibhav/EDITH/logs/edith_daemon.log
```

#### **edith-arch-updater.service**
```ini
Line 8:   ExecStart=/bin/bash /home/vaibhav/EDITH/edith_arch_boot.sh
```

---

### Python Files — Core Modules (.py)

#### **config.py**
```python
Line 62:   VENV_PATH = os.getenv("VENV_PATH", "/home/vaibhav/edith-env")
Line 204:  "/home/vaibhav/Documents/Ayur-stock pro",
Line 216:  "/home/vaibhav/Documents/Ayur-stock pro",
Line 371:  CHATTERBOX_VENV_PYTHON = os.getenv("CHATTERBOX_VENV_PYTHON", "/home/vaibhav/chatterbox-env/bin/python3")
```

**Context:** CODE_DIRS and REPOS lists hardcode secondary project paths

#### **agent.py**
```python
Line 237:  Use absolute paths like /home/vaibhav/  (in docstring/comment)
Line 258:  - Absolute paths only, starting with /home/vaibhav/  (in docstring/comment)
Line 354:  cwd="/home/vaibhav",  (subprocess cwd)
```

#### **intent_dispatch.py**
```python
Line 309:  dir_keywords = {"downloads": "/home/vaibhav/Downloads", "documents": "/home/vaibhav/Documents",
Line 310:                  "home": "/home/vaibhav", "desktop": "/home/vaibhav/Desktop"}
Line 311:  search_dir = "/home/vaibhav"
Line 354:  f"find /home/vaibhav {name_part} {size_part} 2>/dev/null "
Line 364:  return f"No {ext or ''} files found matching criteria in /home/vaibhav."
Line 377:  dir_map = {"downloads": "/home/vaibhav/Downloads", "download": "/home/vaibhav/Downloads",  ...
```

**Context:** File search and directory mapping operations — all hardcoded home path

#### **telegram_bot.py**
```python
Line 222:  path = _os.path.expanduser(path_m.group(1)) if path_m else "/home/vaibhav"
```

**Context:** Fallback path for Telegram file operations

#### **dashboard.py**
```python
Line 877:  (in HTML textarea placeholder)
           placeholder="-y, @modelcontextprotocol/server-filesystem, /home/vaibhav"
```

---

### Configuration Files

#### **mcp_config.json**
```json
Line 7:   "/home/vaibhav/.nvm/versions/node/v20.20.2/lib/node_modules/@modelcontextprotocol/server-filesystem/dist/index.js",
Line 8:   "/home/vaibhav"
Line 10:  "description": "Local filesystem access — read, write, list files under /home/vaibhav",
Line 23:  "/home/vaibhav/.nvm/versions/node/v20.20.2/lib/node_modules/@modelcontextprotocol/server-github/dist/index.js"
Line 38:  "/home/vaibhav/.nvm/versions/node/v20.20.2/lib/node_modules/@modelcontextprotocol/server-cloudflare/dist/index.js",
Line 57:  "/home/vaibhav/.nvm/versions/node/v20.20.2/lib/node_modules/@modelcontextprotocol/server-gdrive/dist/index.js"
Line 66:  "GDRIVE_OAUTH_PATH": "/home/vaibhav/EDITH/credentials.json",
Line 67:  "GDRIVE_CREDENTIALS_PATH": "/home/vaibhav/EDITH/token.json"
```

**Issue:** Node.js module paths + environment paths all hardcoded

#### **.claude/settings.json** (20+ matches)
```json
Lines:    25, 26, 39, 58, 59, 64, 65, 71, 98, 115, 122, 123, 127 (truncated), 130, 131, 136, 137
Pattern:  Bash commands, file operations, source/destination paths all hardcoded
Example:  
  Line 127: SRC=/home/vaibhav/EDITH  DST=/home/vaibhav/edith-source
```

#### **.claude/settings.local.json** (10+ matches)
```json
Similar pattern to settings.json
Lines:    4-11, 20-22, 40, 42-44, 60-66
Examples: Virtual env paths, pip install targets, API key grep patterns
```

---

### Duplicate/Archive Copies

#### **files/edith_arch_boot.sh**
```bash
Line 3:   # Place in: /home/vaibhav/EDITH/edith_arch_boot.sh
Line 6-8: Same 3 lines as main edith_arch_boot.sh
```

#### **files/edith_arch_updater.py**
```python
Line 15:  EDITH_DIR        = "/home/vaibhav/EDITH"
Line 22:  STATE_FILE       = "/home/vaibhav/.edith_arch_note_id"
```

#### **scripts/edith_arch_updater.py**
```python
Line 23:  EDITH_DIR     = "/home/vaibhav/EDITH"
Line 24:  ENV_FILE      = "/home/vaibhav/EDITH/.env"
Line 28:  STATE_FILE    = "/home/vaibhav/.edith_arch_note_id"
```

---

### Test Files

#### **test/test_integration.py**
```python
Line 13:  cd /home/vaibhav/EDITH  (in docstring)
Line 407: assert not is_dangerous("ls /home/vaibhav")
Line 413: score = compute_confidence("ls /home/vaibhav/files", "list the files")
```

#### **tests/test_voice_pipeline.py**
```python
Line 3:   Run: cd /home/vaibhav/EDITH && python -m pytest tests/test_voice_pipeline.py -v
```

---

## 2. `shell=True` SUBPROCESS CALLS

### Summary
- **Total Matches:** 14
- **File:** intent_dispatch.py (all instances)
- **Issue:** Security risk + unnecessary complexity
- **Classification:** All are local-only (marked "DISABLED on cloud")

### All Instances (intent_dispatch.py)

```python
Line 250:  # DISABLED on cloud: all shell=True subprocess calls below are local-only

Line 276:  r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=10)
           Context: ls command for directories/files

Line 286:  r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=5)
           Context: file listing

Line 296:  r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=5)
           Context: file listing

Line 321:  shell=True, capture_output=True, text=True, timeout=30
           Context: find with complex filter

Line 328:  shell=True, capture_output=True, text=True, timeout=30
           Context: find with complex filter

Line 360:  r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=20)
           Context: find command

Line 438:  r1 = subprocess.run("ping -c 3 -W 2 8.8.8.8 2>&1", shell=True, capture_output=True, text=True, timeout=15)
           Context: Network diagnostics

Line 441:  r2 = subprocess.run("ping -c 2 -W 2 google.com 2>&1 | tail -3", shell=True, capture_output=True, text=True, timeout=10)
           Context: Network diagnostics with pipe

Line 444:  r3 = subprocess.run("nslookup google.com 2>/dev/null | tail -4", shell=True, capture_output=True, text=True, timeout=8)
           Context: DNS diagnostics with pipe

Line 460:  r1 = subprocess.run("whoami && id && groups", shell=True, capture_output=True, text=True, timeout=5)
           Context: User/privilege info

Line 463:  r2 = subprocess.run("sudo -l 2>&1 | head -20", shell=True, capture_output=True, text=True, timeout=8)
           Context: Sudo capabilities with pipe

Line 468:  shell=True, capture_output=True, text=True, timeout=5
           Context: User/system info

Line 490:  r = subprocess.run(c, shell=True, capture_output=True, text=True, timeout=5)
           Context: Generic command execution loop
```

### Refactoring Required
1. `ping` → use `shlex.split()`
2. `nslookup` + pipes → use `socket.gethostbyname()` or `dns.resolver`
3. `find` with complex filters → use `pathlib.Path.glob()` + Python filters
4. Commands with pipes → break into separate calls and chain in Python

---

## 3. CURRENT CONFIG.PY APPROACH

### File Location
[config.py](config.py)

### Current Path Management Strategy

#### ✓ Good Practices
```python
# Line 51: Base path derived from __file__
EDITH_PATH = os.path.dirname(os.path.abspath(__file__))

# Uses environment variables with fallback
VENV_PATH = os.getenv("VENV_PATH", "/home/vaibhav/edith-env")
VENV_PYTHON = os.getenv("VENV_PYTHON", os.path.join(VENV_PATH, "bin/python"))

# Consistent use of os.path.join for subdirectories
MEMORY_DB_PATH = os.path.join(EDITH_PATH, "memory_db")
MEMORY_ARCHIVE_PATH = os.path.join(EDITH_PATH, "memory_archive.db")
NOTES_DIR = os.path.join(EDITH_PATH, "notes")
LOG_DIR = os.path.join(EDITH_PATH, "logs")
```

#### ✗ Issues
```python
# Line 62: Fallback to hardcoded path
VENV_PATH = os.getenv("VENV_PATH", "/home/vaibhav/edith-env")

# Line 204, 216: Secondary repos hardcoded
CODE_DIRS = [
    EDITH_PATH,
    "/home/vaibhav/Documents/Ayur-stock pro",  # ← Hardcoded
]

# Line 216, 221: Same pattern
REPOS = [
    EDITH_PATH,
    "/home/vaibhav/Documents/Ayur-stock pro",  # ← Hardcoded
]

# Line 371: Chatterbox venv hardcoded with fallback
CHATTERBOX_VENV_PYTHON = os.getenv("CHATTERBOX_VENV_PYTHON", "/home/vaibhav/chatterbox-env/bin/python3")
```

### Current Architecture
```
config.py
├─ EDITH_PATH (derived from __file__) ✓
├─ VENV_PATH (env var + fallback) ⚠
├─ Directory paths (relative to EDITH_PATH) ✓
│  ├─ MEMORY_DB_PATH
│  ├─ LOG_DIR
│  ├─ NOTES_DIR
│  └─ ...
├─ External repos (hardcoded) ✗
│  ├─ CODE_DIRS
│  └─ REPOS
└─ External venvs (env var + fallback) ⚠
   ├─ CHATTERBOX_VENV_PYTHON
   └─ PIPER_PATH
```

### Lazy Loading Pattern
```python
# Lines 270-285: Vault secret caching to avoid circular imports
_vault_cache = {}

def _get_vault_secret(key, default=""):
    """Lazy-load vault secrets to avoid circular import."""
    if key not in _vault_cache:
        try:
            import vault as v
            _vault_cache[key] = v.get_secret(key, default) or os.getenv(key, default)
        except Exception:
            _vault_cache[key] = os.getenv(key, default)
    return _vault_cache[key]
```

**Good for:** API keys, credentials  
**Bad for:** Path discovery — should be done at script startup, not lazy

---

## 4. RISK ASSESSMENT

### Refactoring Impact
| Category | Risk | Notes |
|----------|------|-------|
| **Shell scripts** | Medium | 6 files × 2-3 paths per file = ~15 replacements |
| **Systemd services** | High | 4 service files — if paths wrong, won't start |
| **Python modules** | Medium | 9 files — intent_dispatch.py has 6 instances |
| **Config files** | Medium | JSON files — syntax sensitive |
| **shell=True** | High | Security + portability; 14 replacements |

### Deployment Strategy
1. **Phase 1:** Centralize path discovery in config.py
2. **Phase 2:** Update .service files with dynamic paths (systemd EnvironmentFile)
3. **Phase 3:** Refactor shell=True → shell=False
4. **Phase 4:** Update shell scripts with environment variable substitution
5. **Phase 5:** Test on new machine to verify portability

---

## 5. KEY METRICS FOR TRACKING

| Metric | Current | Target |
|--------|---------|--------|
| Hardcoded paths | 100+ | 0 |
| shell=True calls | 14 | 0 |
| Config.py env vars | 3 | 8+ |
| Portable across machines | No | Yes |
| Service startup failures | Likely | Zero |

---

## 6. NEXT STEPS RECOMMENDED

1. **Create discovery module** (`path_discovery.py`):
   - Auto-detect EDITH_PATH, VENV_PATH, user home
   - Environment variable resolution
   - Fallback strategies

2. **Refactor config.py**:
   - Use discovery module
   - Move external repo paths to config
   - Add validation checks

3. **Update all shell scripts**:
   - Source from environment
   - Use `$EDITH_PATH`, `$PYTHON_VENV`, etc.

4. **Replace shell=True calls**:
   - Use pathlib + os.walk for file operations
   - Use subprocess with list args
   - Break pipes into sequential calls

5. **Update systemd services**:
   - Reference dynamic paths
   - Use EnvironmentFile=/etc/edith.env

6. **Test matrix**:
   - Different user home paths
   - Different venv locations
   - Cloud vs local modes

