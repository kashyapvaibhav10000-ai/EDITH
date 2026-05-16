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
    conn.commit()
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


def _run_strategic_analysis(repo_url: str, file_contents: dict[str, str]) -> list:
    """Second LLM call — architect-level gap analysis.
    Cloud-only chain: Groq → Gemini → NVIDIA → OpenRouter.
    Ollama excluded — DO cloud node has no local Ollama.
    Returns list[dict] or [] on failure.
    """
    prompt = _build_strategic_prompt(repo_url, file_contents)
    _cloud_callers = [
        ("groq",       smart_router._call_groq),
        ("gemini",     smart_router._call_gemini),
        ("nvidia",     smart_router._call_nvidia),
        ("openrouter", smart_router._call_openrouter),
    ]
    raw = None
    for name, caller in _cloud_callers:
        try:
            raw = caller(prompt, _STRATEGIC_SYSTEM)
            logger.info("[repo_dna] strategic: %s responded (%d chars)", name, len(raw))
            break
        except Exception as exc:
            logger.warning("[repo_dna] strategic: %s failed: %s", name, str(exc)[:120])

    if raw is None:
        logger.warning("[repo_dna] strategic: all cloud providers failed")
        return []

    try:
        result = json.loads(raw)
    except json.JSONDecodeError:
        match = re.search(r"\[[\s\S]+\]", raw)
        if match:
            try:
                result = json.loads(match.group(0))
            except json.JSONDecodeError:
                logger.warning("[repo_dna] strategic: non-JSON response")
                return []
        else:
            logger.warning("[repo_dna] strategic: non-JSON response")
            return []

    if isinstance(result, list):
        return result
    logger.warning("[repo_dna] strategic: expected list, got %s", type(result))
    return []


def _run_llm_analysis(repo_url: str, file_contents: dict[str, str], force_refresh: bool = False) -> dict:
    system_prompt = _build_system_prompt()
    prompt = _build_prompt(repo_url, file_contents)
    if force_refresh:
        # Bust smart_router's 1-hour in-memory response cache.
        # _context_fingerprint() keys on prompt text — unique suffix forces a fresh LLM call.
        import time as _time
        prompt += f"\n\n[refresh:{int(_time.time()):x}]"
    raw = smart_router.smart_call(
        prompt=prompt,
        intent="repo_analyze",
        system=system_prompt,
    )

    # Try to extract JSON even if LLM adds surrounding text
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        match = re.search(r"\{[\s\S]+\}", raw)
        if match:
            try:
                return json.loads(match.group(0))
            except json.JSONDecodeError:
                pass
    logger.warning("[repo_dna] LLM returned non-JSON, storing raw text")
    return {**_ANALYSIS_SCHEMA, "summary": raw, "repo_url": repo_url}


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
        if not used_mcp:
            all_files = []
            for root, dirs, files in os.walk(clone_path):
                dirs[:] = [d for d in dirs if d not in (".git", "node_modules", "dist", "build")]
                for fname in files:
                    rel = os.path.relpath(os.path.join(root, fname), clone_path)
                    all_files.append(rel)
            top = _top_files(all_files)
            file_contents = _read_files_from_clone(clone_path, top)
        else:
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

        # ── Enrich & cache ──
        repo_name = repo_url.rstrip("/").split("/")[-1]
        analysis["repo_url"] = repo_url
        analysis["repo_name"] = repo_name
        analysis["analyzed_at"] = datetime.now(timezone.utc).isoformat()
        _cache_store(repo_url, repo_name, commit_sha, analysis)
        logger.info("[repo_dna] analysis stored for %s", repo_url)
        return analysis

    finally:
        if clone_path and os.path.exists(clone_path):
            shutil.rmtree(clone_path, ignore_errors=True)
            logger.info("[repo_dna] cleaned up %s", clone_path)


def get_cached_analyses() -> list[dict]:
    """Return all cached analyses, newest first."""
    with _get_db() as conn:
        rows = conn.execute(
            "SELECT analysis_json FROM repo_analyses ORDER BY created_at DESC"
        ).fetchall()
    return [json.loads(r["analysis_json"]) for r in rows]


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
