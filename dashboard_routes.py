"""
Dashboard Routes - API endpoints for system monitoring and dev panel

This module provides:
- /api/stats - System statistics
- /api/devpanel/modules - List of EDITH modules
- /api/devpanel/query - Dev panel AI query interface
"""

import asyncio
import glob as _glob
import json as _json2
import os
import urllib.request as _urlreq
from datetime import datetime

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from dashboard_backend import (
    get_system_stats,
    get_active_model,
    get_recent_logs,
    get_edith_modules,
    get_mcp_status,
)
from config import get_logger

log = get_logger("dashboard_routes")

# ──────────────────────────────────────────────────
# Dev Panel Constants
# ──────────────────────────────────────────────────

_EDITH_DIR = os.path.expanduser("~/EDITH")
_CHAT_URL = "http://localhost:8001/api/chat"
_MAX_CHARS_PER_FILE = 4000
_MAX_FILES = 8

_SYSTEM_QA = (
    "You are EDITH's self-awareness module with full access to her source code. "
    "Answer architecture and development questions accurately and concisely. "
    "Reference specific function names, classes, and line details when relevant."
)

_SYSTEM_COUNCIL = """You are EDITH's Council of Minds. Four internal personas analyse the question and debate.

STRATEGIST — long-term architecture, scalability, design principles
CRITIC      — flaws, edge cases, tech debt, failure modes
BUILDER     — concrete next steps, exact code actions needed
FUTURIST    — ambitious possibilities, what EDITH could become

Respond in this exact format (no preamble):
STRATEGIST: <2-3 sentences>
CRITIC: <2-3 sentences>
BUILDER: <2-3 sentences>
FUTURIST: <2-3 sentences>
CONSENSUS: <1-2 sentences final verdict>"""

_SYSTEM_NEXT = (
    "You are EDITH's self-awareness module. Based on the provided codebase, "
    "identify the single most impactful next thing to build. "
    "Be specific: module name, key functions to write, why it matters most right now. "
    "No generic advice — ground everything in the actual code provided."
)


# ──────────────────────────────────────────────────
# API Routes
# ──────────────────────────────────────────────────

def register_dashboard_routes(app: FastAPI):
    """Register all dashboard routes with FastAPI app."""

    @app.get("/api/stats")
    def api_stats():
        """Return aggregated system statistics and module status."""
        return {
            "system": get_system_stats(),
            "model": get_active_model(),
            "logs": get_recent_logs(),
            "modules": get_edith_modules(),
            "mcp": get_mcp_status(),
            "time": datetime.now().strftime("%H:%M:%S"),
            "date": datetime.now().strftime("%A, %d %B %Y"),
        }

    @app.get("/api/devpanel/modules")
    async def devpanel_modules():
        """List all Python modules in EDITH directory with line counts."""
        modules = []
        for fp in sorted(_glob.glob(os.path.join(_EDITH_DIR, "*.py"))):
            name = os.path.basename(fp)
            try:
                with open(fp) as fh:
                    lines = sum(1 for _ in fh)
            except Exception:
                lines = 0
            modules.append({"name": name, "lines": lines})
        return {"modules": modules}

    @app.post("/api/devpanel/query")
    async def devpanel_query(req: Request):
        """Query EDITH's codebase with AI analysis (QA, Council, or Next modes)."""
        body = await req.json()
        query = body.get("query", "").strip()
        mode = body.get("mode", "qa")
        files = body.get("files", [])[:_MAX_FILES]

        if not query:
            return {"error": "Empty query."}

        ctx_parts = []
        for fname in files:
            fp = os.path.join(_EDITH_DIR, fname)
            try:
                with open(fp) as fh:
                    raw = fh.read()[:_MAX_CHARS_PER_FILE]
                ctx_parts.append(f"=== {fname} ===\n{raw}")
            except Exception:
                pass

        context = "\n\n".join(ctx_parts) if ctx_parts else "(no files loaded)"
        system = {
            "qa": _SYSTEM_QA,
            "council": _SYSTEM_COUNCIL,
            "next": _SYSTEM_NEXT,
        }.get(mode, _SYSTEM_QA)

        full_msg = (
            f"[SYSTEM ROLE]\n{system}\n\n"
            f"[CODEBASE CONTEXT]\n{context}\n\n"
            f"[QUESTION]\n{query}"
        )

        def _call():
            payload = _json2.dumps({"message": full_msg}).encode()
            rq = _urlreq.Request(
                _CHAT_URL,
                data=payload,
                headers={"Content-Type": "application/json"},
                method="POST"
            )
            with _urlreq.urlopen(rq, timeout=90) as r:
                return _json2.loads(r.read())

        try:
            data = await asyncio.get_event_loop().run_in_executor(None, _call)
            answer = (
                data.get("response")
                or data.get("message")
                or data.get("text")
                or str(data)
            )
        except Exception as e:
            answer = (
                f"[ERROR — could not reach chat_server at {_CHAT_URL}]\n"
                f"{type(e).__name__}: {e}\n\n"
                f"Make sure chat_server.py is running:\n"
                f"  cd ~/EDITH && source ~/edith-env/bin/activate && python chat_server.py &"
            )

        return {"response": answer}
