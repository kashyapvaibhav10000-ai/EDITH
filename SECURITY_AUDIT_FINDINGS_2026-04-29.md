# EDITH Security Audit Report — 2026-04-29

## Executive Summary
Found **3 critical security issues** and several lesser concerns related to secrets management and shell execution. Most command execution paths are well-protected via dangerous pattern detection.

---

## FINDING 1: API Keys Exposed via os.getenv() Fallback

### ⚠️ **SEVERITY: MEDIUM – Secrets Management**

### Affected Files
| File | Line | Issue |
|------|------|-------|
| [smart_router.py](smart_router.py#L38-L41) | 38-41 | API keys fallback to os.getenv() vs vault-first |
| [chat_server.py](chat_server.py#L371) | 371 | Groq key: `vault.get_secret(...) or os.getenv(...)` |
| [voice.py](voice.py#L194) | 194 | Groq key: `vault.get_secret(...) or os.getenv(...)` |
| [voice.py](voice.py#L310) | 310 | Groq key: `vault.get_secret(...) or os.getenv(...)` |
| [vision.py](vision.py#L144) | 144 | Gemini key: `vault.get_secret(..., os.getenv(...))` |
| [email_reader.py](email_reader.py#L31-L32) | 31-32 | Gmail: both via fallback |
| [telegram_bot.py](telegram_bot.py#L34-L35) | 34-35 | Telegram: both via fallback |
| [config.py](config.py#L256) | 256 | Generic getter with fallback |

### Details
**Problem:** Code uses pattern `vault.get_secret(KEY) or os.getenv(KEY)`. This means:
1. If vault is empty/missing, **secrets can exist in plaintext in shell environment**
2. Environment variables are inherited by child processes and visible in `/proc/PID/environ`
3. No audit trail of which method provided the secret

**Code Example (risk):**
```python
# smart_router.py, lines 38-41 (CURRENT)
GROQ_KEY = vault.get_secret("GROQ_API_KEY", "") or os.getenv("GROQ_API_KEY", "")
GEMINI_KEY = vault.get_secret("GEMINI_API_KEY", "") or os.getenv("GEMINI_API_KEY", "")
NVIDIA_KEY = vault.get_secret("NVIDIA_API_KEY", "") or os.getenv("NVIDIA_API_KEY", "")
OPENROUTER_KEY = vault.get_secret("OPENROUTER_API_KEY", "") or os.getenv("OPENROUTER_API_KEY", "")
```

### Risk
- **Information Disclosure:** Secrets visible in environment, process listings
- **Privilege Escalation:** Child process subprocess can read parent env if running with elevated privs
- **No Audit:** Cannot distinguish between vault-sourced vs env-sourced secrets

### Recommendation
Change pattern from fallback to vault-only with explicit error:
```python
# PREFERRED: Vault-only (fail hard if not found)
GROQ_KEY = vault.get_secret("GROQ_API_KEY")
if not GROQ_KEY:
    raise ValueError("GROQ_API_KEY not in vault! Add via vault.py first.")

# ALTERNATIVE if env is temporary fallback:
GROQ_KEY = vault.get_secret("GROQ_API_KEY", "")
if not GROQ_KEY:
    GROQ_KEY = os.getenv("GROQ_API_KEY", "")
    LAN_LOGGER.warning("GROQ_API_KEY using environment fallback — migrate to vault soon!")
```

---

## FINDING 2: Shell Injection via subprocess.check_output(..., shell=True)

### ⚠️ **SEVERITY: CRITICAL – Command Injection**

### Affected Files
| File | Line | Vulnerability |
|------|------|----------------|
| [config.py](config.py#L28) | 28 | `shell=True` with pgrep command looking for WM |
| [config.py](config.py#L30) | 30 | `shell=True` reading `/proc/PID/environ` |
| [security_audit.py](security_audit.py#L10) | 10 | `shell=True` with arbitrary `cmd` parameter |

### Details

#### Issue A: config.py — X11 Authentication (Lines 28-30)
**Code:**
```python
# config.py, lines 28-30
pid = subprocess.check_output("pgrep -u $USER -x 'kwin_x11|plasmashell|gnome-shell|xfce4-session' | head -n 1", shell=True).decode().strip()
if pid:
    env_vars = subprocess.check_output(f"cat /proc/{pid}/environ", shell=True).split(b'\0')
```

**Problems:**
1. **Line 28:** `pgrep | head` — shell metacharacters (pipe, quotes) — **potential injection if $USER is attacker-controlled**
2. **Line 30:** `cat /proc/{pid}/environ` — **pid validation missing** — if `pid` is malicious string like `*/../../etc/passwd`, injection occurs
3. **Both use shell=True** — unnecessary, increases attack surface

**Attack Vector (theoretical):**
```python
# If $USER env var is compromised or pid is manipulated:
os.environ["USER"] = "user; rm -rf /tmp/*; echo"
# Then shell execution becomes: pgrep -u user; rm -rf /tmp/*; echo -x '...'
```

**Safe Pattern:**
```python
# FIXED: shell=False with list args
import subprocess
cmd = ["pgrep", "-u", os.environ.get("USER", "user"), "-x", "kwin_x11|plasmashell|gnome-shell|xfce4-session"]
result = subprocess.check_output(cmd, shell=False).decode().strip()
```

#### Issue B: security_audit.py — Arbitrary Command (Line 10)
**Code:**
```python
# security_audit.py, line 10
def run(cmd):
    r = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    return r.stdout.strip() or r.stderr.strip()
```

**Problem:**
- Any module calling `run()` can inject commands via `cmd` parameter
- `shell=True` enables full shell metacharacter interpretation
- **All calls to `run()` in security_audit.py are static string literals** (safe), BUT the function signature invites misuse

**Usage (all safe currently):**
```python
fw = run("sudo ufw status")
ps = run("ps aux | grep EDITH")
```

**Recommendation:** Use subprocess.run(shell=False) with list args:
```python
def run(cmd_list: list):
    r = subprocess.run(cmd_list, shell=False, capture_output=True, text=True)
    return r.stdout.strip() or r.stderr.strip()

# Call: run(["sudo", "ufw", "status"])
```

---

## FINDING 3: Agent Dangerous Pattern Detection Gaps

### ⚠️ **SEVERITY: MEDIUM – Code Execution Jailbreak**

### Pattern Coverage in [config.py](config.py#L192-L216)

**Hardcoded DANGEROUS_PATTERNS list:**
```python
DANGEROUS_PATTERNS = [
    "rm -rf /",
    "rm -rf ~",
    "rm -rf /*",
    "rm -rf .",
    "mkfs",
    "dd if=/dev",
    ":(){ :|:",       # fork bomb
    "> /dev/sda",
    "chmod -R 777 /",
    # ... 13 more
]
```

### Gaps
| Gap | Risk | Example Bypass |
|-----|------|---|
| **Whitespace variants** | Dangerous cmds with extra spaces skip detection | `rm  -rf  /` (detected as space-normalized but no normalization in actual check) |
| **Variable expansion** | Shell variables can obfuscate commands | `RM_CMD=rm; $RM_CMD -rf /` |
| **Quoted metacharacters** | Quoted pipes/redirects might bypass | `echo 'rm -rf /'` (actually safe, true — but precedent) |
| **Indirect execution via sudo** | SUID binaries could escalate | `sudo cat /etc/shadow` (vault intent blocked, but agent doesn't check this) |
| **Reverse shell patterns missing** | No detection for `bash -i >& /dev/tcp/...` | Attacker crafts reverse shell |

### Check Function Analysis [agent.py](agent.py#L149-L157)

```python
def is_dangerous(cmd):
    """Check if a command contains any dangerous patterns."""
    cmd_lower = cmd.lower().strip()
    cmd_nospace = cmd_lower.replace(" ", "")
    for pattern in DANGEROUS_PATTERNS:
        pattern_nospace = pattern.lower().replace(" ", "")
        if pattern.lower() in cmd_lower or pattern_nospace in cmd_nospace:
            return True
    if "|" in cmd and any(d in cmd_lower for d in ["rm", "dd", "mkfs", "shred", "wipefs"]):
        return True
    if ">" in cmd and any(f in cmd_lower for f in ["/etc/", "/dev/", "/boot/", "/usr/", "/bin/", "/sbin/"]):
        return True
    return False
```

**Strengths:**
- ✅ Whitespace normalization (`cmd_nospace`)
- ✅ Pipe detection with destructive command check
- ✅ Redirect to system paths blocked

**Weaknesses:**
- ❌ No regex — only string matching
- ❌ Variable expansion ($VAR, ${VAR}) not tested
- ❌ Command chaining after `;` not fully tested: `echo hello; rm -rf /` — detected (contains "rm -rf /") but...
- ❌ Backtick/command substitution: `` `rm -rf /` `` — might bypass

### Recommendation
Upgrade detection:
```python
import re

def is_dangerous(cmd):
    """Enhanced: detect obfuscated dangerous patterns."""
    cmd_lower = cmd.lower().strip()
    cmd_nospace = re.sub(r'\s+', '', cmd_lower)  # Normalize all whitespace
    
    # Check hardcoded patterns (existing)
    for pattern in DANGEROUS_PATTERNS:
        pattern_nospace = re.sub(r'\s+', '', pattern.lower())
        if pattern.lower() in cmd_lower or pattern_nospace in cmd_nospace:
            return True
    
    # Check shell metacharacters + destructive commands
    if "|" in cmd and any(d in cmd_lower for d in ["rm", "dd", "mkfs", "shred", "wipefs"]):
        return True
    if ">" in cmd and any(f in cmd_lower for f in ["/etc/", "/dev/", "/boot/"]):
        return True
    if ";" in cmd:
        # Check each statement after semicolon
        for stmt in cmd.split(";"):
            if is_dangerous(stmt):  # Recursive check
                return True
    
    # Detect command substitution patterns
    if "$(" in cmd or "`" in cmd:
        log.warning(f"Command substitution detected in: {cmd} — blocked for safety")
        return True
    
    # Detect variable expansion with dangerous patterns in quotes
    if re.search(r'\$\{?[A-Z_]+\}?', cmd) and any(p in cmd_lower for p in ["rm", "dd", "chmod"]):
        log.warning(f"Variable expansion + destructive command: {cmd} — blocked")
        return True
    
    return False
```

---

## FINDING 4: HITL Confirmation Gate — VERIFIED as Working

### ✅ **STATUS: SECURE**

### Verification Points
| Component | Status | Evidence |
|-----------|--------|----------|
| [intent_dispatch.py](intent_dispatch.py#L327-L328) | ✅ WORKING | Dangerous shell commands set pending action |
| [chat_server.py](chat_server.py#L252-L270) | ✅ ENFORCED | Checks pending action, requires YES/NO |
| [orchestrator.py](orchestrator.py#L745-L751) | ✅ ENFORCED | Manual mode also checks HITL |
| [agent.py](agent.py#L320-L326) | ✅ WORKING | Dangerous steps blocked with is_dangerous() |

### Flow
```
User: "run rm -rf /tmp/*"
  ↓
_handle_shell() detects not safe
  ↓
set_pending_action({"type": "shell", "cmd": cmd})
  ↓
UI shows: "⚠️ This could modify your system. Type YES to run or NO to cancel"
  ↓
User must reply "YES" to execute_pending_action()
  ↓
If YES → execute with sandbox (firejail if available)
If NO → cancelled
```

### Conclusion
HITL gate is **properly implemented**. No bypass found.

---

## FINDING 5: .env File Security

### Status: ✅ **NO PLAINTEXT SECRETS CHECKED IN**

**Findings:**
- [No .env file found](file_search: .env) in repository root
- `config.py` loads .env via `load_dotenv()` — **sensible design**
- Secrets properly vault-encrypted (see Finding 1 for vault usage needs improvement)

**Check:** Searched for shell-defined constants like `API_KEY = "sk-..."`
- ❌ Found no hardcoded API keys in Python constants
- ✅ Config properly uses vault/env pattern

---

## FINDING 6: Code Execution Sanitization in intent_dispatch

### ✅ **SAFE — Proper use of shlex.split()**

| Location | Code | Safety |
|----------|------|--------|
| [intent_dispatch.py L312](intent_dispatch.py#L312) | `subprocess.run(shlex.split(cmd), ...)` | ✅ shell=False implicit, safe |
| [intent_dispatch.py L888](intent_dispatch.py#L888) | `subprocess.run(shlex.split(cmd), ...)` | ✅ safe |
| [agent.py L320](agent.py#L320) | `subprocess.run(_get_sandboxed_command(shlex.split(...)))` | ✅ sandboxed + safe |

### Sandboxing via firejail
```python
def _get_sandboxed_command(cmd_list: list) -> list:
    if shutil.which("firejail"):
        return ["firejail", "--private-tmp", "--net=none"] + cmd_list
    log.warning("No firejail found — running as user")
    return cmd_list
```
✅ **Good:** Attempt to sandbox dangerous commands with firejail (network disabled, isolated /tmp)

---

## Summary Table

| Finding | Component | Severity | Status |
|---------|-----------|----------|--------|
| API key fallback pattern | Secrets mgmt | MEDIUM | ⚠️ Needs fix |
| shell=True in config.py | Code injection | CRITICAL | ⚠️ Needs fix |
| shell=True in security_audit.py | Code injection | MEDIUM | ⚠️ Design risk |
| Dangerous pattern gaps | Agent safety | MEDIUM | ⚠️ Incomplete regex |
| HITL confirmation gates | User safety | SECURE | ✅ Working |
| .env plaintext | Secrets | SECURE | ✅ No violations |
| shlex.split() usage | Command exec | SECURE | ✅ Proper |

---

## Recommendations (Priority Order)

### 🔴 CRITICAL
1. **Remove shell=True from config.py (lines 28, 30)**
   - Replace with subprocess.run(..., shell=False) + list args
   - Add validation for pid variable
   - Time: ~15 mins

### 🟠 HIGH
2. **Upgrade vault fallback pattern**
   - Remove `or os.getenv()` from all module initializers
   - Make API keys vault-required with explicit errors
   - Time: ~30 mins
   
3. **Fix security_audit.py shell=True risk**
   - Refactor run() function to use shell=False
   - Time: ~20 mins

### 🟡 MEDIUM
4. **Enhance agent.is_dangerous() detection**
   - Add regex patterns for obfuscation
   - Recursive check for command chaining
   - Add command substitution detection
   - Time: ~45 mins

### 🟢 NICE-TO-HAVE
5. **Add security audit tests**
   - Unit tests for dangerous pattern detection
   - Fuzzing for bypass attempts
   - Time: ~1 hour

---

## Files Requiring Changes
- [config.py](config.py) — Lines 28, 30, 256
- [smart_router.py](smart_router.py) — Lines 38-41
- [chat_server.py](chat_server.py) — Line 371
- [voice.py](voice.py) — Lines 194, 310
- [vision.py](vision.py) — Line 144
- [email_reader.py](email_reader.py) — Lines 31-32
- [telegram_bot.py](telegram_bot.py) — Lines 34-35, 40-41
- [security_audit.py](security_audit.py) — Line 10
- [agent.py](agent.py) — Lines 149-157 (enhancement)

---

**Report Generated:** 2026-04-29 by security audit tool
**Next Review:** After fixes applied
