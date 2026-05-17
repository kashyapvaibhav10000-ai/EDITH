#!/usr/bin/env python3
"""
EDITH Architecture Auto-Updater v2.0
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Boot script: AST scan → Groq AI → Joplin
Fixes: chunking, offline fallback, boot order,
       no-dotenv, forced sync, context overflow
"""

import os
import sys
import ast
import json
import time
import socket
import requests
import textwrap
from pathlib import Path
from datetime import datetime
from collections import defaultdict

# ── CONFIG ─────────────────────────────────────────────────────────────────
EDITH_DIR     = "/home/vaibhav/EDITH"
ENV_FILE      = "/home/vaibhav/EDITH/.env"
JOPLIN_PORT   = 41184
JOPLIN_BASE   = f"http://localhost:{JOPLIN_PORT}"
NOTE_TITLE    = "EDITH — Architecture Doc (Auto)"
STATE_FILE    = "/home/vaibhav/.edith_arch_note_id"
GROQ_MODEL    = "llama-3.3-70b-versatile"
GROQ_URL      = "https://api.groq.com/openai/v1/chat/completions"
MAX_CHUNK_TOKENS = 3500   # safe under 6k/min limit
JOPLIN_WAIT_SEC  = 120     # max wait for Joplin
CHUNK_DELAY_SEC  = 12     # delay between Groq chunks
# ───────────────────────────────────────────────────────────────────────────

PRIORITY_FILES = [
    "orchestrator.py", "smart_router.py", "intent.py",
    "intent_dispatch.py", "chat_server.py", "background_daemon.py",
    "cognitive_profile.py", "smart_memory.py", "config.py",
    "vault.py", "circuit_breaker.py", "session.py",
    "council.py", "life_os.py", "agent.py", "context.py",
]

ARCH_PROMPT = """You are a senior software architect. Analyze this EDITH AI assistant codebase and generate a COMPLETE architecture document.

CODEBASE SCAN:
{scan_data}

Generate a thorough markdown document covering ALL sections below. Use actual function names, class names, and file names from the scan. Be concrete, not generic.

---
## 1. PROJECT OVERVIEW
- What does this software do? (purpose, problem it solves)
- Who are the target users?
- What is the tech stack (languages, frameworks, libraries, versions)?
- What is the project type?

## 2. FOLDER & FILE STRUCTURE
- List and explain EVERY folder and its role
- List and explain EVERY important file and what it does
- Identify entry points
- Identify config files

## 3. ARCHITECTURE & DESIGN PATTERNS
- What architectural pattern is used?
- What design patterns are implemented? (with concrete examples from code)
- How is the code organized?
- Is there separation of concerns?

## 4. DATA FLOW
- How does data flow from input to output?
- Trace a full request/response lifecycle
- What data transformations happen and where?
- Where is state managed?

## 5. DATABASE & DATA LAYER
- What database/storage is used?
- List all models/schemas/entities
- Describe all relationships
- How are migrations handled?

## 6. APIs & INTERFACES
- List EVERY API endpoint found (route, method, purpose)
- List all external APIs consumed
- Document CLI commands

## 7. AUTHENTICATION & AUTHORIZATION
- How is auth implemented?
- Which routes/resources are protected?

## 8. CONFIGURATION & ENVIRONMENT
- List all environment variables found and what they control
- How are secrets managed?

## 9. KEY FUNCTIONS & LOGIC
- Identify and explain the 10 most important functions
- Explain any complex algorithms
- Highlight tricky code sections

## 10. DEPENDENCIES
- List all major dependencies and why each is used
- Identify outdated, unused, or risky dependencies

## 11. TESTING
- What testing frameworks/tools are used?
- What types of tests exist?
- What is the test coverage like?

## 12. BUILD, DEPLOY & CI/CD
- How is the project built?
- How is it deployed?
- Are there CI/CD pipelines?

## 13. ERROR HANDLING & LOGGING
- How are errors caught and handled?
- What logging strategy is used?
- Are there monitoring/alerting integrations?

## 14. PERFORMANCE CONSIDERATIONS
- Are there caching strategies?
- Any rate limiting, queuing, or throttling?
- Identify potential performance bottlenecks

## 15. SECURITY
- What security measures are in place?
- Any known vulnerabilities or insecure patterns?
- How is sensitive data protected?

## 16. CODE QUALITY & CONVENTIONS
- What coding standards are followed?
- Is the code DRY?
- Comment/documentation quality

## 17. WHAT'S MISSING / IMPROVEMENTS
- What features or best practices are missing?
- What are the biggest technical debt areas?
- What would you improve first and why?
---
Be thorough. Use headers. Give concrete examples from actual code. Do not skip any section."""


def log(msg):
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"[{ts}] {msg}", flush=True)


# ── ENV PARSER (no dotenv needed) ──────────────────────────────────────────
def load_env(path=ENV_FILE):
    env = {}
    try:
        with open(path) as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                v = v.strip().strip('"').strip("'")
                env[k.strip()] = v
                os.environ[k.strip()] = v
    except Exception as e:
        log(f"Warning: Could not load .env: {e}")
    return env


# ── INTERNET CHECK ──────────────────────────────────────────────────────────
def internet_ok(host="api.groq.com", port=443, timeout=5) -> bool:
    try:
        socket.setdefaulttimeout(timeout)
        socket.socket(socket.AF_INET, socket.SOCK_STREAM).connect((host, port))
        return True
    except Exception:
        return False


# ── JOPLIN HELPERS ──────────────────────────────────────────────────────────
def wait_for_joplin(max_wait=JOPLIN_WAIT_SEC) -> bool:
    start = time.time()
    attempt = 0
    while time.time() - start < max_wait:
        attempt += 1
        try:
            r = requests.get(f"{JOPLIN_BASE}/ping",
                           params={"token": get_joplin_token()}, timeout=3)
            if r.text.strip() == "JoplinClipperServer":
                log(f"Joplin ready (attempt {attempt})")
                return True
        except Exception:
            pass
        log(f"Waiting for Joplin... ({int(time.time()-start)}s/{max_wait}s)")
        time.sleep(5)
    return False


def get_joplin_token() -> str:
    token = os.environ.get("JOPLIN_TOKEN", "")
    if not token:
        log("WARNING: JOPLIN_TOKEN is not set; Joplin sync will be skipped")
    return token


def joplin_req(method, endpoint, data=None):
    token = get_joplin_token()
    url = f"{JOPLIN_BASE}{endpoint}"
    params = {"token": token}
    try:
        if method == "GET":
            r = requests.get(url, params=params, timeout=10)
        elif method == "POST":
            r = requests.post(url, params=params, json=data, timeout=10)
        elif method == "PUT":
            r = requests.put(url, params=params, json=data, timeout=10)
        return r.json() if r.ok else {}
    except Exception as e:
        log(f"Joplin {method} {endpoint} failed: {e}")
        return {}


def get_or_create_notebook(name="EDITH") -> str:
    data = joplin_req("GET", "/folders")
    for nb in data.get("items", []):
        if nb.get("title") == name:
            return nb["id"]
    nb = joplin_req("POST", "/folders", {"title": name})
    return nb.get("id", "")


def load_note_id() -> str:
    try:
        if os.path.exists(STATE_FILE):
            return open(STATE_FILE).read().strip()
    except Exception:
        pass
    return ""


def save_note_id(note_id: str):
    try:
        open(STATE_FILE, "w").write(note_id)
    except Exception as e:
        log(f"Warning: Could not save note ID: {e}")


def note_exists(note_id: str) -> bool:
    if not note_id:
        return False
    r = requests.get(f"{JOPLIN_BASE}/notes/{note_id}",
                    params={"token": get_joplin_token()}, timeout=5)
    return r.ok


def push_to_joplin(content: str, notebook_id: str) -> bool:
    note_id = load_note_id()
    if note_id and note_exists(note_id):
        log(f"Updating note {note_id[:8]}...")
        result = joplin_req("PUT", f"/notes/{note_id}", {
            "title": NOTE_TITLE,
            "body": content,
        })
        success = bool(result.get("id"))
    else:
        log("Creating new note...")
        result = joplin_req("POST", "/notes", {
            "title": NOTE_TITLE,
            "body": content,
            "parent_id": notebook_id,
        })
        new_id = result.get("id", "")
        if new_id:
            save_note_id(new_id)
            success = True
        else:
            success = False

    # Force Joplin sync → Dropbox → phone gets update fast
    if success:
        try:
            requests.post(f"{JOPLIN_BASE}/synchronizer",
                        params={"token": get_joplin_token()}, timeout=5)
            log("Joplin sync triggered")
        except Exception:
            pass

    return success


# ── AST SCANNER ─────────────────────────────────────────────────────────────
class FileScanner:
    def __init__(self, filepath: str):
        self.path = filepath
        self.name = Path(filepath).name
        self.source = ""
        self.tree = None
        self.error = None

    def parse(self):
        try:
            self.source = open(self.path, errors="ignore").read()
            self.tree = ast.parse(self.source)
        except Exception as e:
            self.error = str(e)
        return self

    def get_classes(self) -> list:
        if not self.tree:
            return []
        result = []
        for node in ast.walk(self.tree):
            if isinstance(node, ast.ClassDef):
                methods = [n.name for n in ast.walk(node)
                          if isinstance(n, ast.FunctionDef)]
                bases = [ast.unparse(b) for b in node.bases] if node.bases else []
                doc = ast.get_docstring(node) or ""
                result.append({
                    "name": node.name,
                    "bases": bases,
                    "methods": methods[:15],
                    "doc": doc[:150],
                    "line": node.lineno,
                })
        return result

    def get_functions(self) -> list:
        if not self.tree:
            return []
        result = []
        for node in ast.walk(self.tree):
            if isinstance(node, ast.FunctionDef):
                args = [a.arg for a in node.args.args]
                doc = ast.get_docstring(node) or ""
                decorators = []
                for d in node.decorator_list:
                    try:
                        decorators.append(ast.unparse(d))
                    except Exception:
                        pass
                result.append({
                    "name": node.name,
                    "args": args[:8],
                    "doc": doc[:120],
                    "decorators": decorators,
                    "line": node.lineno,
                })
        return result[:30]

    def get_imports(self) -> list:
        if not self.tree:
            return []
        imports = []
        for node in ast.walk(self.tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    imports.append(alias.name)
            elif isinstance(node, ast.ImportFrom):
                mod = node.module or ""
                imports.append(mod)
        return list(set(imports))[:20]

    def get_api_endpoints(self) -> list:
        """Find FastAPI route decorators."""
        if not self.tree:
            return []
        endpoints = []
        for node in ast.walk(self.tree):
            if isinstance(node, ast.FunctionDef):
                for dec in node.decorator_list:
                    try:
                        dec_str = ast.unparse(dec)
                        if any(m in dec_str for m in
                               [".get(", ".post(", ".put(",
                                ".delete(", ".patch("]):
                            endpoints.append({
                                "decorator": dec_str,
                                "function": node.name,
                                "line": node.lineno,
                            })
                    except Exception:
                        pass
        return endpoints

    def get_env_vars(self) -> list:
        """Find all os.getenv() / os.environ calls."""
        if not self.tree:
            return []
        env_vars = []
        for node in ast.walk(self.tree):
            if isinstance(node, ast.Call):
                try:
                    call_str = ast.unparse(node)
                    if "os.getenv(" in call_str or "os.environ" in call_str:
                        if node.args:
                            val = ast.unparse(node.args[0]).strip("'\"")
                            env_vars.append(val)
                except Exception:
                    pass
        return list(set(env_vars))

    def get_try_excepts(self) -> int:
        """Count try/except blocks."""
        if not self.tree:
            return 0
        return sum(1 for n in ast.walk(self.tree)
                  if isinstance(n, ast.Try))

    def get_todos(self) -> list:
        """Find TODO/FIXME/HACK comments."""
        todos = []
        for i, line in enumerate(self.source.splitlines(), 1):
            if any(t in line.upper() for t in ["TODO", "FIXME", "HACK", "XXX"]):
                todos.append(f"L{i}: {line.strip()[:80]}")
        return todos[:5]

    def get_complexity(self) -> int:
        """Rough cyclomatic complexity."""
        if not self.tree:
            return 0
        count = 0
        for node in ast.walk(self.tree):
            if isinstance(node, (ast.If, ast.For, ast.While,
                                ast.ExceptHandler, ast.With,
                                ast.Assert, ast.comprehension)):
                count += 1
        return count


def scan_codebase(edith_dir: str) -> dict:
    """Full AST scan of EDITH codebase."""
    result = {
        "scan_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "files": {},
        "all_endpoints": [],
        "all_env_vars": [],
        "total_lines": 0,
        "total_functions": 0,
        "total_classes": 0,
        "total_try_excepts": 0,
        "folders": [],
        "requirements": [],
    }

    path = Path(edith_dir)
    if not path.exists():
        log(f"ERROR: {edith_dir} not found")
        return result

    # Scan folders
    result["folders"] = [
        f.name for f in sorted(path.iterdir())
        if f.is_dir() and not f.name.startswith(".")
    ]

    # Read requirements.txt
    req_file = path / "requirements.txt"
    if req_file.exists():
        lines = req_file.read_text().splitlines()
        result["requirements"] = [l for l in lines
                                  if l and not l.startswith("#")][:50]

    # Scan Python files — priority first
    all_py = sorted(path.glob("*.py"))
    priority = [p for p in all_py if p.name in PRIORITY_FILES]
    rest = [p for p in all_py if p.name not in PRIORITY_FILES]
    ordered = priority + rest

    for pyfile in ordered:
        scanner = FileScanner(str(pyfile)).parse()
        lines = len(scanner.source.splitlines())
        functions = scanner.get_functions()
        classes = scanner.get_classes()
        endpoints = scanner.get_api_endpoints()
        env_vars = scanner.get_env_vars()
        try_excepts = scanner.get_try_excepts()

        result["total_lines"] += lines
        result["total_functions"] += len(functions)
        result["total_classes"] += len(classes)
        result["total_try_excepts"] += try_excepts
        result["all_endpoints"].extend(
            [{**e, "file": pyfile.name} for e in endpoints])
        result["all_env_vars"].extend(env_vars)

        result["files"][pyfile.name] = {
            "lines": lines,
            "functions": functions,
            "classes": classes,
            "imports": scanner.get_imports(),
            "endpoints": endpoints,
            "env_vars": env_vars,
            "try_excepts": try_excepts,
            "todos": scanner.get_todos(),
            "complexity": scanner.get_complexity(),
            "error": scanner.error,
        }

    result["all_env_vars"] = list(set(result["all_env_vars"]))
    return result


# ── TOKEN ESTIMATOR ─────────────────────────────────────────────────────────
def estimate_tokens(text: str) -> int:
    return len(text) // 4  # ~4 chars per token


def build_scan_text(scan: dict) -> str:
    """Convert scan dict to readable text for Groq."""
    lines = []
    lines.append(f"SCAN TIME: {scan['scan_time']}")
    lines.append(f"TOTAL FILES: {len(scan['files'])}")
    lines.append(f"TOTAL LINES: {scan['total_lines']}")
    lines.append(f"TOTAL FUNCTIONS: {scan['total_functions']}")
    lines.append(f"TOTAL CLASSES: {scan['total_classes']}")
    lines.append(f"TOTAL TRY/EXCEPTS: {scan['total_try_excepts']}")
    lines.append(f"\nFOLDERS: {', '.join(scan['folders'])}")

    lines.append(f"\nAPI ENDPOINTS ({len(scan['all_endpoints'])}):")
    for ep in scan["all_endpoints"]:
        lines.append(f"  {ep['file']} → {ep['decorator']} → {ep['function']}()")

    lines.append(f"\nENV VARS FOUND: {', '.join(scan['all_env_vars'])}")

    lines.append(f"\nREQUIREMENTS (first 30):")
    for r in scan["requirements"][:30]:
        lines.append(f"  {r}")

    lines.append("\nFILE DETAILS:")
    for fname, info in scan["files"].items():
        lines.append(f"\n{'='*50}")
        lines.append(f"FILE: {fname} ({info['lines']} lines, "
                    f"complexity={info['complexity']}, "
                    f"try/except={info['try_excepts']})")

        if info["error"]:
            lines.append(f"  PARSE ERROR: {info['error']}")
            continue

        if info["imports"]:
            lines.append(f"  IMPORTS: {', '.join(info['imports'][:10])}")

        if info["classes"]:
            for cls in info["classes"]:
                lines.append(f"  CLASS {cls['name']}"
                           f"({', '.join(cls['bases'])})")
                if cls["doc"]:
                    lines.append(f"    doc: {cls['doc']}")
                if cls["methods"]:
                    lines.append(f"    methods: {', '.join(cls['methods'])}")

        if info["functions"]:
            for fn in info["functions"][:15]:
                dec = ""
                if fn["decorators"]:
                    dec = f" [{', '.join(fn['decorators'][:2])}]"
                args = ", ".join(fn["args"])
                lines.append(f"  def {fn['name']}({args}){dec}"
                           f" L{fn['line']}")
                if fn["doc"]:
                    lines.append(f"    → {fn['doc'][:100]}")

        if info["env_vars"]:
            lines.append(f"  ENV_VARS: {', '.join(info['env_vars'])}")

        if info["todos"]:
            lines.append(f"  TODOs: {'; '.join(info['todos'])}")

    return "\n".join(lines)


# ── GROQ CALLER ─────────────────────────────────────────────────────────────
def call_groq(prompt: str, api_key: str) -> str:
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": GROQ_MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.3,
        "max_tokens": 4000,
    }
    try:
        r = requests.post(GROQ_URL, headers=headers,
                         json=payload, timeout=90)
        r.raise_for_status()
        return r.json()["choices"][0]["message"]["content"]
    except requests.exceptions.HTTPError as e:
        if r.status_code == 429:
            log("Rate limit hit — waiting 60s...")
            time.sleep(60)
            return call_groq(prompt, api_key)  # retry once
        log(f"Groq HTTP error: {e}")
        return ""
    except Exception as e:
        log(f"Groq error: {e}")
        return ""


def generate_with_groq(scan_text: str, api_key: str) -> str:
    """Send scan to Groq. Chunk if too large."""
    total_tokens = estimate_tokens(scan_text)
    log(f"Scan text: ~{total_tokens} tokens")

    # If fits in one request
    if total_tokens <= MAX_CHUNK_TOKENS:
        log("Single Groq request...")
        prompt = ARCH_PROMPT.format(scan_data=scan_text)
        return call_groq(prompt, api_key)

    # Need to chunk — split files into groups
    log(f"Large scan — chunking into pieces...")
    file_blocks = scan_text.split("\n" + "="*50)
    header = file_blocks[0]  # stats + endpoints + env vars

    chunks = []
    current = header
    for block in file_blocks[1:]:
        test = current + "\n" + "="*50 + block
        if estimate_tokens(test) > MAX_CHUNK_TOKENS:
            chunks.append(current)
            current = header + "\n" + "="*50 + block
        else:
            current = test
    chunks.append(current)

    log(f"Split into {len(chunks)} chunks")

    # First chunk: full 17-section analysis
    responses = []
    first_prompt = ARCH_PROMPT.format(scan_data=chunks[0])
    log(f"Chunk 1/{len(chunks)} → Groq...")
    resp = call_groq(first_prompt, api_key)
    if resp:
        responses.append(resp)

    # Remaining chunks: supplement/expand
    for i, chunk in enumerate(chunks[1:], 2):
        time.sleep(CHUNK_DELAY_SEC)
        log(f"Chunk {i}/{len(chunks)} → Groq...")
        supp_prompt = f"""You are continuing an architecture analysis of EDITH AI assistant.
Here are MORE files from the codebase not covered yet:

{chunk}

Supplement the previous analysis. Add any new functions, classes, patterns, or issues found.
Focus on sections: Key Functions, Dependencies, Error Handling, Security, Code Quality.
Be concise — only add what's new."""
        resp = call_groq(supp_prompt, api_key)
        if resp:
            responses.append(f"\n\n---\n## Additional Analysis (Files Batch {i})\n\n{resp}")

    return "\n".join(responses)


# ── OFFLINE FALLBACK ────────────────────────────────────────────────────────
def generate_static_doc(scan: dict) -> str:
    """Pure AST doc — no AI. Used when offline."""
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    lines = []
    lines.append(f"# EDITH Architecture — {now}")
    lines.append(f"\n> *Static scan (offline mode — no AI)*\n")

    lines.append("## Summary Stats")
    lines.append(f"| Metric | Value |")
    lines.append(f"|--------|-------|")
    lines.append(f"| Python Files | {len(scan['files'])} |")
    lines.append(f"| Total Lines | {scan['total_lines']} |")
    lines.append(f"| Total Functions | {scan['total_functions']} |")
    lines.append(f"| Total Classes | {scan['total_classes']} |")
    lines.append(f"| Try/Except Blocks | {scan['total_try_excepts']} |")
    lines.append(f"| API Endpoints | {len(scan['all_endpoints'])} |")

    lines.append("\n## API Endpoints")
    for ep in scan["all_endpoints"]:
        lines.append(f"- `{ep['file']}` → `{ep['decorator']}` → `{ep['function']}()`")

    lines.append("\n## Environment Variables")
    for ev in sorted(scan["all_env_vars"]):
        lines.append(f"- `{ev}`")

    lines.append("\n## File Map")
    lines.append("| File | Lines | Functions | Classes | Complexity |")
    lines.append("|------|-------|-----------|---------|------------|")
    for fname, info in scan["files"].items():
        lines.append(
            f"| {fname} | {info['lines']} | "
            f"{len(info['functions'])} | "
            f"{len(info['classes'])} | "
            f"{info['complexity']} |"
        )

    lines.append("\n## Key Functions per File")
    for fname, info in list(scan["files"].items())[:20]:
        if info["functions"]:
            lines.append(f"\n### {fname}")
            for fn in info["functions"][:8]:
                args = ", ".join(fn["args"])
                lines.append(f"- `{fn['name']}({args})`"
                           + (f" — {fn['doc'][:80]}" if fn["doc"] else ""))

    lines.append("\n## TODOs Found")
    for fname, info in scan["files"].items():
        for todo in info["todos"]:
            lines.append(f"- **{fname}**: {todo}")

    return "\n".join(lines)


# ── MAIN ────────────────────────────────────────────────────────────────────
def main():
    log("=" * 55)
    log("EDITH Architecture Updater v2.0 — Starting")
    log("=" * 55)

    # 1. Load env
    env = load_env()
    groq_key = (env.get("GROQ_ARCH_KEY") or
                env.get("GROQ_API_KEY") or
                os.environ.get("GROQ_ARCH_KEY") or
                os.environ.get("GROQ_API_KEY", ""))

    # 2. Wait for Joplin
    log("Waiting for Joplin Web Clipper...")
    if not wait_for_joplin():
        log("ERROR: Joplin not reachable after 60s. Abort.")
        sys.exit(1)

    # 3. AST Scan
    log(f"Scanning {EDITH_DIR}...")
    scan = scan_codebase(EDITH_DIR)
    log(f"Scan complete: {len(scan['files'])} files, "
        f"{scan['total_lines']} lines, "
        f"{scan['total_functions']} functions, "
        f"{len(scan['all_endpoints'])} endpoints")

    # 4. Generate doc
    scan_text = build_scan_text(scan)

    online = internet_ok()
    log(f"Internet: {'YES' if online else 'NO (offline fallback)'}")

    if online and groq_key:
        log(f"Using Groq ({GROQ_MODEL})...")
        arch_doc = generate_with_groq(scan_text, groq_key)
        if not arch_doc:
            log("Groq failed — using static fallback")
            arch_doc = generate_static_doc(scan)
        else:
            # Prepend timestamp header
            now = datetime.now().strftime("%Y-%m-%d %H:%M")
            arch_doc = (f"# EDITH Architecture — {now}\n"
                       f"> *AI-generated via Groq {GROQ_MODEL}*\n\n"
                       + arch_doc)
    elif online and not groq_key:
        log("WARNING: No GROQ_ARCH_KEY found in .env — using static doc")
        arch_doc = generate_static_doc(scan)
    else:
        log("Offline mode — static AST doc")
        arch_doc = generate_static_doc(scan)

    log(f"Doc generated: {len(arch_doc)} chars")

    # 5. Push to Joplin
    notebook_id = get_or_create_notebook("EDITH")
    if not notebook_id:
        log("ERROR: Could not get EDITH notebook")
        sys.exit(1)

    success = push_to_joplin(arch_doc, notebook_id)
    if success:
        log("SUCCESS: Architecture doc updated in Joplin!")
        log("Dropbox sync triggered — phone update in ~1 min")
    else:
        log("ERROR: Failed to push to Joplin")
        sys.exit(1)

    log("Done.")


if __name__ == "__main__":
    main()
