"""
EDITH Session Manager — v2.0 with Device Tracking + Continuity

Ties all 4 Visions together. Handles session start/end rituals.
Every session ends with: PROFILE UPDATE · DRIFT CHECK · OPEN LOOPS · EPISODE + GRAPH

Phase 2 additions:
  - Device tracking (voice/widget/telegram/chat_server)
  - Session state persistence to SQLite for cross-device continuity
  - Session transfer between devices
  - Session context snapshot for fast resume
"""

import datetime
import uuid
import sqlite3
import os
import json
import threading
import db_pool
from config import get_logger, EDITH_PATH
from cognitive_profile import (
    update_profile, propose_profile_update, detect_drift,
    log_query, get_prime_directive
)
from self_improve import run_self_improvement
from life_os import format_open_loops
from episodic_memory import save_episode
from graph_memory import ingest_text, graph_stats

log = get_logger("session")

# ──────────────────────────────────────────────
# Session State Database
# ──────────────────────────────────────────────
_SESSION_DB = os.path.join(EDITH_PATH, "session_state.db")
_db_lock = threading.Lock()


def _get_db():
    """Get a thread-local SQLite connection for session state."""
    conn = db_pool.get(_SESSION_DB)
    conn.execute("""CREATE TABLE IF NOT EXISTS sessions (
        session_id TEXT PRIMARY KEY,
        device TEXT DEFAULT 'unknown',
        start_time TEXT,
        last_active TEXT,
        query_count INTEGER DEFAULT 0,
        queries_json TEXT DEFAULT '[]',
        context_snapshot TEXT DEFAULT '{}',
        status TEXT DEFAULT 'active'
    )""")
    conn.commit()
    return conn


# ──────────────────────────────────────────────
# Current Session (in-memory, fast access)
# ──────────────────────────────────────────────
_session_lock = threading.Lock()  # Protects _current_session from concurrent mutations
_current_session = {
    "id": None,
    "start_time": None,
    "queries": [],
    "device": "unknown",
    "context_snapshot": {},
}


# ──────────────────────────────────────────────
# Session Lifecycle
# ──────────────────────────────────────────────
def start_session(device: str = "unknown") -> str:
    """Initialize a new EDITH session with device tracking."""
    session_id = str(uuid.uuid4())[:8]
    now = datetime.datetime.now()

    with _session_lock:
        _current_session["id"] = session_id
        _current_session["start_time"] = now
        _current_session["queries"] = []
        _current_session["device"] = device
        _current_session["context_snapshot"] = {}

    # Persist to SQLite
    _persist_session()

    log.info(f"Session started: {session_id} on {device}")
    return session_id


def track_query(user_input: str, device: str = None):
    """Track a query in the current session."""
    with _session_lock:
        _current_session["queries"].append(user_input)

        if device and device != _current_session.get("device"):
            old_device = _current_session.get("device", "unknown")
            _current_session["device"] = device
            log.info(f"Device switch detected: {old_device} → {device}")

    log_query(user_input, _current_session["id"] or "unknown")

    # Periodic persist (every 5 queries)
    with _session_lock:
        query_count = len(_current_session["queries"])
    if query_count % 5 == 0:
        _persist_session()


def get_session_id() -> str:
    with _session_lock:
        return _current_session["id"] or "unknown"


def get_session_device() -> str:
    """Get the current session's device."""
    with _session_lock:
        return _current_session.get("device", "unknown")


def set_context_snapshot(key: str, value):
    """Save a context value for cross-device session resume."""
    with _session_lock:
        _current_session["context_snapshot"][key] = value


def get_context_snapshot(key: str, default=None):
    """Get a previously saved context value."""
    with _session_lock:
        return _current_session["context_snapshot"].get(key, default)


# ──────────────────────────────────────────────
# Session Transfer (cross-device continuity)
# ──────────────────────────────────────────────
def transfer_session(new_device: str) -> str:
    """Transfer the current session to a new device.

    Saves full state, then updates the device field.
    Returns a status message.
    """
    with _session_lock:
        old_device = _current_session.get("device", "unknown")
        session_id = _current_session.get("id")
        if not session_id:
            return "No active session to transfer."

    # Persist current state first
    _persist_session()

    # Update device
    with _session_lock:
        _current_session["device"] = new_device

    # Update in DB
    with _db_lock:
        try:
            conn = _get_db()
            conn.execute(
                "UPDATE sessions SET device = ?, last_active = ? WHERE session_id = ?",
                (new_device, datetime.datetime.now().isoformat(), session_id)
            )
            conn.commit()
            db_pool.put(_SESSION_DB, conn)
        except Exception as e:
            log.error(f"Session transfer DB update failed: {e}")

    msg = f"Session {session_id} transferred: {old_device} → {new_device}"
    log.info(msg)
    return msg


def resume_session(session_id: str) -> str:
    """Resume a previous session by ID. Loads state from SQLite."""
    with _db_lock:
        try:
            conn = _get_db()
            row = conn.execute(
                "SELECT session_id, device, start_time, queries_json, context_snapshot "
                "FROM sessions WHERE session_id = ?",
                (session_id,)
            ).fetchone()
            db_pool.put(_SESSION_DB, conn)

            if not row:
                return f"Session {session_id} not found."

            _current_session["id"] = row[0]
            _current_session["device"] = row[1]
            _current_session["start_time"] = datetime.datetime.fromisoformat(row[2])
            _current_session["queries"] = json.loads(row[3])
            _current_session["context_snapshot"] = json.loads(row[4]) if row[4] else {}

            log.info(f"Resumed session {session_id} ({len(_current_session['queries'])} queries)")
            return f"Resumed session {session_id} with {len(_current_session['queries'])} queries"

        except Exception as e:
            log.error(f"Session resume failed: {e}")
            return f"Failed to resume session: {e}"


def get_recent_sessions(limit: int = 5) -> list:
    """Get recent sessions from the database."""
    with _db_lock:
        try:
            conn = _get_db()
            rows = conn.execute(
                "SELECT session_id, device, start_time, query_count, status "
                "FROM sessions ORDER BY last_active DESC LIMIT ?",
                (limit,)
            ).fetchall()
            db_pool.put(_SESSION_DB, conn)
            return [
                {
                    "id": r[0], "device": r[1], "start_time": r[2],
                    "query_count": r[3], "status": r[4]
                }
                for r in rows
            ]
        except Exception as e:
            log.error(f"Recent sessions query failed: {e}")
            return []


# ──────────────────────────────────────────────
# Session Persistence
# ──────────────────────────────────────────────
def _persist_session():
    """Save current session state to SQLite."""
    session_id = _current_session.get("id")
    if not session_id:
        return

    with _db_lock:
        try:
            conn = _get_db()
            conn.execute("""INSERT OR REPLACE INTO sessions
                (session_id, device, start_time, last_active, query_count, queries_json, context_snapshot, status)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    session_id,
                    _current_session.get("device", "unknown"),
                    _current_session["start_time"].isoformat() if _current_session["start_time"] else "",
                    datetime.datetime.now().isoformat(),
                    len(_current_session["queries"]),
                    json.dumps(_current_session["queries"][-50:]),  # last 50 queries
                    json.dumps(_current_session.get("context_snapshot", {})),
                    "active"
                )
            )
            conn.commit()
            db_pool.put(_SESSION_DB, conn)
        except Exception as e:
            log.error(f"Session persist failed: {e}")


# ──────────────────────────────────────────────
# End-of-Session Ritual (preserved from v1)
# ──────────────────────────────────────────────
def end_session() -> str:
    """End-of-session ritual: Profile Update · Proposed Upgrade · Open Loops."""
    session_id = _current_session["id"] or "unknown"
    queries = _current_session["queries"]
    device = _current_session.get("device", "unknown")
    duration = ""
    if _current_session["start_time"]:
        elapsed = datetime.datetime.now() - _current_session["start_time"]
        minutes = int(elapsed.total_seconds() / 60)
        duration = f"{minutes} minutes"

    output_parts = []
    output_parts.append(f"""
╔══════════════════════════════════════════════════╗
║       E.D.I.T.H — SESSION SUMMARY               ║
║       Session: {session_id:<8}  Duration: {duration:<12}   ║
║       Queries: {len(queries):<8}  Device: {device:<12}     ║
╚══════════════════════════════════════════════════╝""")

    # 1. Profile Update
    output_parts.append("\n📊 PROFILE UPDATE")
    if len(queries) >= 2:
        try:
            proposal = propose_profile_update(queries)
            output_parts.append(f"  {proposal}")
            # Auto-save the observation
            if "OBSERVATION:" in proposal:
                obs = proposal.split("OBSERVATION:")[-1].strip()
                update_profile(obs, session_id)
                output_parts.append(f"  ✅ Saved to profile.")
        except Exception as e:
            output_parts.append(f"  Could not generate: {e}")
    else:
        output_parts.append("  Not enough queries this session for update.")

    # 2. Drift Check
    output_parts.append("\n🧭 DRIFT CHECK")
    try:
        drift = detect_drift()
        output_parts.append(f"  {drift}")
    except Exception as e:
        output_parts.append(f"  Could not check: {e}")

    # 3. Open Loops
    output_parts.append("\n🔄 OPEN LOOPS")
    loops = format_open_loops()
    output_parts.append(f"  {loops}")

    # 4. Episodic Memory — save full session timeline
    output_parts.append("\n🧠 EPISODIC MEMORY")
    try:
        save_episode(session_id, queries)
        output_parts.append(f"  ✅ Session saved as episode ({len(queries)} queries)")
    except Exception as e:
        output_parts.append(f"  Could not save episode: {e}")

    # 5. Knowledge Graph — extract relationships
    output_parts.append("\n🕸️ KNOWLEDGE GRAPH")
    if len(queries) >= 2:
        try:
            joined = ". ".join(queries[-10:])  # Last 10 queries
            triples = ingest_text(joined)
            if triples:
                output_parts.append(f"  ✅ Extracted {len(triples)} new relationships")
                for s, r, o in triples:
                    output_parts.append(f"     {s} --[{r}]--> {o}")
            else:
                output_parts.append("  No new relationships found.")
            output_parts.append(f"  📊 {graph_stats()}")
        except Exception as e:
            output_parts.append(f"  Could not update graph: {e}")
    else:
        output_parts.append("  Not enough queries for graph extraction.")

    # 6. Prime Directive Reminder
    output_parts.append(f"\n🎯 PRIME DIRECTIVE: {get_prime_directive()}")

    output_parts.append("\n" + "═" * 52)

    result = "\n".join(output_parts)
    log.info(f"Session {session_id} ended ({len(queries)} queries, {duration}, {device})")

    # Mark session as ended in DB
    with _db_lock:
        try:
            conn = _get_db()
            conn.execute(
                "UPDATE sessions SET status = 'ended', last_active = ? WHERE session_id = ?",
                (datetime.datetime.now().isoformat(), session_id)
            )
            conn.commit()
            db_pool.put(_SESSION_DB, conn)
        except Exception:
            pass

    return result


def session_status() -> str:
    """Get current session info."""
    sid = _current_session["id"] or "No active session"
    count = len(_current_session["queries"])
    device = _current_session.get("device", "unknown")
    elapsed = ""
    if _current_session["start_time"]:
        mins = int((datetime.datetime.now() - _current_session["start_time"]).total_seconds() / 60)
        elapsed = f"{mins}m"
    return f"Session: {sid} | Queries: {count} | Duration: {elapsed} | Device: {device}"


if __name__ == "__main__":
    print("[EDITH Session] Testing v2.0...")
    start_session(device="widget")
    track_query("How do I fix this Python error?")
    track_query("Search for best ML frameworks 2026")
    track_query("What is my schedule today?", device="telegram")
    print(f"Status: {session_status()}")
    print(f"Device: {get_session_device()}")
    transfer_session("voice")
    print(f"After transfer: {session_status()}")
    recent = get_recent_sessions()
    print(f"Recent sessions: {recent}")
    print(end_session())
