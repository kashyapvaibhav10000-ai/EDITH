"""
routes/repo.py — Repo DNA competitive intelligence endpoints.
  POST   /api/repo/analyze
  GET    /api/repo/analyses
  POST   /api/repo/watch
  GET    /api/repo/watched
  POST   /api/repo/compare
  DELETE /api/repo/cache
  POST   /api/repo/adapt-preview
  POST   /api/repo/adapt-confirm
  GET    /api/repo/adapt-status/{task_id}
  POST   /api/repo/gap-plan
  GET    /api/repo/subtask-status
  POST   /api/repo/rate-adaptation
  GET    /api/repo/success-rate
  POST   /api/repo/alert-config
  GET    /api/repo/alert-config
  GET    /api/repo/trend
  POST   /api/repo/multi-compare
  POST   /api/repo/self-audit
  POST   /api/repo/watch-check
"""

import json
import os
import re

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from config import get_logger

log = get_logger("routes.repo")
router = APIRouter()

_REPO_URL_RE = re.compile(r"^https://github\.com/[\w\-]+/[\w\-]+$")
_alert_config: dict = {"enabled": True}
_COMPARE_CATEGORIES = [
    "Memory Systems", "LLM Routing", "Voice Pipeline", "Agent Capabilities",
    "UI/Interface", "Integrations", "Security", "Reliability", "Code Quality", "Unique Features",
]
_ADAPT_PREVIEW_SYSTEM = (
    "You are EDITH's code architect. Given a capability from a competitor repo "
    "(may be JS, Rust, TypeScript, or any language), your job is to:\n"
    "1. Understand the CONCEPT behind the capability — not the syntax.\n"
    "2. Decide if EDITH actually needs this. EDITH is a Python backend AI daemon: "
    "no browser, no UI state, no Node.js, no Redux, no DOM.\n"
    "3. If applicable: implement in idiomatic Python using EDITH's existing patterns. "
    "Translate concepts — never copy JS/Rust syntax, class names, or polyfills.\n"
    "4. If not applicable: say so and explain why.\n\n"
    "TARGET_FILE must be one of the EDITH Python files listed in the prompt. "
    "If no existing file fits, use 'utils.py'.\n\n"
    "Format your response EXACTLY as:\n"
    "TARGET_FILE: <real_edith_file.py>\n"
    "APPLICABLE: yes/no\n"
    "REASON: <one line>\n"
    "```python\n<Python implementation, or empty block if not applicable>\n```"
)

# ── Shared helpers ────────────────────────────────────────────────────────────
_sigs_cache: dict = {"data": None, "mtime": 0.0}


def _get_edith_signatures() -> dict:
    import glob as _g
    edith_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    files = sorted(_g.glob(os.path.join(edith_dir, "*.py")))
    max_mtime = max((os.path.getmtime(f) for f in files), default=0.0)
    if _sigs_cache["mtime"] == max_mtime and _sigs_cache["data"] is not None:
        return _sigs_cache["data"]
    _BLOCKLIST = {"config.py", "vault.py", "voice.py"}
    sigs: dict = {}
    for fpath in files:
        fname = os.path.basename(fpath)
        if fname in _BLOCKLIST:
            continue
        try:
            defs = [l.strip() for l in open(fpath) if l.strip().startswith("def ")]
            if defs:
                sigs[fname] = defs
        except Exception:
            pass
    _sigs_cache.update({"data": sigs, "mtime": max_mtime})
    return sigs


def _get_all_fns_in_file(fname: str) -> set:
    edith_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    fpath = os.path.join(edith_dir, fname)
    fns: set = set()
    if not os.path.exists(fpath):
        return fns
    try:
        for line in open(fpath):
            s = line.strip()
            if s.startswith("def "):
                fns.add(s.split("(")[0].replace("def ", "").strip())
    except Exception:
        pass
    return fns


def _read_file_skeleton(fname: str) -> str:
    edith_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    fpath = os.path.join(edith_dir, fname)
    if not os.path.exists(fpath):
        return ""
    try:
        return "".join(open(fpath).readlines()[:200])
    except Exception:
        return ""


def _try_parse_json(raw: str):
    import re as _re
    for attempt in [
        lambda: json.loads(raw.strip()),
        lambda: json.loads(_re.sub(r'```[a-z]*\n?', '', raw).strip()),
        lambda: json.loads((_re.search(r'\{[\s\S]+\}', raw) or type('x', (), {'group': lambda *_: '{}'})()).group(0)),
    ]:
        try:
            return attempt()
        except Exception:
            pass
    return {}


def _try_parse_json_list(raw: str):
    import re as _re
    for attempt in [
        lambda: json.loads(raw.strip()),
        lambda: json.loads(_re.sub(r'```[a-z]*\n?', '', raw).strip()),
        lambda: json.loads((_re.search(r'\[[\s\S]+\]', raw) or type('x', (), {'group': lambda *_: '[]'})()).group(0)),
    ]:
        try:
            r = attempt()
            if isinstance(r, list):
                return r
        except Exception:
            pass
    return []


# ── Repo DNA lazy imports ─────────────────────────────────────────────────────
def _get_repo_dna():
    try:
        import repo_dna as _dna
        from repo_dna import (
            analyze_repo, get_cached_analyses, clear_cache, watch_repo,
            get_watched_repos, check_watched_repos, get_previous_snapshot,
            diff_analyses, compare_multi_repos, _build_edith_context_summary,
            mark_adapted, RepoFetchError, RepoAnalysisError,
        )
        return True, _dna, {
            "analyze_repo": analyze_repo, "get_cached_analyses": get_cached_analyses,
            "clear_cache": clear_cache, "watch_repo": watch_repo,
            "get_watched_repos": get_watched_repos, "check_watched_repos": check_watched_repos,
            "get_previous_snapshot": get_previous_snapshot, "diff_analyses": diff_analyses,
            "compare_multi_repos": compare_multi_repos,
            "_build_edith_context_summary": _build_edith_context_summary,
            "mark_adapted": mark_adapted,
            "RepoFetchError": RepoFetchError, "RepoAnalysisError": RepoAnalysisError,
        }
    except ImportError:
        return False, None, {}


_503 = JSONResponse({"error": "repo_dna module not available"}, status_code=503)


# ── Endpoints ─────────────────────────────────────────────────────────────────
@router.post("/api/repo/analyze")
async def repo_analyze(request):
    ok, _, fns = _get_repo_dna()
    if not ok:
        return _503
    try:
        body = await request.json()
        repo_url = (body.get("repo_url") or "").strip().rstrip("/")
        force_refresh = bool(body.get("force_refresh", False))
        if not _REPO_URL_RE.match(repo_url):
            return JSONResponse({"error": "Invalid URL", "detail": "Must match https://github.com/owner/repo"}, status_code=400)
        log.info(f"[repo_dna] analyze requested: {repo_url} force={force_refresh}")
        analysis = fns["analyze_repo"](repo_url, force_refresh=force_refresh)
        return JSONResponse(analysis)
    except Exception as exc:
        cls = type(exc).__name__
        code = 400 if "Fetch" in cls else 500
        return JSONResponse({"error": cls, "detail": str(exc)}, status_code=code)


@router.get("/api/repo/analyses")
async def repo_analyses():
    ok, _, fns = _get_repo_dna()
    if not ok:
        return _503
    try:
        items = [
            {"repo_name": a.get("repo_name", ""), "repo_url": a.get("repo_url", ""),
             "analyzed_at": a.get("analyzed_at", ""),
             "steal_this_count": len(a.get("steal_this", [])),
             "quick_wins_count": len(a.get("quick_wins", []))}
            for a in fns["get_cached_analyses"]()
        ]
        return JSONResponse(items)
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=500)


@router.post("/api/repo/watch")
async def repo_watch(request):
    ok, _, fns = _get_repo_dna()
    if not ok:
        return _503
    try:
        body = await request.json()
        repo_url = (body.get("repo_url") or "").strip().rstrip("/")
        if not _REPO_URL_RE.match(repo_url):
            return JSONResponse({"error": "Invalid URL", "detail": "Must match https://github.com/owner/repo"}, status_code=400)
        added = fns["watch_repo"](repo_url)
        return JSONResponse({"watching": True, "added": added, "repo_url": repo_url})
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=500)


@router.get("/api/repo/watched")
async def repo_watched():
    ok, _, fns = _get_repo_dna()
    if not ok:
        return _503
    try:
        return JSONResponse(fns["get_watched_repos"]())
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=500)


@router.post("/api/repo/compare")
async def repo_compare(request):
    ok, _, fns = _get_repo_dna()
    if not ok:
        return _503
    try:
        body = await request.json()
        repo_url = (body.get("repo_url") or "").strip().rstrip("/")
        if not _REPO_URL_RE.match(repo_url):
            return JSONResponse({"error": "Invalid URL"}, status_code=400)
        all_analyses = fns["get_cached_analyses"]()
        cached = next((a for a in all_analyses if a.get("repo_url") == repo_url), None)
        if not cached:
            return JSONResponse({"error": "analyze first", "detail": "Run analyze before compare"}, status_code=404)
        edith_summary = fns["_build_edith_context_summary"]()
        compare_prompt = (
            f"EDITH self-knowledge (live scan):\n{edith_summary}\n\n"
            f"Target repo analysis:\n{json.dumps(cached, indent=2)}\n\n"
            f"Produce a head-to-head comparison for these exact categories: {', '.join(_COMPARE_CATEGORIES)}\n\n"
            "Return ONLY valid JSON with no prose outside it:\n"
            '{{"categories":[{{"name":"category name","edith_score":1,"repo_score":1,'
            '"edith_note":"what EDITH has","repo_note":"what repo has","winner":"edith|repo|tie"}}],'
            '"overall_winner":"edith|repo|tie","edith_advantages":["..."],'
            '"repo_advantages":["..."],"verdict":"2-3 sentence summary"}}\n\n'
            f"Score 1-10. winner must be exactly edith, repo, or tie. Output exactly {len(_COMPARE_CATEGORIES)} categories."
        )
        import smart_router as _sr
        raw = _sr.smart_call(prompt=compare_prompt, intent="repo_analyze",
                             system="You are EDITH's competitive intelligence engine. Return ONLY valid JSON.")
        result = _try_parse_json(raw)
        if not result:
            result = {"error": "LLM returned non-JSON", "raw": raw}
        result["repo_url"] = repo_url
        result["repo_name"] = cached.get("repo_name", "")
        return JSONResponse(result)
    except Exception as exc:
        log.warning(f"[repo_compare] {exc}")
        return JSONResponse({"error": str(exc)}, status_code=500)


@router.delete("/api/repo/cache")
async def repo_clear_cache(repo_url: str = None):
    ok, _, fns = _get_repo_dna()
    if not ok:
        return _503
    try:
        url = (repo_url or "").strip() or None
        fns["clear_cache"](url)
        return JSONResponse({"cleared": True, "repo_url": url or "all"})
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=500)


@router.post("/api/repo/adapt-preview")
async def repo_adapt_preview(request):
    ok, _, fns = _get_repo_dna()
    if not ok:
        return _503
    try:
        import glob as _glob
        body = await request.json()
        steal_item = body.get("steal_item") or {}
        repo_url = (body.get("repo_url") or "").strip()
        capability = steal_item.get("capability") or steal_item.get("title") or "unknown"
        description = steal_item.get("description") or steal_item.get("what") or ""
        steal_from = steal_item.get("steal_from") or steal_item.get("file_hint") or ""
        edith_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        edith_files = sorted(os.path.basename(f) for f in _glob.glob(os.path.join(edith_dir, "*.py")))
        file_list_str = ", ".join(edith_files)
        task_description = (f"Implement '{capability}' in EDITH. Pattern source: {steal_from or 'see repo'}. "
                            f"Repo: {repo_url}. What it does: {description}")
        prompt = (f"Capability to steal: {capability}\nWhat it does: {description}\n"
                  f"Source file in their repo: {steal_from}\nTheir repo: {repo_url}\n\n"
                  f"EDITH Python files (flat directory, no subdirs): {file_list_str}\n\n"
                  "Generate a Python implementation sketch for EDITH. TARGET_FILE must be one of the files listed above.")
        import smart_router as _sr
        raw = _sr.smart_call(prompt=prompt, intent="repo_analyze", system=_ADAPT_PREVIEW_SYSTEM)
        target_file = "utils.py"
        applicable = True
        reason = ""
        for line in raw.splitlines():
            if line.startswith("TARGET_FILE:"):
                candidate = line.split(":", 1)[1].strip()
                if candidate in edith_files:
                    target_file = candidate
            elif line.startswith("APPLICABLE:"):
                applicable = line.split(":", 1)[1].strip().lower() == "yes"
            elif line.startswith("REASON:"):
                reason = line.split(":", 1)[1].strip()
        import re as _re
        _code_match = _re.search(r'```python\n([\s\S]+?)\n```', raw)
        new_code = _code_match.group(1).strip() if _code_match else ""
        return JSONResponse({"diff_preview": raw, "new_code": new_code, "target_file": target_file,
                             "task_description": task_description, "capability": capability,
                             "applicable": applicable, "reason": reason})
    except Exception as exc:
        log.warning(f"[repo_adapt] preview error: {exc}")
        return JSONResponse({"error": str(exc)}, status_code=500)


# adapt_results and adapt_meta are shared state — imported from chat_server at runtime
def _get_adapt_state():
    import chat_server as _cs
    return _cs._adapt_results, _cs._adapt_meta


@router.post("/api/repo/adapt-confirm")
async def repo_adapt_confirm(request):
    try:
        from agent import start_agent_task as _start, execute_agent_task as _exec
    except ImportError:
        return JSONResponse({"error": "agent module not available"}, status_code=503)
    try:
        body = await request.json()
        if not bool(body.get("confirmed", False)):
            return JSONResponse({"status": "rejected"})
        task_description = (body.get("task_description") or "").strip()
        target_file = (body.get("target_file") or "").strip()
        capability = (body.get("capability") or "").strip()
        repo_url = (body.get("repo_url") or "").strip()
        if not task_description:
            return JSONResponse({"error": "task_description required"}, status_code=400)
        plan_result = _start(task_description)
        if not plan_result.ok:
            return JSONResponse({"error": f"Planning failed: {plan_result.error}"}, status_code=500)
        task_id = plan_result.value["task_id"]
        _adapt_results, _adapt_meta = _get_adapt_state()
        _adapt_meta[task_id] = {"capability": capability, "repo_url": repo_url, "target_file": target_file}
        exec_result = _exec(task_id)
        if not exec_result.ok:
            _adapt_meta.pop(task_id, None)
            return JSONResponse({"error": f"Execution failed: {exec_result.error}"}, status_code=500)
        try:
            from devlog import add_entry as _devlog_add
            _devlog_add(change=f"repo_dna: Adapted '{capability}' from {repo_url} → {target_file}",
                        reason="repo_dna click-to-adapt HITL confirm", status="applied", error="",
                        next_plan=f"verify changes in {target_file or 'EDITH'}")
        except Exception:
            pass
        return JSONResponse({"status": "queued", "task_id": task_id,
                             "message": f"Agent executing '{capability}' adaptation in background."})
    except Exception as exc:
        log.warning(f"[repo_adapt] confirm error: {exc}")
        return JSONResponse({"error": str(exc)}, status_code=500)


@router.get("/api/repo/adapt-status/{task_id}")
async def repo_adapt_status(task_id: str):
    _adapt_results, _ = _get_adapt_state()
    return JSONResponse(_adapt_results.get(task_id, {"status": "pending"}))


_GAP_PLAN_SYSTEM = (
    "You are EDITH's code architect. Decompose a capability gap into 3-5 sub-tasks. "
    "Each sub-task adds ONE new Python function to the target file. "
    "Rules: ADD ONLY. Never modify existing functions. Python only. Max 40 lines per function. "
    "depends_on is a list of sub-task ids that MUST be implemented first (use [] if no dependency). "
    "Return JSON only, no markdown fences:\n"
    '{"target_file":"filename.py","reason":"one sentence",'
    '"subtasks":[{"id":1,"title":"...","function_name":"...","description":"...","lines_estimate":20,"depends_on":[]}]}'
)


@router.post("/api/repo/gap-plan")
async def repo_gap_plan(request):
    ok, _, fns = _get_repo_dna()
    if not ok:
        return _503
    try:
        body = await request.json()
        gap = body.get("gap") or {}
        repo_url = (body.get("repo_url") or "").strip()
        capability = gap.get("capability") or ""
        what = gap.get("what") or ""
        why = gap.get("why") or ""
        all_sigs = _get_edith_signatures()
        sigs_text = "\n".join(
            f"{fname}:\n" + "\n".join(f"  {d}" for d in defs)
            for fname, defs in all_sigs.items()
        )
        edith_files = sorted(all_sigs.keys())
        prompt = (f"Gap: {capability}\nWhat: {what}\nWhy: {why}\n\n"
                  f"EDITH files + their functions:\n{sigs_text}\n\n"
                  f"Pick the best existing file as target. Decompose into 3-5 sub-tasks. "
                  f"TARGET_FILE must be one of: {', '.join(edith_files)}\nReturn JSON only.")
        import smart_router as _sr
        raw = _sr.smart_call(prompt=prompt, intent="repo_analyze", system=_GAP_PLAN_SYSTEM)
        result = _try_parse_json(raw)
        _BLOCKLIST = {"config.py", "vault.py", "voice.py"}
        target_file = result.get("target_file", "utils.py")
        if target_file in _BLOCKLIST or not target_file.endswith(".py") or target_file not in all_sigs:
            target_file = "utils.py"
        existing_fns = _get_all_fns_in_file(target_file)
        file_skeleton = _read_file_skeleton(target_file)
        subtasks = [t for t in (result.get("subtasks") or [])
                    if isinstance(t, dict) and t.get("function_name") not in existing_fns]
        return JSONResponse({"target_file": target_file, "pick_reason": result.get("reason", ""),
                             "file_skeleton": file_skeleton, "subtasks": subtasks,
                             "capability": capability, "repo_url": repo_url})
    except Exception as exc:
        log.warning(f"[repo_gap_plan] error: {exc}")
        return JSONResponse({"error": str(exc)}, status_code=500)


@router.get("/api/repo/subtask-status")
async def repo_subtask_status(repo_url: str, capability: str):
    ok, _dna, _ = _get_repo_dna()
    if not ok:
        return _503
    try:
        db = _dna._get_db()
        prefix = f"{capability}::subtask::"
        rows = db.execute(
            "SELECT capability FROM adapted_items WHERE repo_url=? AND capability LIKE ?",
            (repo_url.strip().rstrip("/"), prefix + "%"),
        ).fetchall()
        done_ids = set()
        for row in rows:
            suffix = row[0][len(prefix):]
            if suffix.isdigit():
                done_ids.add(int(suffix))
        return JSONResponse({"done_ids": sorted(done_ids)})
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=500)


class _RateBody(BaseModel):
    repo_url: str = ""
    capability: str = ""
    outcome: str = "success"
    notes: str = ""


@router.post("/api/repo/rate-adaptation")
async def repo_rate_adaptation(body: _RateBody):
    ok, _dna, _ = _get_repo_dna()
    if not ok:
        return _503
    try:
        _dna.rate_adaptation(repo_url=body.repo_url.strip().rstrip("/"),
                             capability=body.capability.strip(),
                             outcome=body.outcome.strip(), notes=body.notes.strip())
        return JSONResponse({"ok": True})
    except Exception as exc:
        log.warning(f"[rate_adaptation] {exc}")
        return JSONResponse({"error": str(exc)}, status_code=500)


@router.get("/api/repo/success-rate")
async def repo_success_rate(repo_url: str = ""):
    ok, _dna, _ = _get_repo_dna()
    if not ok:
        return _503
    try:
        data = _dna.get_steal_success_rate(repo_url.strip().rstrip("/") or None)
        return JSONResponse(data)
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=500)


class _AlertConfigBody(BaseModel):
    enabled: bool = True


@router.post("/api/repo/alert-config")
async def repo_alert_config(body: _AlertConfigBody):
    _alert_config["enabled"] = body.enabled
    return JSONResponse({"enabled": _alert_config["enabled"]})


@router.get("/api/repo/alert-config")
async def repo_alert_config_get():
    return JSONResponse({"enabled": _alert_config.get("enabled", True)})


@router.get("/api/repo/trend")
async def repo_trend(repo_url: str):
    ok, _, fns = _get_repo_dna()
    if not ok:
        return _503
    try:
        repo_url = repo_url.strip().rstrip("/")
        all_analyses = fns["get_cached_analyses"]()
        current = next((a for a in all_analyses if a.get("repo_url") == repo_url), None)
        if not current:
            return JSONResponse({"error": "no analysis found for this repo"}, status_code=404)
        previous = fns["get_previous_snapshot"](repo_url)
        if not previous:
            return JSONResponse({"has_changes": False, "first_analysis": True})
        return JSONResponse(fns["diff_analyses"](current, previous))
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=500)


class _MultiCompareBody(BaseModel):
    repo_urls: list = []
    force_refresh: bool = False


@router.post("/api/repo/multi-compare")
def repo_multi_compare(body: _MultiCompareBody):
    ok, _, fns = _get_repo_dna()
    if not ok:
        return _503
    repo_urls = [u.strip().rstrip("/") for u in (body.repo_urls or []) if u.strip()]
    if len(repo_urls) < 2:
        return JSONResponse({"error": "need at least 2 repo URLs"}, status_code=400)
    if len(repo_urls) > 3:
        return JSONResponse({"error": "max 3 repos at once"}, status_code=400)
    for url in repo_urls:
        if not _REPO_URL_RE.match(url):
            return JSONResponse({"error": f"Invalid URL: {url}"}, status_code=400)
    try:
        result = fns["compare_multi_repos"](repo_urls, body.force_refresh)
        return JSONResponse(result)
    except Exception as exc:
        log.warning(f"[multi_compare] {exc}")
        return JSONResponse({"error": str(exc)}, status_code=500)


_audit_cache: dict = {"result": None, "ts": 0.0}


def _audit_edith_self() -> dict:
    import time, re as _re
    import smart_router as _sr
    edith_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    claude_md_path = os.path.join(edith_dir, "CLAUDE.md")
    claude_md = open(claude_md_path, errors="ignore").read() if os.path.exists(claude_md_path) else ""
    module_map_files = list(set(_re.findall(r'\b[\w_]+\.py\b', claude_md)))
    actual_files = set(f for f in os.listdir(edith_dir) if f.endswith(".py"))
    missing_files = [f for f in module_map_files if f not in actual_files]
    _VISION_EXPECTED = {
        "cognitive_profile.py": ["update_profile", "detect_drift", "get_profile"],
        "self_improve.py": ["run_scheduled_improvement", "monitor_arxiv"],
        "life_os.py": ["weekly_briefing", "simulate_branches"],
        "council.py": ["council_debate", "run_council"],
    }
    vision_gaps = [
        f"{vf}: missing `{fn}`"
        for vf, fns in _VISION_EXPECTED.items()
        for fn in fns
        if fn not in _get_all_fns_in_file(vf)
    ]
    all_sigs = _get_edith_signatures()
    sigs_text = "\n".join(
        f"{fname}: {', '.join(d.split('(')[0].replace('def ', '') for d in defs[:8])}"
        for fname, defs in list(all_sigs.items())[:30]
    )
    prompt = (
        f"EDITH CLAUDE.md lists these .py files:\n{', '.join(module_map_files[:60])}\n\n"
        f"Files MISSING from disk: {', '.join(missing_files) or 'none'}\n\n"
        f"4-Vision function checks: {'; '.join(vision_gaps) or 'all present'}\n\n"
        f"Actual implemented functions (sample):\n{sigs_text}\n\n"
        "Find up to 8 notable gaps between documented architecture and actual implementation. "
        "Return JSON array only, no markdown:\n"
        '[{"capability":"short name","claimed":"what docs say","reality":"what code has",'
        '"severity":"critical|medium|low","target_file":"which .py to fix"}]'
    )
    raw = _sr.smart_call(prompt=prompt, intent="repo_analyze",
                         system="EDITH code auditor. Analyze concrete evidence. Return JSON array only, no markdown.")
    gaps = _try_parse_json_list(raw)
    for mf in missing_files[:3]:
        if not any(mf in g.get("capability", "") for g in gaps):
            gaps.insert(0, {"capability": f"Missing module: {mf}",
                            "claimed": f"CLAUDE.md lists {mf} in module map",
                            "reality": "File does not exist on disk",
                            "severity": "critical", "target_file": mf})
    return {"summary": f"Found {len(gaps)} gaps between CLAUDE.md and actual code.",
            "audit_gaps": gaps, "missing_files": missing_files, "vision_gaps": vision_gaps,
            "timestamp": __import__("datetime").datetime.utcnow().isoformat()}


@router.post("/api/repo/self-audit")
async def repo_self_audit():
    ok, _, _ = _get_repo_dna()
    if not ok:
        return _503
    import time as _time
    now = _time.time()
    if _audit_cache["result"] is not None and now - _audit_cache["ts"] < 300:
        return JSONResponse({**_audit_cache["result"], "cached": True})
    try:
        result = _audit_edith_self()
        _audit_cache.update({"result": result, "ts": now})
        return JSONResponse(result)
    except Exception as exc:
        log.warning(f"[self_audit] error: {exc}")
        return JSONResponse({"error": str(exc)}, status_code=500)


def _send_watch_alert(repo_url: str, items: list) -> None:
    try:
        from telegram_bot import send_telegram
        lines = [f"🔔 *Repo Watch Alert*: {repo_url}\nNew low-effort steal items:"]
        for item in items[:5]:
            lines.append(f"  • {item.get('title') or item.get('capability') or '?'}")
        if len(items) > 5:
            lines.append(f"  …and {len(items) - 5} more")
        send_telegram("\n".join(lines))
    except Exception as exc:
        log.warning(f"[watch_alert] failed to send Telegram: {exc}")


@router.post("/api/repo/watch-check")
async def repo_watch_check():
    ok, _, fns = _get_repo_dna()
    if not ok:
        return _503
    try:
        updated = fns["check_watched_repos"]()
        if _alert_config.get("enabled", True):
            for entry in updated:
                repo_url = entry["repo_url"] if isinstance(entry, dict) else entry
                try:
                    current = next((a for a in fns["get_cached_analyses"]() if a.get("repo_url") == repo_url), None)
                    if not current:
                        continue
                    previous = fns["get_previous_snapshot"](repo_url)
                    if not previous:
                        continue
                    diff = fns["diff_analyses"](current, previous)
                    quick_wins = [it for it in diff.get("new_steal_this", [])
                                  if (it.get("effort") or "").lower() == "low"]
                    if quick_wins:
                        _send_watch_alert(repo_url, quick_wins)
                except Exception as exc_inner:
                    log.warning(f"[watch_check alert] {repo_url}: {exc_inner}")
        return JSONResponse({"updated": updated, "count": len(updated)})
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=500)
