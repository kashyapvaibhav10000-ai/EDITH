#!/usr/bin/env python3
"""
EDITH Architecture Auto-Updater
Runs on boot → scans EDITH codebase → generates fresh arch doc via Ollama → pushes to Joplin
"""

import os
import json
import requests
import subprocess
from datetime import datetime
from pathlib import Path

# ── CONFIG ────────────────────────────────────────────────────────────────────
EDITH_DIR        = os.path.expanduser("~/EDITH")
JOPLIN_TOKEN     = os.environ.get("JOPLIN_TOKEN", "")
JOPLIN_PORT      = 41184
JOPLIN_BASE      = f"http://localhost:{JOPLIN_PORT}"
NOTE_TITLE       = "EDITH Architecture — Auto Generated"
OLLAMA_MODEL     = "qwen2.5:1.5b"   # fast + light; change to gemma3:1b if needed
OLLAMA_URL       = "http://localhost:11434/api/generate"
STATE_FILE       = os.path.expanduser("~/.edith_arch_note_id")   # persists Joplin note ID
# ──────────────────────────────────────────────────────────────────────────────


def log(msg):
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"[{ts}] {msg}")


def scan_edith_codebase(edith_dir: str) -> dict:
    """Scan all .py files — collect name, line count, top-level functions/classes."""
    result = {}
    path = Path(edith_dir)
    if not path.exists():
        return result

    for pyfile in sorted(path.glob("*.py")):
        lines = pyfile.read_text(errors="ignore").splitlines()
        functions = [l.strip() for l in lines if l.startswith("def ") or l.startswith("class ")]
        result[pyfile.name] = {
            "lines": len(lines),
            "definitions": functions[:20],  # cap at 20 per file
        }
    return result


def build_prompt(scan: dict) -> str:
    """Build compact prompt for Ollama."""
    file_summary = []
    total_lines = 0
    for fname, info in scan.items():
        total_lines += info["lines"]
        defs = ", ".join(d.replace("def ", "").replace("class ", "⬡").split("(")[0]
                         for d in info["definitions"][:8])
        file_summary.append(f"- {fname} ({info['lines']} lines): {defs}")

    files_text = "\n".join(file_summary)
    today = datetime.now().strftime("%Y-%m-%d %H:%M")

    return f"""You are an expert Python architect. Analyze this EDITH AI assistant codebase scan and generate a concise architecture document.

SCAN DATE: {today}
TOTAL FILES: {len(scan)}
TOTAL LINES: {total_lines}

FILES:
{files_text}

Generate a markdown architecture document with these sections:
1. Project Summary (2-3 lines)
2. Module Map (table: Module | Purpose | Key Functions)
3. Architecture Layers (Input → Orchestration → Memory → Services → Output)
4. Key Design Patterns identified
5. Stats (files, lines, entry points)
6. Top 3 things to improve

Be concise. Use markdown tables. Max 600 words. Start with: # EDITH Architecture — {today}"""


def call_ollama(prompt: str) -> str:
    """Call local Ollama, stream response."""
    log(f"Calling Ollama ({OLLAMA_MODEL})...")
    try:
        resp = requests.post(OLLAMA_URL, json={
            "model": OLLAMA_MODEL,
            "prompt": prompt,
            "stream": False,
            "options": {"temperature": 0.3, "num_predict": 1200}
        }, timeout=120)
        resp.raise_for_status()
        return resp.json().get("response", "").strip()
    except Exception as e:
        log(f"Ollama error: {e}")
        return None


def joplin_get(endpoint: str) -> dict:
    r = requests.get(f"{JOPLIN_BASE}{endpoint}",
                     params={"token": JOPLIN_TOKEN}, timeout=10)
    return r.json() if r.ok else {}


def joplin_post(endpoint: str, data: dict) -> dict:
    r = requests.post(f"{JOPLIN_BASE}{endpoint}",
                      params={"token": JOPLIN_TOKEN},
                      json=data, timeout=10)
    return r.json() if r.ok else {}


def joplin_put(endpoint: str, data: dict) -> dict:
    r = requests.put(f"{JOPLIN_BASE}{endpoint}",
                     params={"token": JOPLIN_TOKEN},
                     json=data, timeout=10)
    return r.json() if r.ok else {}


def get_or_create_notebook(name: str) -> str:
    """Find notebook by name or create it. Returns ID."""
    data = joplin_get("/folders")
    for nb in data.get("items", []):
        if nb.get("title") == name:
            return nb["id"]
    # create
    nb = joplin_post("/folders", {"title": name})
    return nb.get("id")


def load_note_id() -> str | None:
    if os.path.exists(STATE_FILE):
        return open(STATE_FILE).read().strip() or None
    return None


def save_note_id(note_id: str):
    open(STATE_FILE, "w").write(note_id)


def note_exists(note_id: str) -> bool:
    r = requests.get(f"{JOPLIN_BASE}/notes/{note_id}",
                     params={"token": JOPLIN_TOKEN}, timeout=10)
    return r.ok


def push_to_joplin(content: str, notebook_id: str) -> bool:
    """Update existing note or create new one. Never duplicates."""
    note_id = load_note_id()

    if note_id and note_exists(note_id):
        log(f"Updating existing Joplin note: {note_id}")
        result = joplin_put(f"/notes/{note_id}", {
            "title": NOTE_TITLE,
            "body": content,
        })
        return bool(result.get("id"))
    else:
        log("Creating new Joplin note...")
        result = joplin_post("/notes", {
            "title": NOTE_TITLE,
            "body": content,
            "parent_id": notebook_id,
        })
        new_id = result.get("id")
        if new_id:
            save_note_id(new_id)
            log(f"Note created: {new_id}")
            return True
        return False


def wait_for_joplin(retries=10, delay=3) -> bool:
    """Wait for Joplin Web Clipper to be ready."""
    import time
    for i in range(retries):
        try:
            r = requests.get(f"{JOPLIN_BASE}/ping", timeout=3)
            if r.text == "JoplinClipperServer":
                return True
        except:
            pass
        log(f"Waiting for Joplin API... ({i+1}/{retries})")
        time.sleep(delay)
    return False


def main():
    log("=" * 50)
    log("EDITH Architecture Updater — Starting")
    log("=" * 50)

    # 1. Wait for Joplin
    if not wait_for_joplin():
        log("ERROR: Joplin not reachable on port 41184. Is it running?")
        return

    # 2. Scan codebase
    log(f"Scanning {EDITH_DIR}...")
    scan = scan_edith_codebase(EDITH_DIR)
    if not scan:
        log(f"ERROR: No .py files found in {EDITH_DIR}")
        return
    log(f"Found {len(scan)} Python files")

    # 3. Build prompt + call Ollama
    prompt = build_prompt(scan)
    arch_doc = call_ollama(prompt)
    if not arch_doc:
        log("ERROR: Ollama returned nothing. Using fallback static scan.")
        # Fallback — plain scan without LLM
        today = datetime.now().strftime("%Y-%m-%d %H:%M")
        lines = [f"# EDITH Architecture — {today}\n",
                 f"*Auto-generated static scan (Ollama unavailable)*\n",
                 f"**Files:** {len(scan)} | **Total lines:** {sum(v['lines'] for v in scan.values())}\n",
                 "\n## Module List\n"]
        for fname, info in scan.items():
            lines.append(f"- **{fname}** ({info['lines']} lines)")
        arch_doc = "\n".join(lines)

    log(f"Architecture doc generated ({len(arch_doc)} chars)")

    # 4. Get/create EDITH notebook
    notebook_id = get_or_create_notebook("EDITH")
    if not notebook_id:
        log("ERROR: Could not find or create EDITH notebook in Joplin")
        return
    log(f"Notebook ID: {notebook_id}")

    # 5. Push to Joplin
    success = push_to_joplin(arch_doc, notebook_id)
    if success:
        log("SUCCESS: Architecture doc updated in Joplin!")
    else:
        log("ERROR: Failed to push to Joplin")

    log("Done.")


if __name__ == "__main__":
    main()
