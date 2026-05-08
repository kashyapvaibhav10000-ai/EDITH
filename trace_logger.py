"""
EDITH Trace Logger — Phase 7.1

Generates unique TRACE_ID at input layer, passed through every layer.
Each node appends: timestamp, input/output summary, confidence, status.
Stored in SQLite (trace_log.db), privacy-safe (summaries only).
"""

import uuid
import time
import sqlite3
import os
import json
import threading
import db_pool
from config import get_logger, EDITH_PATH

log = get_logger("trace_logger")

_TRACE_DB = os.path.join(EDITH_PATH, "trace_log.db")
_db_lock = threading.Lock()


def _get_db():
    conn = db_pool.get(_TRACE_DB)
    conn.execute("""CREATE TABLE IF NOT EXISTS traces (
        trace_id TEXT NOT NULL,
        layer TEXT NOT NULL,
        timestamp REAL NOT NULL,
        input_summary TEXT,
        output_summary TEXT,
        confidence REAL DEFAULT 0.0,
        status TEXT DEFAULT 'ok',
        metadata_json TEXT DEFAULT '{}',
        PRIMARY KEY (trace_id, layer, timestamp)
    )""")
    conn.execute("""CREATE TABLE IF NOT EXISTS trace_index (
        trace_id TEXT PRIMARY KEY,
        user_input TEXT,
        intent TEXT,
        device TEXT DEFAULT 'unknown',
        created_at REAL,
        completed_at REAL,
        total_layers INTEGER DEFAULT 0,
        final_status TEXT DEFAULT 'pending',
        feedback TEXT DEFAULT 'none'
    )""")
    # Additive telemetry columns — safe to add to existing tables
    for alter in [
        "ALTER TABLE trace_index ADD COLUMN tokens_in INTEGER DEFAULT 0",
        "ALTER TABLE trace_index ADD COLUMN tokens_out INTEGER DEFAULT 0",
        "ALTER TABLE trace_index ADD COLUMN cost_usd REAL DEFAULT 0.0",
        "ALTER TABLE trace_index ADD COLUMN provider TEXT DEFAULT ''",
    ]:
        try:
            conn.execute(alter)
        except Exception:
            pass  # Column already exists
    conn.commit()
    return conn


def new_trace(user_input: str, intent: str = "", device: str = "unknown") -> str:
    """Create a new trace and return its TRACE_ID."""
    import config
    if not config.TRACE_ENABLED:
        return "disabled"
    trace_id = str(uuid.uuid4())[:12]
    with _db_lock:
        try:
            conn = _get_db()
            conn.execute(
                "INSERT INTO trace_index (trace_id, user_input, intent, device, created_at) VALUES (?,?,?,?,?)",
                (trace_id, user_input[:200], intent, device, time.time())
            )
            conn.commit()
            db_pool.put(_TRACE_DB, conn)
        except Exception as e:
            log.error(f"Trace creation failed: {e}")
    return trace_id


def log_layer(trace_id: str, layer: str, input_summary: str = "",
              output_summary: str = "", confidence: float = 0.0,
              status: str = "ok", metadata: dict = None):
    """Log a trace entry for a specific layer."""
    import config
    if not config.TRACE_ENABLED or trace_id == "disabled":
        return
    with _db_lock:
        try:
            conn = _get_db()
            conn.execute(
                "INSERT INTO traces (trace_id, layer, timestamp, input_summary, output_summary, confidence, status, metadata_json) VALUES (?,?,?,?,?,?,?,?)",
                (trace_id, layer, time.time(), input_summary[:200],
                 output_summary[:200], confidence, status,
                 json.dumps(metadata or {}))
            )
            conn.execute(
                "UPDATE trace_index SET total_layers = total_layers + 1 WHERE trace_id = ?",
                (trace_id,)
            )
            conn.commit()
            db_pool.put(_TRACE_DB, conn)
        except Exception as e:
            log.error(f"Trace log failed: {e}")


def complete_trace(trace_id: str, status: str = "success",
                   tokens_in: int = 0, tokens_out: int = 0,
                   cost_usd: float = 0.0, provider: str = ""):
    """Mark a trace as completed, optionally with telemetry data."""
    with _db_lock:
        try:
            conn = _get_db()
            conn.execute(
                "UPDATE trace_index SET completed_at = ?, final_status = ?, "
                "tokens_in = ?, tokens_out = ?, cost_usd = ?, provider = ? "
                "WHERE trace_id = ?",
                (time.time(), status, tokens_in, tokens_out, cost_usd, provider, trace_id)
            )
            conn.commit()
            db_pool.put(_TRACE_DB, conn)
        except Exception as e:
            log.error(f"Trace completion failed: {e}")


def set_feedback(trace_id: str, feedback: str):
    """Set feedback (thumbs_up/thumbs_down) for a trace."""
    with _db_lock:
        try:
            conn = _get_db()
            conn.execute(
                "UPDATE trace_index SET feedback = ? WHERE trace_id = ?",
                (feedback, trace_id)
            )
            conn.commit()
            db_pool.put(_TRACE_DB, conn)
        except Exception as e:
            log.error(f"Feedback set failed: {e}")


def get_trace(trace_id: str) -> dict:
    """Get full trace with all layers."""
    with _db_lock:
        try:
            conn = _get_db()
            idx = conn.execute(
                "SELECT * FROM trace_index WHERE trace_id = ?", (trace_id,)
            ).fetchone()
            layers = conn.execute(
                "SELECT layer, timestamp, input_summary, output_summary, confidence, status "
                "FROM traces WHERE trace_id = ? ORDER BY timestamp",
                (trace_id,)
            ).fetchall()
            db_pool.put(_TRACE_DB, conn)
            if not idx:
                return {}
            return {
                "trace_id": idx[0], "user_input": idx[1], "intent": idx[2],
                "device": idx[3], "created_at": idx[4], "completed_at": idx[5],
                "total_layers": idx[6], "final_status": idx[7], "feedback": idx[8],
                "layers": [
                    {"layer": l[0], "timestamp": l[1], "input": l[2],
                     "output": l[3], "confidence": l[4], "status": l[5]}
                    for l in layers
                ]
            }
        except Exception as e:
            log.error(f"Trace get failed: {e}")
            return {}


def get_recent_traces(limit: int = 50) -> list:
    """Get recent traces for Dashboard."""
    with _db_lock:
        try:
            conn = _get_db()
            rows = conn.execute(
                "SELECT trace_id, user_input, intent, device, created_at, final_status, feedback "
                "FROM trace_index ORDER BY created_at DESC LIMIT ?",
                (limit,)
            ).fetchall()
            db_pool.put(_TRACE_DB, conn)
            return [
                {"trace_id": r[0], "input": r[1], "intent": r[2],
                 "device": r[3], "created_at": r[4], "status": r[5], "feedback": r[6]}
                for r in rows
            ]
        except Exception as e:
            log.error(f"Recent traces failed: {e}")
            return []


def get_feedback_stats() -> dict:
    """Get feedback statistics for tuner."""
    with _db_lock:
        try:
            conn = _get_db()
            total = conn.execute("SELECT COUNT(*) FROM trace_index").fetchone()[0]
            up = conn.execute("SELECT COUNT(*) FROM trace_index WHERE feedback='thumbs_up'").fetchone()[0]
            down = conn.execute("SELECT COUNT(*) FROM trace_index WHERE feedback='thumbs_down'").fetchone()[0]
            db_pool.put(_TRACE_DB, conn)
            return {"total": total, "thumbs_up": up, "thumbs_down": down,
                    "satisfaction": round(up / max(up + down, 1) * 100, 1)}
        except Exception as e:
            return {"total": 0, "thumbs_up": 0, "thumbs_down": 0, "satisfaction": 0}


if __name__ == "__main__":
    tid = new_trace("What is the weather?", intent="weather", device="widget")
    log_layer(tid, "intent", "weather query", "intent=weather", confidence=0.95)
    log_layer(tid, "router", "weather", "Groq response", confidence=0.9)
    complete_trace(tid, "success")
    set_feedback(tid, "thumbs_up")
    print(json.dumps(get_trace(tid), indent=2))
    print(f"\nStats: {get_feedback_stats()}")
