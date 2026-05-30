"""
routes/sessions.py — Session history endpoints + devpanel + webhooks.
  GET  /api/sessions
  POST /api/sessions/new
  GET  /api/sessions/{session_id}/messages
  GET  /api/devpanel/modules
  POST /api/devpanel/query
  POST /webhook/{source}
  POST /tg_webhook
"""

import asyncio
import datetime
import json
import os
import urllib.request as _urlreq

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from config import get_logger

log = get_logger("routes.sessions")
router = APIRouter()

_EDITH_DIR = os.path.expanduser("~/EDITH")
_MAX_CHARS_PER_FILE = 4000
_MAX_FILES = 8
_WEBHOOK_TOKEN = os.getenv("EDITH_WEBHOOK_TOKEN", "")

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


def _verify_webhook(req: Request) -> bool:
    if not _WEBHOOK_TOKEN:
        return True
    return req.headers.get("X-Webhook-Token", "") == _WEBHOOK_TOKEN


@router.get("/api/devpanel/modules")
async def devpanel_modules():
    import glob as _glob
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


@router.post("/api/devpanel/query")
async def devpanel_query(req: Request):
    body = await req.json()
    query = body.get("query", "").strip()
    mode = body.get("mode", "qa")
    files = body.get("files", [])[:_MAX_FILES]
    if not query:
        return {"error": "Empty query."}
    ctx_parts = []
    for fname in files:
        fp = os.path.join(_EDITH_DIR, fname)
        if not os.path.abspath(fp).startswith(_EDITH_DIR):
            continue
        try:
            with open(fp) as fh:
                raw = fh.read()[:_MAX_CHARS_PER_FILE]
            ctx_parts.append(f"=== {fname} ===\n{raw}")
        except Exception:
            pass
    context = "\n\n".join(ctx_parts) if ctx_parts else "(no files loaded)"
    system = {"qa": _SYSTEM_QA, "council": _SYSTEM_COUNCIL, "next": _SYSTEM_NEXT}.get(mode, _SYSTEM_QA)
    full_msg = f"[SYSTEM ROLE]\n{system}\n\n[CODEBASE CONTEXT]\n{context}\n\n[QUESTION]\n{query}"

    def _call():
        payload = json.dumps({"message": full_msg}).encode()
        rq = _urlreq.Request(
            "http://localhost:8001/api/chat",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with _urlreq.urlopen(rq, timeout=90) as r:
            return json.loads(r.read())

    try:
        data = await asyncio.get_event_loop().run_in_executor(None, _call)
        answer = data.get("reply") or data.get("response") or data.get("message") or str(data)
    except Exception as e:
        answer = f"[ERROR — could not reach chat endpoint]\n{type(e).__name__}: {e}"
    return {"response": answer}


@router.get("/api/sessions")
async def get_sessions():
    try:
        import sqlite3 as _sq
        from datetime import date, timedelta
        _db = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "session_state.db")
        conn = _sq.connect(_db)
        rows = conn.execute(
            "SELECT session_id, conversation_json, start_time FROM sessions "
            "WHERE session_id IS NOT NULL ORDER BY last_active DESC LIMIT 50"
        ).fetchall()
        conn.close()
        today = date.today().isoformat()
        yesterday = (date.today() - timedelta(days=1)).isoformat()
        result = {"today": [], "yesterday": [], "older": []}
        for sid, cjson, start_time in rows:
            turns = json.loads(cjson or "[]")
            first_user = next((t["content"] for t in turns if t.get("role") == "user"), None)
            title = (first_user[:40] + ("..." if len(first_user) > 40 else "")) if first_user else f"New Chat ({sid})"
            item = {"session_id": sid, "title": title, "timestamp": start_time or "", "message_count": len(turns) // 2}
            day = (start_time or "")[:10]
            if day == today:
                result["today"].append(item)
            elif day == yesterday:
                result["yesterday"].append(item)
            else:
                result["older"].append(item)
        return result
    except Exception as e:
        log.warning(f"get_sessions failed: {e}")
        return {"today": [], "yesterday": [], "older": []}


@router.post("/api/sessions/new")
async def create_session_endpoint(request: Request):
    try:
        import sqlite3 as _sq
        body = await request.json()
        sid = body.get("session_id") or f"web_{int(__import__('time').time())}"
        _db = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "session_state.db")
        now = datetime.datetime.now().isoformat()
        conn = _sq.connect(_db)
        conn.execute(
            "INSERT OR IGNORE INTO sessions (session_id, device, start_time, last_active, status, conversation_json) VALUES (?,?,?,?,?,?)",
            (sid, "web", now, now, "active", "[]"),
        )
        conn.commit()
        conn.close()
        return {"ok": True, "session_id": sid}
    except Exception as e:
        log.warning(f"create_session failed: {e}")
        return {"ok": False, "error": str(e)}


@router.get("/api/sessions/{session_id}/messages")
async def get_session_messages(session_id: str):
    try:
        import sqlite3 as _sq
        _db = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "session_state.db")
        conn = _sq.connect(_db)
        row = conn.execute("SELECT conversation_json FROM sessions WHERE session_id=?", (session_id,)).fetchone()
        conn.close()
        turns = json.loads(row[0]) if row and row[0] else []
        return {"messages": turns}
    except Exception as e:
        log.warning(f"get_session_messages failed: {e}")
        return {"messages": []}


@router.post("/webhook/{source}")
async def webhook_trigger(source: str, req: Request):
    """O6: Push-event webhook."""
    if not _verify_webhook(req):
        return JSONResponse(status_code=401, content={"ok": False, "error": "Unauthorized"})
    allowed_sources = {"github", "telegram", "calendar", "generic", "alert"}
    if source not in allowed_sources:
        return JSONResponse(status_code=400, content={"ok": False, "error": f"Unknown source '{source}'"})
    try:
        body = await req.json()
    except Exception:
        body = {}
    event = body.get("event", "push")
    message = body.get("message", "")
    payload = body.get("payload", {})
    if not message:
        if source == "github":
            repo = payload.get("repository", {}).get("full_name", "unknown repo")
            ref = payload.get("ref", "")
            pusher = payload.get("pusher", {}).get("name", "someone")
            message = f"GitHub {event} on {repo} ({ref}) by {pusher}"
        elif source == "calendar":
            message = f"Calendar event: {payload.get('summary', event)}"
        elif source == "alert":
            message = f"Alert [{event}]: {payload.get('text', json.dumps(payload)[:200])}"
        else:
            message = f"Webhook event from {source}: {event}"
    log.info(f"[webhook/{source}] {event}: {message[:100]}")

    def _process():
        from orchestrator import chat
        return chat(message, intent="chat", source="webhook")

    try:
        reply = await asyncio.to_thread(_process)
    except Exception as e:
        log.error(f"Webhook processing error: {e}")
        reply = f"[EDITH] Webhook received but processing failed: {e}"
    try:
        from telegram_bot import send_message as _tg_send
        await asyncio.to_thread(_tg_send, f"[{source.upper()} webhook]\n{message}\n\n{reply}")
    except Exception:
        pass
    return {"ok": True, "source": source, "event": event, "reply": reply}


@router.post("/tg_webhook")
async def tg_webhook(req: Request):
    """Telegram Bot API webhook endpoint."""
    if os.getenv("EDITH_NODE_TYPE", "local") != "cloud":
        return JSONResponse(status_code=403, content={"ok": False, "error": "Webhook only active on cloud node"})
    try:
        update = await req.json()
    except Exception:
        return JSONResponse(status_code=400, content={"ok": False})
    try:
        from telegram_bot import handle_telegram_update
        await asyncio.to_thread(handle_telegram_update, update)
    except Exception as e:
        log.error(f"tg_webhook handler error: {e}")
    return {"ok": True}
