"""
repo_dna.py — EDITH competitive intelligence engine.
Analyzes GitHub repos: what to steal, skip, watch.
Fetch chain: git clone → GitHub MCP → RepoFetchError
Results cached in memory_archive.db (7-day TTL).
"""

import hashlib
import json
import logging
import os
import re
import shutil
import sqlite3
import subprocess
import tempfile
from datetime import datetime, timedelta, timezone
from typing import Optional

from config import EDITH_PATH, MEMORY_ARCHIVE_PATH
import smart_router

logger = logging.getLogger("edith")

_CACHE_TTL_DAYS = 7
_TOP_FILES_COUNT = 10
_MAX_FILE_CHARS = 3_000  # per-file cap — keeps total prompt under Groq's payload limit
_TMP_PREFIX = "edith_repo_"
_MIN_CONTENT_CHARS = 1000
_GIT_BIN = "/usr/bin/git"  # full path — service env may not have /usr/bin in PATH

# File scoring weights
_FILE_SCORES = {
    "readme": 10,
    "requirements": 8,
    ".md": 6,
    "main.py": 7,
    "app.py": 7,
    "core": 7,
    "test": -3,
    ".lock": -10,
    "node_modules": -10,
    "dist/": -10,
    "build/": -10,
}

_ANALYSIS_SCHEMA = {
    "repo_url": "",
    "repo_name": "",
    "analyzed_at": "",
    "steal_this": [],
    "skip_this": [],
    "watch_this": [],
    "architecture_delta": "",
    "quick_wins": [],
    "summary": "",
    "strategic_gaps": [],
}


class RepoFetchError(Exception):
    pass


class RepoAnalysisError(Exception):
    pass


# ── EDITH self-context (dynamic, never hardcoded) ─────────────────────────────

_EDITH_CONTEXT_MAX_CHARS = 8_000   # ~2k tokens — Groq TPM=12k, needs headroom for files
_EDITH_CONTEXT_MAX_FILE_CHARS = 1_000  # cap per file in context
_EDITH_CONTEXT_SKIP_IF_LARGER = 3_000  # skip generated/config files
# Exclude self + analysis scaffold files that confuse LLM with schema JSON
_EDITH_CONTEXT_EXCLUDE = {
    'repo_dna.py', 'test_harness.py', 'dashboard.py',
}


def _build_edith_context() -> str:
    """Dynamically reads EDITH's own codebase to build context. Never hardcoded.
    EXCLUDES repo_dna.py itself (contains schema JSON that confuses LLM).
    Capped at _EDITH_CONTEXT_MAX_CHARS to avoid LLM context overflow."""
    edith_dir = os.path.dirname(os.path.abspath(__file__))
    sections = []

    # 1. Python module summaries — capped per file, skip large/excluded files
    sections.append("## EDITH EXISTING MODULES (auto-scanned):")
    py_files = sorted([
        f for f in os.listdir(edith_dir)
        if f.endswith('.py') and not f.startswith('__') and f not in _EDITH_CONTEXT_EXCLUDE
    ])
    for fname in py_files:
        fpath = os.path.join(edith_dir, fname)
        try:
            fsize = os.path.getsize(fpath)
            if fsize > _EDITH_CONTEXT_SKIP_IF_LARGER * 4:  # bytes ≈ chars for ASCII
                sections.append(f"\n### {fname}: [large file, skipped]")
                continue
            with open(fpath, 'r', errors='ignore') as f:
                content = f.read(_EDITH_CONTEXT_MAX_FILE_CHARS)
            sections.append(f"\n### {fname}:\n{content}")
        except Exception:
            pass

    # 2. CLAUDE.md — architecture + known gaps (capped)
    claude_md = os.path.join(edith_dir, 'CLAUDE.md')
    if os.path.exists(claude_md):
        with open(claude_md, 'r', errors='ignore') as f:
            sections.append(f"\n## CLAUDE.md (known gaps + architecture):\n{f.read()[:3000]}")

    # 3. requirements.txt — current stack (first 40 lines only)
    req_txt = os.path.join(edith_dir, 'requirements.txt')
    if os.path.exists(req_txt):
        with open(req_txt, 'r', errors='ignore') as f:
            sections.append(f"\n## CURRENT DEPENDENCIES:\n{''.join(f.readlines()[:40])}")

    full = '\n'.join(sections)
    if len(full) > _EDITH_CONTEXT_MAX_CHARS:
        full = full[:_EDITH_CONTEXT_MAX_CHARS] + "\n... [context capped]"
    return full


def _build_edith_context_summary() -> str:
    """Short version — module names + CLAUDE.md gaps only. For comparison prompt."""
    edith_dir = os.path.dirname(os.path.abspath(__file__))
    py_files = sorted([f for f in os.listdir(edith_dir) if f.endswith('.py') and not f.startswith('__')])
    claude_md_path = os.path.join(edith_dir, 'CLAUDE.md')
    claude_md = ""
    if os.path.exists(claude_md_path):
        with open(claude_md_path, 'r', errors='ignore') as f:
            claude_md = f.read()[:3000]
    return f"Modules: {', '.join(py_files)}\n\nCLAUDE.md:\n{claude_md}"


def _build_system_prompt() -> str:
    edith_context = _build_edith_context()
    return f"""You are EDITH's competitive intelligence engine.
EDITH is a personal AI operating system built in Python for a solo developer.

=== EDITH CODEBASE (CONTEXT ONLY — DO NOT REPRODUCE OR ANALYZE THIS) ===
The EDITH codebase below is provided solely so you know what EDITH ALREADY HAS.
Do NOT describe it. Do NOT include it in output. Use it only to judge gaps.

{edith_context}

=== END EDITH CODEBASE ===

CRITICAL RULES:
- The EDITH codebase above is for CONTEXT ONLY. Do NOT reproduce it in output.
- Analyze ONLY the TARGET REPO files in the user message.
- TARGET REPO may be ANY language (Rust, Go, TypeScript, etc.) — that is fine.
  Extract ARCHITECTURAL PATTERNS and ALGORITHMS, not raw code. Ask: "what does this do, and can EDITH do it in Python?"
- steal_this = ideas/patterns/features in TARGET REPO that EDITH lacks — even if written in Rust/TS, describe how to implement in Python
- skip_this = things not worth porting (UI-only, platform-specific, already in EDITH)
- watch_this = interesting ideas to monitor but not steal yet
- quick_wins = patterns that are <100 lines to implement in Python in EDITH
- summary = ALWAYS write 2-3 sentences describing what the TARGET REPO does and EDITH's positioning vs it. NEVER leave empty.
- Be specific — name exact file/function from TARGET REPO, then describe Python equivalent
- EDITH is Python only, CPU only, 8GB RAM, single developer
- effort=low: <100 lines in existing EDITH module
- effort=medium: new module (~200-500 lines)
- effort=high: multi-module refactor or cloud dependency
- steal_this MUST have at least 3 items. If repo is genuinely poor, explain in skip_this instead.
- Return ONLY valid JSON. No markdown fences. No prose outside JSON.

Schema:
{{
  "repo_url": "",
  "repo_name": "",
  "analyzed_at": "",
  "steal_this": [{{"title": "", "description": "", "file_hint": "", "effort": "low|medium|high"}}],
  "skip_this": [{{"title": "", "reason": ""}}],
  "watch_this": [{{"title": "", "description": ""}}],
  "architecture_delta": "",
  "quick_wins": [{{"title": "", "description": "", "effort": "low"}}],
  "summary": ""
}}"""


# ── Cache ──────────────────────────────────────────────────────────────────────

def _get_db() -> sqlite3.Connection:
    conn = sqlite3.connect(MEMORY_ARCHIVE_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("""
        CREATE TABLE IF NOT EXISTS repo_analyses (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            repo_url    TEXT NOT NULL,
            repo_name   TEXT NOT NULL,
            commit_sha  TEXT NOT NULL,
            analysis_json TEXT NOT NULL,
            created_at  TEXT NOT NULL
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS watched_repos (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            repo_url     TEXT UNIQUE NOT NULL,
            repo_name    TEXT NOT NULL,
            added_at     TEXT NOT NULL,
            last_checked TEXT,
            last_sha     TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS adapted_items (
            repo_url    TEXT NOT NULL,
            capability  TEXT NOT NULL,
            adapted_at  TEXT NOT NULL,
            target_file TEXT NOT NULL,
            PRIMARY KEY (repo_url, capability)
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS analysis_snapshots (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            repo_url      TEXT NOT NULL,
            commit_sha    TEXT NOT NULL,
            snapshot_json TEXT NOT NULL,
            analyzed_at   TEXT NOT NULL
        )
    """)
    conn.commit()
    # Session 8: idempotent column additions for success tracking
    for _col_sql in [
        "ALTER TABLE adapted_items ADD COLUMN outcome TEXT",
        "ALTER TABLE adapted_items ADD COLUMN rated_at TEXT",
        "ALTER TABLE adapted_items ADD COLUMN notes TEXT",
    ]:
        try:
            conn.execute(_col_sql)
            conn.commit()
        except Exception:
            pass
    return conn


def _cache_lookup(repo_url: str, commit_sha: str) -> Optional[dict]:
    with _get_db() as conn:
        cutoff = (datetime.now(timezone.utc) - timedelta(days=_CACHE_TTL_DAYS)).isoformat()
        row = conn.execute(
            "SELECT analysis_json, created_at FROM repo_analyses "
            "WHERE repo_url = ? AND commit_sha = ? AND created_at > ? "
            "ORDER BY created_at DESC LIMIT 1",
            (repo_url, commit_sha, cutoff),
        ).fetchone()
        if row:
            return json.loads(row["analysis_json"])
    return None


def _cache_store(repo_url: str, repo_name: str, commit_sha: str, analysis: dict) -> None:
    with _get_db() as conn:
        conn.execute(
            "INSERT INTO repo_analyses (repo_url, repo_name, commit_sha, analysis_json, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (repo_url, repo_name, commit_sha, json.dumps(analysis), datetime.now(timezone.utc).isoformat()),
        )
        conn.commit()


# ── Trend snapshots ────────────────────────────────────────────────────────────

def _save_snapshot(repo_url: str, commit_sha: str, analysis: dict) -> None:
    """Store snapshot; skip if last snapshot has same commit_sha; prune to 10."""
    with _get_db() as conn:
        last = conn.execute(
            "SELECT commit_sha FROM analysis_snapshots WHERE repo_url = ? "
            "ORDER BY analyzed_at DESC LIMIT 1",
            (repo_url,),
        ).fetchone()
        if last and last["commit_sha"] == commit_sha:
            return  # same commit — no new snapshot
        conn.execute(
            "INSERT INTO analysis_snapshots (repo_url, commit_sha, snapshot_json, analyzed_at) "
            "VALUES (?, ?, ?, ?)",
            (repo_url, commit_sha, json.dumps(analysis), datetime.now(timezone.utc).isoformat()),
        )
        # Prune: keep last 10 per repo
        conn.execute(
            "DELETE FROM analysis_snapshots WHERE repo_url = ? AND id NOT IN ("
            "  SELECT id FROM analysis_snapshots WHERE repo_url = ? "
            "  ORDER BY analyzed_at DESC LIMIT 10"
            ")",
            (repo_url, repo_url),
        )
        conn.commit()


def get_previous_snapshot(repo_url: str) -> Optional[dict]:
    """Return the most-recent saved snapshot for this repo, or None.
    Called BEFORE _save_snapshot in analyze_repo, so the current run's snapshot
    has not been saved yet — row[0] is the prior run's snapshot."""
    with _get_db() as conn:
        row = conn.execute(
            "SELECT snapshot_json FROM analysis_snapshots WHERE repo_url = ? "
            "ORDER BY analyzed_at DESC LIMIT 1",
            (repo_url,),
        ).fetchone()
    if row is None:
        return None
    return json.loads(row["snapshot_json"])


def _backfill_snapshots() -> None:
    """Populate analysis_snapshots from repo_analyses rows that have no snapshot.
    Runs once at startup — idempotent, skips repos already having a snapshot."""
    with _get_db() as conn:
        analyses = conn.execute(
            "SELECT repo_url, commit_sha, analysis_json FROM repo_analyses "
            "ORDER BY created_at ASC"
        ).fetchall()
        for row in analyses:
            existing = conn.execute(
                "SELECT 1 FROM analysis_snapshots WHERE repo_url = ? AND commit_sha = ?",
                (row["repo_url"], row["commit_sha"]),
            ).fetchone()
            if existing:
                continue
            conn.execute(
                "INSERT INTO analysis_snapshots (repo_url, commit_sha, snapshot_json, analyzed_at) "
                "VALUES (?, ?, ?, ?)",
                (
                    row["repo_url"],
                    row["commit_sha"],
                    row["analysis_json"],
                    datetime.now(timezone.utc).isoformat(),
                ),
            )
        conn.commit()
    logger.info("[repo_dna] snapshot backfill complete (%d analyses checked)", len(analyses))


def diff_analyses(current: dict, previous: dict) -> dict:
    """Diff two analyses by title (steal_this) / capability (strategic_gaps)."""
    def _steal_key(item: dict) -> str:
        return (item.get("title") or item.get("capability") or "").lower().strip()

    def _gap_key(item: dict) -> str:
        return (item.get("capability") or item.get("title") or "").lower().strip()

    cur_steal  = {_steal_key(i): i for i in (current.get("steal_this") or []) if _steal_key(i)}
    prev_steal = {_steal_key(i): i for i in (previous.get("steal_this") or []) if _steal_key(i)}
    cur_gaps   = {_gap_key(i): i  for i in (current.get("strategic_gaps") or []) if _gap_key(i)}
    prev_gaps  = {_gap_key(i): i  for i in (previous.get("strategic_gaps") or []) if _gap_key(i)}

    new_steal     = [cur_steal[k]  for k in cur_steal  if k not in prev_steal]
    removed_steal = [prev_steal[k] for k in prev_steal if k not in cur_steal]
    new_gaps      = [cur_gaps[k]   for k in cur_gaps   if k not in prev_gaps]
    removed_gaps  = [prev_gaps[k]  for k in prev_gaps  if k not in cur_gaps]

    files_delta = (current.get("files_analyzed") or 0) - (previous.get("files_analyzed") or 0)
    has_changes = bool(new_steal or removed_steal or new_gaps or removed_gaps or files_delta)

    return {
        "new_steal_this":       new_steal,
        "removed_steal_this":   removed_steal,
        "new_strategic_gaps":   new_gaps,
        "removed_strategic_gaps": removed_gaps,
        "files_delta":          files_delta,
        "has_changes":          has_changes,
    }


# ── Multi-repo parallel compare ────────────────────────────────────────────────

def compare_multi_repos(repo_urls: list, force_refresh: bool = False) -> dict:
    """Analyze repos in parallel; return unified steal list ranked by frequency."""
    from concurrent.futures import ThreadPoolExecutor, as_completed

    results: dict = {}
    errors:  dict = {}

    with ThreadPoolExecutor(max_workers=min(len(repo_urls), 3)) as pool:
        futures = {pool.submit(analyze_repo, url, force_refresh): url for url in repo_urls}
        for future in as_completed(futures, timeout=300):
            url = futures[future]
            try:
                results[url] = future.result()
            except Exception as exc:
                errors[url] = str(exc)
                logger.warning("[repo_dna] multi-compare failed for %s: %s", url, exc)

    if not results:
        raise RuntimeError(f"All repos failed: {errors}")

    # Build unified steal list — key by title, rank by frequency
    steal_counter: dict = {}
    for url, analysis in results.items():
        for item in (analysis.get("steal_this") or []):
            key = (item.get("title") or item.get("capability") or "").lower().strip()
            if not key:
                continue
            if key not in steal_counter:
                steal_counter[key] = {"item": item, "repos": [], "count": 0}
            steal_counter[key]["repos"].append(url)
            steal_counter[key]["count"] += 1

    unified_steal = sorted(steal_counter.values(), key=lambda x: x["count"], reverse=True)

    return {
        "repos":         results,
        "errors":        errors,
        "unified_steal": unified_steal,
        "repo_count":    len(results),
        "failed_count":  len(errors),
    }


# ── Fetch ──────────────────────────────────────────────────────────────────────

def _url_hash(url: str) -> str:
    return hashlib.md5(url.encode()).hexdigest()[:8]


def _clone_repo(repo_url: str) -> tuple[str, str]:
    """Clone repo to tmp dir. Returns (clone_path, commit_sha). Raises RepoFetchError."""
    clone_path = os.path.join(tempfile.gettempdir(), f"{_TMP_PREFIX}{_url_hash(repo_url)}")
    if os.path.exists(clone_path):
        shutil.rmtree(clone_path, ignore_errors=True)

    result = subprocess.run(
        [_GIT_BIN, "clone", "--depth", "1", repo_url, clone_path],
        capture_output=True,
        text=True,
        timeout=120,
    )
    if result.returncode != 0:
        raise RepoFetchError(f"git clone failed: {result.stderr.strip()[:300]}")

    sha_result = subprocess.run(
        [_GIT_BIN, "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
        cwd=clone_path,
        timeout=10,
    )
    commit_sha = sha_result.stdout.strip() if sha_result.returncode == 0 else "unknown"
    return clone_path, commit_sha


def _get_remote_sha(repo_url: str) -> str:
    """Get HEAD sha without cloning — used by watch checker."""
    result = subprocess.run(
        [_GIT_BIN, "ls-remote", repo_url, "HEAD"],
        capture_output=True,
        text=True,
        timeout=30,
    )
    if result.returncode == 0 and result.stdout.strip():
        return result.stdout.split()[0]
    return "unknown"


def _mcp_file_tree(repo_url: str) -> tuple[list[str], str]:
    """Fallback: fetch file tree via GitHub MCP. Returns (file_list, 'unknown' sha)."""
    try:
        import mcp_bridge

        match = re.search(r"github\.com/([\w\-]+)/([\w\-]+)", repo_url)
        if not match:
            raise RepoFetchError("Cannot parse owner/repo from URL")
        owner, repo = match.group(1), match.group(2)

        tree_result = mcp_bridge.call_mcp_server(
            "github",
            "get_file_tree",
            {"owner": owner, "repo": repo, "recursive": True},
            context_intent="mcp",
        )
        files = []
        if isinstance(tree_result, list):
            files = [f.get("path", "") for f in tree_result if isinstance(f, dict)]
        elif isinstance(tree_result, str):
            files = [line.strip() for line in tree_result.splitlines() if line.strip()]
        return files, "unknown"
    except Exception as exc:
        raise RepoFetchError(f"GitHub MCP fallback failed: {exc}") from exc


# ── File scoring & sampling ────────────────────────────────────────────────────

def _score_file(path: str) -> int:
    lower = path.lower()
    score = 0
    name = os.path.basename(lower)
    ext = os.path.splitext(name)[1]

    # ── Source code — highest priority ──
    if ext == ".py":
        score += 10
    if name in ("main.py", "app.py", "core.py") or (ext == ".py" and name.startswith("core")):
        score += 5  # bonus: only Python entry points/core files → +15 total
    elif ext in (".rs", ".ts", ".js", ".go", ".kt", ".swift"):
        score += 4  # other source languages — still valuable for patterns

    # ── Config / deps ──
    if "requirements" in name and ext in (".txt", ""):
        score += 6
    if ext == ".json" and not name.startswith("."):
        score += 2

    # ── Docs — only ONE readme useful ──
    if name == "readme.md":
        score += 5  # primary README only
    elif name.startswith("readme"):
        score -= 5  # translated/variant READMEs (README.zh.md, README.en.md…)
    elif ext == ".md":
        score += 3  # other docs (architecture, contributing, etc.)

    # ── Penalize noise ──
    if name.startswith("test") or "test/" in lower or "tests/" in lower:
        score -= 5
    if ext == ".lock":
        score -= 10
    for skip in ("node_modules/", "dist/", "build/", ".git/", "__pycache__/"):
        if skip in lower:
            score -= 20

    return score


def _top_files(file_list: list[str]) -> list[str]:
    scored = [(path, _score_file(path)) for path in file_list]
    scored.sort(key=lambda x: x[1], reverse=True)

    # Dedup: allow at most 1 README in final selection
    selected = []
    readme_count = 0
    for path, _ in scored:
        name = os.path.basename(path.lower())
        if name.startswith("readme"):
            if readme_count >= 1:
                continue
            readme_count += 1
        selected.append(path)
        if len(selected) >= _TOP_FILES_COUNT:
            break

    logger.info("[repo_dna] sampled files: %s", selected)
    return selected


def _read_files_from_clone(clone_path: str, file_list: list[str]) -> dict[str, str]:
    contents = {}
    for rel_path in file_list:
        abs_path = os.path.join(clone_path, rel_path)
        if os.path.isfile(abs_path):
            try:
                with open(abs_path, "r", encoding="utf-8", errors="replace") as f:
                    contents[rel_path] = f.read(_MAX_FILE_CHARS)
            except OSError:
                pass
    return contents


def _read_files_via_mcp(owner: str, repo: str, file_list: list[str]) -> dict[str, str]:
    import mcp_bridge
    contents = {}
    for path in file_list:
        try:
            text = mcp_bridge.call_mcp_server(
                "github",
                "get_file_contents",
                {"owner": owner, "repo": repo, "path": path},
                context_intent="mcp",
            )
            if isinstance(text, str):
                contents[path] = text[:_MAX_FILE_CHARS]
            elif isinstance(text, dict) and "content" in text:
                contents[path] = text["content"][:_MAX_FILE_CHARS]
        except Exception:
            pass
    return contents


# ── LLM analysis ──────────────────────────────────────────────────────────────

_SANITIZE_PATTERNS = [
    (re.compile(r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b'), "<email>"),
    (re.compile(r'\b\d{3}[-.]?\d{3}[-.]?\d{4}\b'), "<phone>"),
    (re.compile(r'\b\d{3}-\d{2}-\d{4}\b'), "<ssn>"),
    (re.compile(r'\b\d{4}[- ]?\d{4}[- ]?\d{4}[- ]?\d{4}\b'), "<card>"),
]


def _sanitize_content(content: str) -> str:
    """Replace PII-like patterns to avoid triggering smart_router PII gate on code content."""
    for pattern, replacement in _SANITIZE_PATTERNS:
        content = pattern.sub(replacement, content)
    return content


def _build_prompt(repo_url: str, file_contents: dict[str, str]) -> str:
    lines = [f"TARGET REPO: {repo_url}\n\n## TARGET REPO FILES:\n"]
    for path, content in file_contents.items():
        lines.append(f"\n=== {path} ===\n{_sanitize_content(content)}")
    lines.append(
        "\n\nAnalyze the target repo files above against EDITH's codebase in the system prompt. "
        "Return ONLY valid JSON with no markdown fences or prose outside the JSON object."
    )
    return "".join(lines)


_STRATEGIC_SYSTEM = (
    "You are a senior software architect analyzing a GitHub repository as competitive "
    "reference for EDITH, a personal AI OS built in Python. Return only a JSON array. "
    "No markdown fences. No preamble. No trailing text."
)

_STRATEGIC_PROMPT_TMPL = """\
You are analyzing a GitHub repository as a competitive reference for EDITH, a personal AI OS.

Repo: {repo_url}

Repo content:
{repo_content}

Identify exactly 5 system-level capabilities this repo has that EDITH lacks or does poorly.
For each capability return JSON:
{{
  "capability": "short name",
  "what": "one sentence what it is",
  "why": "one sentence why EDITH needs it",
  "effort": "quick_win | sprint | roadmap",
  "steal_from": "specific file or module in their repo"
}}

Return only a JSON array of exactly 5 objects. No markdown. No preamble.\
"""


def _build_strategic_prompt(repo_url: str, file_contents: dict[str, str]) -> str:
    repo_content = "\n".join(
        f"=== {path} ===\n{_sanitize_content(content)}"
        for path, content in file_contents.items()
    )
    return _STRATEGIC_PROMPT_TMPL.format(repo_url=repo_url, repo_content=repo_content)


def _valid_strategic_schema(result: object) -> bool:
    """True only if result is a non-empty list where each item has required keys."""
    if not isinstance(result, list) or len(result) == 0:
        return False
    required = {"capability", "what"}
    return all(required.issubset(item.keys()) for item in result if isinstance(item, dict))


def _parse_strategic_json(raw: str) -> Optional[list]:
    """Extract JSON list from raw LLM response. Returns None on total parse failure."""
    try:
        parsed = json.loads(raw)
        if isinstance(parsed, list):
            return parsed
        # LLM wrapped list in object: {"strategic_gaps": [...]}
        if isinstance(parsed, dict):
            for v in parsed.values():
                if isinstance(v, list):
                    return v
    except json.JSONDecodeError:
        pass
    match = re.search(r"\[[\s\S]+\]", raw)
    if match:
        try:
            parsed = json.loads(match.group(0))
            if isinstance(parsed, list):
                return parsed
        except json.JSONDecodeError:
            pass
    return None


def _run_strategic_analysis(repo_url: str, file_contents: dict[str, str]) -> list:
    """Second LLM call — architect-level gap analysis.
    Cloud-only chain: Groq → Gemini → NVIDIA → OpenRouter.
    Ollama excluded — DO cloud node has no local Ollama.
    Returns list[dict] on success, [] on failure.
    Sets parse_error key on returned list's __dict__ — callers check via _strategic_parse_error.
    """
    prompt = _build_strategic_prompt(repo_url, file_contents)
    _cloud_callers = [
        ("groq",       smart_router._call_groq),
        ("gemini",     smart_router._call_gemini),
        ("nvidia",     smart_router._call_nvidia),
        ("openrouter", smart_router._call_openrouter),
    ]

    def _call_cloud(extra_system: str = "") -> Optional[str]:
        system = _STRATEGIC_SYSTEM + extra_system
        for name, caller in _cloud_callers:
            try:
                raw = caller(prompt, system)
                logger.info("[repo_dna] strategic: %s responded (%d chars)", name, len(raw))
                return raw
            except Exception as exc:
                logger.warning("[repo_dna] strategic: %s failed: %s", name, str(exc)[:120])
        return None

    raw = _call_cloud()
    if raw is None:
        logger.warning("[repo_dna] strategic: all cloud providers failed")
        return []

    result = _parse_strategic_json(raw)
    if result is not None and _valid_strategic_schema(result):
        return result

    # Schema validation failed — retry once with stricter instruction
    logger.warning(
        "[repo_dna] strategic schema invalid on first attempt "
        "(result=%s, len=%s). Retrying.",
        type(result).__name__,
        len(result) if isinstance(result, list) else "n/a",
    )
    raw2 = _call_cloud(
        extra_system=(
            " CRITICAL: Your previous response did not match the required schema. "
            "Return ONLY a raw JSON array of exactly 5 objects. "
            "Each object MUST have these keys: capability, what, why, effort, steal_from. "
            "No markdown fences. No wrapping object. Start with [ and end with ]."
        )
    )
    if raw2 is not None:
        result2 = _parse_strategic_json(raw2)
        if result2 is not None and _valid_strategic_schema(result2):
            return result2

    logger.warning("[repo_dna] strategic: retry also failed. raw[:200]=%r", (raw or "")[:200])
    return []


def _parse_analysis_json(raw: str) -> Optional[dict]:
    """Extract JSON dict from raw LLM response. Returns None on total parse failure."""
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        match = re.search(r"\{[\s\S]+\}", raw)
        if match:
            try:
                return json.loads(match.group(0))
            except json.JSONDecodeError:
                pass
    return None


_ANALYSIS_REQUIRED_KEYS = {"steal_this", "skip_this", "summary"}


def _valid_analysis_schema(result: dict) -> bool:
    """True only if result has required keys and steal_this is a non-empty list."""
    steal = result.get("steal_this")
    return (
        isinstance(steal, list)
        and len(steal) > 0
        and _ANALYSIS_REQUIRED_KEYS.issubset(result.keys())
    )


def _run_llm_analysis(repo_url: str, file_contents: dict[str, str], force_refresh: bool = False) -> dict:
    import time as _time
    system_prompt = _build_system_prompt()
    prompt = _build_prompt(repo_url, file_contents)
    if force_refresh:
        # Bust smart_router's 1-hour in-memory response cache.
        # _context_fingerprint() keys on prompt text — unique suffix forces a fresh LLM call.
        prompt += f"\n\n[refresh:{int(_time.time()):x}]"

    raw = smart_router.smart_call(
        prompt=prompt,
        intent="repo_analyze",
        system=system_prompt,
    )

    result = _parse_analysis_json(raw)
    if result and _valid_analysis_schema(result):
        return result

    # Schema validation failed (wrong keys or steal_this missing/empty) — retry once
    logger.warning(
        "[repo_dna] schema validation failed on first attempt "
        "(steal_this=%r, keys=%s). Retrying with strict prompt.",
        result.get("steal_this") if result else "parse_error",
        list(result.keys()) if result else [],
    )
    strict_system = system_prompt + (
        "\n\nCRITICAL: Your previous response did not match the required JSON schema. "
        "Return ONLY a raw JSON object — no markdown fences, no prose. "
        "Required top-level keys: repo_url, repo_name, analyzed_at, steal_this, "
        "skip_this, watch_this, architecture_delta, quick_wins, summary. "
        "steal_this MUST be a non-empty list with at least 3 items."
    )
    retry_prompt = prompt + f"\n\n[strict-retry:{int(_time.time()):x}]"
    raw2 = smart_router.smart_call(
        prompt=retry_prompt,
        intent="repo_analyze",
        system=strict_system,
    )

    result2 = _parse_analysis_json(raw2)
    if result2 and _valid_analysis_schema(result2):
        return result2

    logger.warning("[repo_dna] retry also failed schema validation. raw[:200]=%r", raw[:200])
    return {**_ANALYSIS_SCHEMA, "summary": raw, "repo_url": repo_url, "parse_error": True}


# ── Public API ─────────────────────────────────────────────────────────────────

def analyze_repo(repo_url: str, force_refresh: bool = False) -> dict:
    """
    Analyze a GitHub repo. Returns analysis dict.
    Raises RepoFetchError or RepoAnalysisError on failure.
    Cache: 7-day TTL keyed by repo_url + commit_sha.
    """
    clone_path = None
    used_mcp = False

    try:
        # ── Fetch step ──
        try:
            clone_path = os.path.join(tempfile.gettempdir(), f"{_TMP_PREFIX}{_url_hash(repo_url)}")
            clone_path, commit_sha = _clone_repo(repo_url)
            logger.info("[repo_dna] cloned %s @ %s", repo_url, commit_sha)
        except RepoFetchError as clone_err:
            logger.warning("[repo_dna] clone failed, trying MCP: %s", clone_err)
            used_mcp = True
            file_list_mcp, commit_sha = _mcp_file_tree(repo_url)

        # ── Cache check ──
        if not force_refresh:
            cached = _cache_lookup(repo_url, commit_sha)
            if cached:
                logger.info("[repo_dna] cache HIT for %s @ %s", repo_url, commit_sha)
                return cached
        logger.info("[repo_dna] cache MISS for %s", repo_url)

        # ── Sample files ──
        files_total = 0
        if not used_mcp:
            all_files = []
            for root, dirs, files in os.walk(clone_path):
                dirs[:] = [d for d in dirs if d not in (".git", "node_modules", "dist", "build")]
                for fname in files:
                    rel = os.path.relpath(os.path.join(root, fname), clone_path)
                    all_files.append(rel)
            files_total = len(all_files)
            top = _top_files(all_files)
            file_contents = _read_files_from_clone(clone_path, top)
        else:
            files_total = len(file_list_mcp)
            top = _top_files(file_list_mcp)
            match = re.search(r"github\.com/([\w\-]+)/([\w\-]+)", repo_url)
            if match:
                owner, repo = match.group(1), match.group(2)
                file_contents = _read_files_via_mcp(owner, repo, top)
            else:
                file_contents = {}

        # ── Content guard ──
        total_chars = sum(len(v) for v in file_contents.values())
        logger.info("[repo_dna] fetched %d files, %d total chars", len(file_contents), total_chars)
        if total_chars < _MIN_CONTENT_CHARS:
            raise RepoFetchError(
                f"Fetched only {total_chars} chars from {len(file_contents)} files — "
                "repo may be empty, private, or fetch failed"
            )

        # ── LLM call (code-level) ──
        try:
            analysis = _run_llm_analysis(repo_url, file_contents, force_refresh=force_refresh)
        except Exception as exc:
            raise RepoAnalysisError(f"LLM analysis failed: {exc}") from exc

        # ── Strategic gap analysis (same file_contents, no second fetch) ──
        strategic_gaps = _run_strategic_analysis(repo_url, file_contents)
        analysis["strategic_gaps"] = strategic_gaps
        if strategic_gaps:
            logger.info("[repo_dna] strategic: %d gaps found", len(strategic_gaps))
        else:
            logger.warning("[repo_dna] strategic: no gaps returned (provider may have failed)")
            analysis["strategic_parse_error"] = True

        # ── Enrich & cache ──
        repo_name = repo_url.rstrip("/").split("/")[-1]
        analysis["repo_url"] = repo_url
        analysis["repo_name"] = repo_name
        analysis["analyzed_at"] = datetime.now(timezone.utc).isoformat()
        analysis["files_analyzed"] = len(file_contents)
        analysis["files_total"] = files_total
        _cache_store(repo_url, repo_name, commit_sha, analysis)
        logger.info("[repo_dna] analysis stored for %s", repo_url)

        # Trend: diff against previous snapshot, then save current
        prev = get_previous_snapshot(repo_url)
        _save_snapshot(repo_url, commit_sha, analysis)
        if prev:
            analysis["trend"] = diff_analyses(analysis, prev)
        else:
            analysis["trend"] = {"has_changes": False, "first_analysis": True}

        return analysis

    finally:
        if clone_path and os.path.exists(clone_path):
            shutil.rmtree(clone_path, ignore_errors=True)
            logger.info("[repo_dna] cleaned up %s", clone_path)


def mark_adapted(repo_url: str, capability: str, target_file: str) -> None:
    now = datetime.now(timezone.utc).isoformat()
    with _get_db() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO adapted_items (repo_url, capability, adapted_at, target_file) "
            "VALUES (?, ?, ?, ?)",
            (repo_url, capability, now, target_file),
        )
        conn.commit()
    logger.info("[repo_dna] marked adapted: %s / %s → %s", repo_url, capability, target_file)


def get_adapted_capabilities(repo_url: str) -> set:
    try:
        with _get_db() as conn:
            rows = conn.execute(
                "SELECT capability FROM adapted_items WHERE repo_url = ?", (repo_url,)
            ).fetchall()
        return {r["capability"] for r in rows}
    except Exception as exc:
        logger.warning("[repo_dna] get_adapted_capabilities failed: %s", exc)
        return set()


def rate_adaptation(repo_url: str, capability: str, outcome: str, notes: str = "") -> None:
    """Record thumbs-up/partial/down outcome for an adapted item."""
    now = datetime.now(timezone.utc).isoformat()
    with _get_db() as conn:
        conn.execute(
            "UPDATE adapted_items SET outcome=?, rated_at=?, notes=? "
            "WHERE repo_url=? AND capability=?",
            (outcome, now, notes, repo_url, capability),
        )
        conn.commit()
    logger.info("[repo_dna] rated %s / %s → %s", repo_url, capability, outcome)


def get_steal_success_rate(repo_url: Optional[str] = None) -> dict:
    """Return success/partial/failure counts. Filter to repo_url when provided."""
    with _get_db() as conn:
        if repo_url:
            rows = conn.execute(
                "SELECT outcome FROM adapted_items WHERE repo_url=? AND outcome IS NOT NULL",
                (repo_url,),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT outcome FROM adapted_items WHERE outcome IS NOT NULL"
            ).fetchall()
    totals: dict = {"success": 0, "partial": 0, "failure": 0, "total": 0}
    for row in rows:
        o = (row["outcome"] or "").lower()
        totals["total"] += 1
        if o in totals:
            totals[o] += 1
    rate = round(totals["success"] / totals["total"] * 100) if totals["total"] else 0
    return {**totals, "success_rate_pct": rate}


def get_cached_analyses() -> list[dict]:
    """Return all cached analyses, newest first. Enriches steal_this with adapted field."""
    with _get_db() as conn:
        rows = conn.execute(
            "SELECT analysis_json FROM repo_analyses ORDER BY created_at DESC"
        ).fetchall()
    analyses = [json.loads(r["analysis_json"]) for r in rows]
    for entry in analyses:
        repo_url = entry.get("repo_url", "")
        if not repo_url:
            continue
        try:
            adapted_caps = get_adapted_capabilities(repo_url)
            for item in entry.get("steal_this", []):
                cap = item.get("capability") or item.get("title") or ""
                item["adapted"] = cap in adapted_caps
        except Exception:
            pass
    return analyses


def clear_cache(repo_url: str = None) -> None:
    """Clear one repo's cache or all if repo_url is None."""
    with _get_db() as conn:
        if repo_url:
            conn.execute("DELETE FROM repo_analyses WHERE repo_url = ?", (repo_url,))
            logger.info("[repo_dna] cleared cache for %s", repo_url)
        else:
            conn.execute("DELETE FROM repo_analyses")
            logger.info("[repo_dna] cleared all repo_dna cache")
        conn.commit()


# ── Watch list ─────────────────────────────────────────────────────────────────

def watch_repo(repo_url: str) -> bool:
    """Add repo to weekly auto-watch list. Returns True if added, False if already watching."""
    repo_name = repo_url.rstrip("/").split("/")[-1]
    now = datetime.now(timezone.utc).isoformat()
    with _get_db() as conn:
        try:
            conn.execute(
                "INSERT INTO watched_repos (repo_url, repo_name, added_at) VALUES (?, ?, ?)",
                (repo_url, repo_name, now),
            )
            conn.commit()
            logger.info("[repo_dna] watching %s", repo_url)
            return True
        except sqlite3.IntegrityError:
            return False


def get_watched_repos() -> list[dict]:
    """Return all watched repos."""
    with _get_db() as conn:
        rows = conn.execute(
            "SELECT repo_url, repo_name, added_at, last_checked, last_sha "
            "FROM watched_repos ORDER BY added_at DESC"
        ).fetchall()
    return [dict(r) for r in rows]


def check_watched_repos() -> list[dict]:
    """
    Called by background_daemon weekly job.
    For each watched repo: get current HEAD sha, compare to last cached sha.
    If changed → re-analyze with force_refresh=True.
    Returns list of repos that had changes + new findings.
    """
    watched = get_watched_repos()
    changed = []
    now = datetime.now(timezone.utc).isoformat()

    for w in watched:
        repo_url = w["repo_url"]
        try:
            current_sha = _get_remote_sha(repo_url)
            last_sha = w.get("last_sha") or ""

            with _get_db() as conn:
                conn.execute(
                    "UPDATE watched_repos SET last_checked = ? WHERE repo_url = ?",
                    (now, repo_url),
                )
                conn.commit()

            if current_sha != "unknown" and current_sha == last_sha:
                logger.info("[repo_watch] no change: %s", repo_url)
                continue

            logger.info("[repo_watch] change detected %s (%s → %s)", repo_url, last_sha[:8], current_sha[:8])
            analysis = analyze_repo(repo_url, force_refresh=True)

            with _get_db() as conn:
                conn.execute(
                    "UPDATE watched_repos SET last_sha = ? WHERE repo_url = ?",
                    (current_sha, repo_url),
                )
                conn.commit()

            changed.append({
                "repo_url": repo_url,
                "repo_name": w["repo_name"],
                "new_sha": current_sha,
                "steal_count": len(analysis.get("steal_this", [])),
                "quick_wins": [q["title"] for q in analysis.get("quick_wins", [])],
                "summary": analysis.get("summary", ""),
            })
        except Exception as exc:
            logger.error("[repo_watch] failed checking %s: %s", repo_url, exc)

    return changed


# ── Module init ────────────────────────────────────────────────────────────────
try:
    _backfill_snapshots()
except Exception as _e:
    logger.warning("[repo_dna] snapshot backfill failed: %s", _e)
