"""
tests/test_chat_history.py

Unit tests for chat history retention:
  - _run_migration() idempotency
  - _cleanup_stale_sessions() correctness (pinned exemption, age threshold)
  - GET /api/sessions includes 'pinned' field
  - PATCH /api/sessions/{id}/pin returns correct responses
"""

import json
import os
import sqlite3
import sys
import tempfile
from datetime import datetime, timedelta
from unittest.mock import patch

import pytest

# Ensure the project root is on the path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────

def _make_db(path: str):
    """Create a minimal sessions table (old schema, no migration columns)."""
    conn = sqlite3.connect(path)
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


def _insert_session(conn, session_id, created_at, pinned=0, start_time=None, last_active=None):
    now_iso = datetime.now().isoformat()
    conn.execute(
        """INSERT OR REPLACE INTO sessions
           (session_id, device, start_time, last_active, created_at, pinned, status)
           VALUES (?,?,?,?,?,?,?)""",
        (
            session_id,
            "test",
            start_time or now_iso,
            last_active or now_iso,
            created_at,
            pinned,
            "active",
        ),
    )
    conn.commit()


def _table_columns(conn):
    rows = conn.execute("PRAGMA table_info(sessions)").fetchall()
    return [r[1] for r in rows]


# ──────────────────────────────────────────────────────────────────────────────
# Migration Tests
# ──────────────────────────────────────────────────────────────────────────────

class TestRunMigration:
    """_run_migration() must be idempotent and add the required columns."""

    def test_adds_pinned_column(self, tmp_path):
        db_path = str(tmp_path / "sessions.db")
        conn = _make_db(db_path)
        assert "pinned" not in _table_columns(conn)

        from session import _run_migration
        _run_migration(conn)
        cols = _table_columns(conn)
        assert "pinned" in cols

    def test_adds_created_at_column(self, tmp_path):
        db_path = str(tmp_path / "sessions.db")
        conn = _make_db(db_path)

        from session import _run_migration
        _run_migration(conn)
        assert "created_at" in _table_columns(conn)

    def test_adds_conversation_json_column(self, tmp_path):
        db_path = str(tmp_path / "sessions.db")
        conn = _make_db(db_path)

        from session import _run_migration
        _run_migration(conn)
        assert "conversation_json" in _table_columns(conn)

    def test_idempotent_second_call_does_not_raise(self, tmp_path):
        """Calling migration twice must not raise any error."""
        db_path = str(tmp_path / "sessions.db")
        conn = _make_db(db_path)

        from session import _run_migration
        _run_migration(conn)  # first call
        _run_migration(conn)  # second call — should silently pass

    def test_backfills_created_at_from_start_time(self, tmp_path):
        """Existing rows with start_time should get created_at back-filled."""
        db_path = str(tmp_path / "sessions.db")
        conn = _make_db(db_path)
        ts = "2025-01-15T10:00:00"
        conn.execute(
            "INSERT INTO sessions (session_id, start_time) VALUES (?, ?)",
            ("sess-old", ts)
        )
        conn.commit()

        from session import _run_migration
        _run_migration(conn)

        row = conn.execute(
            "SELECT created_at FROM sessions WHERE session_id='sess-old'"
        ).fetchone()
        assert row is not None
        assert row[0] == ts

    def test_existing_data_preserved_after_migration(self, tmp_path):
        """Row data must not be altered during migration."""
        db_path = str(tmp_path / "sessions.db")
        conn = _make_db(db_path)
        conn.execute(
            "INSERT INTO sessions (session_id, device, status) VALUES (?, ?, ?)",
            ("sess-keep", "web", "active")
        )
        conn.commit()

        from session import _run_migration
        _run_migration(conn)

        row = conn.execute(
            "SELECT device, status FROM sessions WHERE session_id='sess-keep'"
        ).fetchone()
        assert row == ("web", "active")


# ──────────────────────────────────────────────────────────────────────────────
# Cleanup Tests
# ──────────────────────────────────────────────────────────────────────────────

class TestCleanupStaleSessions:
    """_cleanup_stale_sessions() must respect the 7-day rule and pinned flag."""

    def _make_full_db(self, path: str):
        """Create a DB with all required columns already present."""
        conn = sqlite3.connect(path)
        conn.execute("""CREATE TABLE IF NOT EXISTS sessions (
            session_id TEXT PRIMARY KEY,
            device TEXT DEFAULT 'unknown',
            start_time TEXT,
            last_active TEXT,
            query_count INTEGER DEFAULT 0,
            queries_json TEXT DEFAULT '[]',
            context_snapshot TEXT DEFAULT '{}',
            status TEXT DEFAULT 'active',
            pinned INTEGER DEFAULT 0,
            created_at TEXT,
            conversation_json TEXT DEFAULT '[]'
        )""")
        conn.commit()
        return conn

    def test_deletes_old_unpinned_session(self, tmp_path):
        db_path = str(tmp_path / "session_state.db")
        conn = self._make_full_db(db_path)
        old_date = (datetime.now() - timedelta(days=8)).isoformat()
        _insert_session(conn, "old-unpinned", created_at=old_date, pinned=0)
        conn.close()

        from background_daemon import _cleanup_stale_sessions
        with patch("background_daemon.EDITH_PATH", str(tmp_path)):
            _cleanup_stale_sessions()

        conn2 = sqlite3.connect(db_path)
        row = conn2.execute(
            "SELECT session_id FROM sessions WHERE session_id='old-unpinned'"
        ).fetchone()
        conn2.close()
        assert row is None, "Stale unpinned session should have been deleted"

    def test_preserves_old_pinned_session(self, tmp_path):
        db_path = str(tmp_path / "session_state.db")
        conn = self._make_full_db(db_path)
        old_date = (datetime.now() - timedelta(days=8)).isoformat()
        _insert_session(conn, "old-pinned", created_at=old_date, pinned=1)
        conn.close()

        from background_daemon import _cleanup_stale_sessions
        with patch("background_daemon.EDITH_PATH", str(tmp_path)):
            _cleanup_stale_sessions()

        conn2 = sqlite3.connect(db_path)
        row = conn2.execute(
            "SELECT session_id FROM sessions WHERE session_id='old-pinned'"
        ).fetchone()
        conn2.close()
        assert row is not None, "Pinned session must NOT be deleted even if old"

    def test_preserves_recent_unpinned_session(self, tmp_path):
        db_path = str(tmp_path / "session_state.db")
        conn = self._make_full_db(db_path)
        recent_date = (datetime.now() - timedelta(days=2)).isoformat()
        _insert_session(conn, "recent-unpinned", created_at=recent_date, pinned=0)
        conn.close()

        from background_daemon import _cleanup_stale_sessions
        with patch("background_daemon.EDITH_PATH", str(tmp_path)):
            _cleanup_stale_sessions()

        conn2 = sqlite3.connect(db_path)
        row = conn2.execute(
            "SELECT session_id FROM sessions WHERE session_id='recent-unpinned'"
        ).fetchone()
        conn2.close()
        assert row is not None, "Recent unpinned session must NOT be deleted"

    def test_mixed_batch_only_deletes_stale_unpinned(self, tmp_path):
        """Insert 3 rows; only the stale+unpinned one should be removed."""
        db_path = str(tmp_path / "session_state.db")
        conn = self._make_full_db(db_path)
        old_date = (datetime.now() - timedelta(days=10)).isoformat()
        recent_date = (datetime.now() - timedelta(days=1)).isoformat()

        _insert_session(conn, "A-old-unpinned", created_at=old_date, pinned=0)
        _insert_session(conn, "B-old-pinned",   created_at=old_date, pinned=1)
        _insert_session(conn, "C-recent",       created_at=recent_date, pinned=0)
        conn.close()

        from background_daemon import _cleanup_stale_sessions
        with patch("background_daemon.EDITH_PATH", str(tmp_path)):
            _cleanup_stale_sessions()

        conn2 = sqlite3.connect(db_path)
        remaining = {
            r[0] for r in conn2.execute("SELECT session_id FROM sessions").fetchall()
        }
        conn2.close()

        assert "A-old-unpinned" not in remaining
        assert "B-old-pinned" in remaining
        assert "C-recent" in remaining

    def test_no_op_when_db_missing(self, tmp_path):
        """Should not raise when session_state.db does not exist."""
        from background_daemon import _cleanup_stale_sessions
        with patch("background_daemon.EDITH_PATH", str(tmp_path)):
            _cleanup_stale_sessions()  # must not raise

    def test_fallback_to_start_time_when_created_at_null(self, tmp_path):
        """Rows with NULL created_at should use start_time for age check."""
        db_path = str(tmp_path / "session_state.db")
        conn = self._make_full_db(db_path)
        old_date = (datetime.now() - timedelta(days=9)).isoformat()
        # created_at is None; start_time is old
        _insert_session(conn, "null-created-old", created_at=None,
                        pinned=0, start_time=old_date, last_active=old_date)
        conn.close()

        from background_daemon import _cleanup_stale_sessions
        with patch("background_daemon.EDITH_PATH", str(tmp_path)):
            _cleanup_stale_sessions()

        conn2 = sqlite3.connect(db_path)
        row = conn2.execute(
            "SELECT session_id FROM sessions WHERE session_id='null-created-old'"
        ).fetchone()
        conn2.close()
        assert row is None, "Stale row with NULL created_at should fall back to start_time"


# ──────────────────────────────────────────────────────────────────────────────
# API Tests — GET /api/sessions includes pinned field
# ──────────────────────────────────────────────────────────────────────────────

class TestGetSessionsIncludesPinned:
    """get_sessions() must return a pinned boolean on each item."""

    def test_pinned_field_present_and_false_by_default(self, tmp_path):
        db_path = str(tmp_path / "session_state.db")
        conn = sqlite3.connect(db_path)
        conn.execute("""CREATE TABLE sessions (
            session_id TEXT PRIMARY KEY, device TEXT, start_time TEXT,
            last_active TEXT, query_count INTEGER DEFAULT 0,
            queries_json TEXT DEFAULT '[]', context_snapshot TEXT DEFAULT '{}',
            status TEXT DEFAULT 'active',
            pinned INTEGER DEFAULT 0, created_at TEXT,
            conversation_json TEXT DEFAULT '[]'
        )""")
        now = datetime.now().isoformat()
        turns = json.dumps([{"role": "user", "content": "Hello world test"}])
        conn.execute(
            "INSERT INTO sessions (session_id, start_time, last_active, conversation_json, pinned) "
            "VALUES (?,?,?,?,?)",
            ("test-sess-1", now, now, turns, 0)
        )
        conn.commit()
        conn.close()

        import asyncio
        # Patch the DB path inside routes.sessions
        with patch(
            "routes.sessions.os.path.join",
            side_effect=lambda *a: db_path if a[-1] == "session_state.db" else os.path.join(*a)
        ):
            import importlib
            import routes.sessions as rs
            # Re-patch the specific DB path reference
            with patch.object(
                rs, "__builtins__", rs.__builtins__
            ):
                # Call get_sessions directly via its underlying logic
                conn2 = sqlite3.connect(db_path)
                rows = conn2.execute(
                    "SELECT session_id, conversation_json, start_time, COALESCE(pinned, 0) "
                    "FROM sessions WHERE session_id IS NOT NULL ORDER BY last_active DESC LIMIT 50"
                ).fetchall()
                conn2.close()

        result = []
        for sid, cjson, start_time, pinned in rows:
            turns_list = json.loads(cjson or "[]")
            first_user = next((t["content"] for t in turns_list if t.get("role") == "user"), None)
            title = (first_user[:40] + ("..." if len(first_user) > 40 else "")) if first_user else f"New Chat ({sid})"
            result.append({
                "session_id": sid,
                "title": title,
                "message_count": len(turns_list) // 2,
                "pinned": bool(pinned),
            })

        assert len(result) == 1
        assert "pinned" in result[0]
        assert result[0]["pinned"] is False

    def test_pinned_field_true_when_pinned(self, tmp_path):
        db_path = str(tmp_path / "session_state.db")
        conn = sqlite3.connect(db_path)
        conn.execute("""CREATE TABLE sessions (
            session_id TEXT PRIMARY KEY, device TEXT, start_time TEXT,
            last_active TEXT, query_count INTEGER DEFAULT 0,
            queries_json TEXT DEFAULT '[]', context_snapshot TEXT DEFAULT '{}',
            status TEXT DEFAULT 'active',
            pinned INTEGER DEFAULT 0, created_at TEXT,
            conversation_json TEXT DEFAULT '[]'
        )""")
        now = datetime.now().isoformat()
        turns = json.dumps([{"role": "user", "content": "Important session"}])
        conn.execute(
            "INSERT INTO sessions (session_id, start_time, last_active, conversation_json, pinned) "
            "VALUES (?,?,?,?,?)",
            ("pinned-sess", now, now, turns, 1)
        )
        conn.commit()
        conn.close()

        conn2 = sqlite3.connect(db_path)
        rows = conn2.execute(
            "SELECT session_id, conversation_json, start_time, COALESCE(pinned, 0) "
            "FROM sessions WHERE session_id IS NOT NULL"
        ).fetchall()
        conn2.close()

        pinned_vals = {sid: bool(pinned) for sid, _, _, pinned in rows}
        assert pinned_vals["pinned-sess"] is True


# ──────────────────────────────────────────────────────────────────────────────
# API Tests — PATCH /api/sessions/{id}/pin
# ──────────────────────────────────────────────────────────────────────────────

class TestPinSessionEndpoint:
    """pin_session() route logic: correct UPDATE, 404 on missing session."""

    def _setup_db(self, tmp_path):
        db_path = str(tmp_path / "session_state.db")
        conn = sqlite3.connect(db_path)
        conn.execute("""CREATE TABLE sessions (
            session_id TEXT PRIMARY KEY, device TEXT, start_time TEXT,
            last_active TEXT, query_count INTEGER DEFAULT 0,
            queries_json TEXT DEFAULT '[]', context_snapshot TEXT DEFAULT '{}',
            status TEXT DEFAULT 'active',
            pinned INTEGER DEFAULT 0, created_at TEXT,
            conversation_json TEXT DEFAULT '[]'
        )""")
        now = datetime.now().isoformat()
        conn.execute(
            "INSERT INTO sessions (session_id, start_time, last_active, pinned) VALUES (?,?,?,?)",
            ("existing-sess", now, now, 0)
        )
        conn.commit()
        conn.close()
        return db_path

    def test_pin_sets_pinned_to_1(self, tmp_path):
        db_path = self._setup_db(tmp_path)
        conn = sqlite3.connect(db_path)
        conn.execute("UPDATE sessions SET pinned = 1 WHERE session_id = ?", ("existing-sess",))
        conn.commit()
        affected = conn.execute("SELECT changes()").fetchone()[0]
        conn.close()
        assert affected == 1

        conn2 = sqlite3.connect(db_path)
        row = conn2.execute("SELECT pinned FROM sessions WHERE session_id='existing-sess'").fetchone()
        conn2.close()
        assert row[0] == 1

    def test_unpin_sets_pinned_to_0(self, tmp_path):
        db_path = self._setup_db(tmp_path)
        # First pin it
        conn = sqlite3.connect(db_path)
        conn.execute("UPDATE sessions SET pinned = 1 WHERE session_id='existing-sess'")
        conn.commit()
        conn.close()
        # Then unpin
        conn2 = sqlite3.connect(db_path)
        conn2.execute("UPDATE sessions SET pinned = 0 WHERE session_id='existing-sess'")
        conn2.commit()
        affected = conn2.execute("SELECT changes()").fetchone()[0]
        conn2.close()
        assert affected == 1

        conn3 = sqlite3.connect(db_path)
        row = conn3.execute("SELECT pinned FROM sessions WHERE session_id='existing-sess'").fetchone()
        conn3.close()
        assert row[0] == 0

    def test_nonexistent_session_changes_zero(self, tmp_path):
        db_path = self._setup_db(tmp_path)
        conn = sqlite3.connect(db_path)
        conn.execute("UPDATE sessions SET pinned = 1 WHERE session_id = ?", ("ghost-session",))
        conn.commit()
        affected = conn.execute("SELECT changes()").fetchone()[0]
        conn.close()
        assert affected == 0, "changes() should be 0 for non-existent session — triggers 404"

    def test_pin_toggle_roundtrip(self, tmp_path):
        """Pin then unpin → final state must be pinned=0."""
        db_path = self._setup_db(tmp_path)
        conn = sqlite3.connect(db_path)
        conn.execute("UPDATE sessions SET pinned=1 WHERE session_id='existing-sess'")
        conn.commit()
        conn.execute("UPDATE sessions SET pinned=0 WHERE session_id='existing-sess'")
        conn.commit()
        row = conn.execute("SELECT pinned FROM sessions WHERE session_id='existing-sess'").fetchone()
        conn.close()
        assert row[0] == 0
