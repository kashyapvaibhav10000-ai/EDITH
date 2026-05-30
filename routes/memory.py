"""
routes/memory.py — Memory, traces, and feedback endpoints.
  GET  /api/last-memory
  GET  /api/traces/recent
  GET  /api/recent_traces
  POST /api/feedback
"""

import asyncio
import datetime as _dt

from fastapi import APIRouter, Request
from config import get_logger

log = get_logger("routes.memory")
router = APIRouter()


@router.get("/api/last-memory")
async def api_last_memory():
    """Return last 3 memories from SmartMemoryManager."""
    try:
        import sqlite3 as _sql
        from config import MEMORY_ARCHIVE_PATH

        def _fetch():
            conn = _sql.connect(MEMORY_ARCHIVE_PATH)
            cur = conn.cursor()
            cur.execute(
                "SELECT key, value, timestamp FROM memories ORDER BY timestamp DESC LIMIT 3"
            )
            rows = [{"key": r[0], "value": r[1], "timestamp": r[2]} for r in cur.fetchall()]
            conn.close()
            return rows

        memories = await asyncio.to_thread(_fetch)
        return {"memories": memories}
    except Exception as e:
        return {"error": str(e), "memories": []}


@router.get("/api/traces/recent")
async def api_traces_recent(limit: int = 20):
    """Return last N traces from trace_log.db."""
    try:
        import os
        import sqlite3 as _sql
        from config import EDITH_PATH

        _trace_db = os.path.join(EDITH_PATH, "trace_log.db")

        def _fetch():
            if not os.path.exists(_trace_db):
                return []
            conn = _sql.connect(_trace_db)
            cur = conn.cursor()
            cur.execute(
                "SELECT trace_id, user_input, intent, created_at, final_status, total_layers "
                "FROM trace_index ORDER BY created_at DESC LIMIT ?",
                (limit,),
            )
            rows = [
                {
                    "trace_id": r[0],
                    "user_input": r[1],
                    "intent": r[2],
                    "created_at": r[3],
                    "final_status": r[4],
                    "total_layers": r[5],
                }
                for r in cur.fetchall()
            ]
            conn.close()
            return rows

        traces = await asyncio.to_thread(_fetch)
        return {"traces": traces}
    except Exception as e:
        return {"error": str(e), "traces": []}


@router.get("/api/recent_traces")
async def api_recent_traces(limit: int = 20):
    """Return last N routing traces from the archive DB."""
    import sqlite3 as _sql
    from config import MEMORY_ARCHIVE_PATH

    def _fetch():
        try:
            conn = _sql.connect(MEMORY_ARCHIVE_PATH)
            cur = conn.cursor()
            cur.execute(
                """
                SELECT * FROM (
                    SELECT provider, date, call_count FROM api_usage
                ) LIMIT ?
                """,
                (limit,),
            )
            rows = [{"provider": r[0], "date": r[1], "call_count": r[2]} for r in cur.fetchall()]
            conn.close()
            return rows
        except Exception:
            return []

    traces = await asyncio.to_thread(_fetch)
    return {"traces": traces}


@router.post("/api/feedback")
async def api_feedback(req: Request):
    """Tag a trace with thumbs_up / thumbs_down feedback."""
    data = await req.json()
    trace_id = data.get("trace_id", "")
    feedback = data.get("feedback", "")
    if not trace_id or feedback not in ("thumbs_up", "thumbs_down"):
        return {"ok": False, "error": "trace_id and valid feedback (thumbs_up|thumbs_down) required"}

    import sqlite3 as _sql
    from config import MEMORY_ARCHIVE_PATH

    def _tag():
        try:
            conn = _sql.connect(MEMORY_ARCHIVE_PATH)
            cur = conn.cursor()
            cur.execute("""
                CREATE TABLE IF NOT EXISTS feedback (
                    trace_id TEXT PRIMARY KEY,
                    feedback TEXT,
                    reason TEXT,
                    created_at TEXT
                )
            """)
            cur.execute(
                "INSERT OR REPLACE INTO feedback (trace_id, feedback, reason, created_at) VALUES (?, ?, ?, ?)",
                (trace_id, feedback, data.get("reason", ""), _dt.datetime.now().isoformat()),
            )
            conn.commit()
            conn.close()
            try:
                from feedback_tagger import tag_feedback
                tag_feedback(trace_id, feedback, data.get("reason", ""))
            except Exception as e:
                log.debug(f"feedback_tagger.tag_feedback failed (non-fatal): {e}")
            return True
        except Exception as e:
            log.error(f"Feedback tag failed: {e}")
            return False

    ok = await asyncio.to_thread(_tag)
    return {"ok": ok}
