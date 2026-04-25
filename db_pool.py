"""
EDITH DB Pool — Item 9: SQLite connection pooling + WAL mode

Thread-safe connection pool for SQLite. Each DB path gets its own pool.
WAL mode enabled on all connections for concurrent read/write.
Use as context manager or call get()/put() directly.

Usage:
    with db_pool.connection(path) as conn:
        conn.execute("SELECT ...")

    # Or imperatively:
    conn = db_pool.get(path)
    conn.execute(...)
    db_pool.put(path, conn)
"""

import sqlite3
import threading
import queue
import os
from typing import Dict
from contextlib import contextmanager

from config import get_logger
from errors import Result

log = get_logger("db_pool")

_POOL_SIZE = 5      # connections per DB path
_TIMEOUT   = 10.0   # seconds to wait for a connection


class _ConnectionPool:
    """Per-database connection pool."""

    def __init__(self, db_path: str, size: int = _POOL_SIZE):
        self._path = db_path
        self._pool: queue.Queue = queue.Queue(maxsize=size)
        self._size = size
        self._lock = threading.Lock()
        self._created = 0

        # Pre-create one connection to test + enable WAL
        self._fill()

    def _make_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(
            self._path,
            check_same_thread=False,
            timeout=30.0,
        )
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA cache_size=-8192")  # 8 MB page cache
        conn.row_factory = sqlite3.Row
        return conn

    def _fill(self):
        """Pre-create one connection to verify the DB is accessible."""
        try:
            conn = self._make_connection()
            self._pool.put_nowait(conn)
            with self._lock:
                self._created = 1
        except Exception as e:
            log.error(f"DB pool init failed for {self._path}: {e}")

    def get(self, timeout: float = _TIMEOUT) -> sqlite3.Connection:
        """Borrow a connection. Creates new one if pool empty (up to size)."""
        try:
            return self._pool.get_nowait()
        except queue.Empty:
            pass

        with self._lock:
            if self._created < self._size:
                conn = self._make_connection()
                self._created += 1
                return conn

        # Pool at capacity — wait for one to be returned
        try:
            return self._pool.get(timeout=timeout)
        except queue.Empty:
            raise TimeoutError(f"No connection available for {self._path} after {timeout}s")

    def put(self, conn: sqlite3.Connection):
        """Return a connection to the pool."""
        try:
            self._pool.put_nowait(conn)
        except queue.Full:
            # Pool overflowed (shouldn't happen) — close the extra conn
            try:
                conn.close()
            except Exception:
                pass

    def close_all(self):
        """Close all pooled connections."""
        while True:
            try:
                conn = self._pool.get_nowait()
                conn.close()
            except queue.Empty:
                break
        with self._lock:
            self._created = 0

    def stats(self) -> dict:
        return {
            "path": self._path,
            "pool_size": self._size,
            "created": self._created,
            "available": self._pool.qsize(),
        }


# ──────────────────────────────────────────────
# Global registry
# ──────────────────────────────────────────────
_pools: Dict[str, _ConnectionPool] = {}
_registry_lock = threading.Lock()


def _get_pool(db_path: str) -> _ConnectionPool:
    abs_path = os.path.abspath(db_path)
    with _registry_lock:
        if abs_path not in _pools:
            _pools[abs_path] = _ConnectionPool(abs_path)
        return _pools[abs_path]


def get(db_path: str, timeout: float = _TIMEOUT) -> sqlite3.Connection:
    """Borrow a connection from the pool for db_path."""
    return _get_pool(db_path).get(timeout=timeout)


def put(db_path: str, conn: sqlite3.Connection):
    """Return a connection to the pool for db_path."""
    abs_path = os.path.abspath(db_path)
    if abs_path in _pools:
        _pools[abs_path].put(conn)
    else:
        conn.close()


@contextmanager
def connection(db_path: str, timeout: float = _TIMEOUT):
    """Context manager: borrow, yield, return (or close on exception)."""
    pool = _get_pool(db_path)
    conn = pool.get(timeout=timeout)
    try:
        yield conn
    except Exception:
        # On error, close rather than return (may be in bad state)
        try:
            conn.close()
        except Exception:
            pass
        with _registry_lock:
            if os.path.abspath(db_path) in _pools:
                with _pools[os.path.abspath(db_path)]._lock:
                    _pools[os.path.abspath(db_path)]._created = max(
                        0, _pools[os.path.abspath(db_path)]._created - 1
                    )
        raise
    else:
        pool.put(conn)


def pool_stats() -> Result:
    """Return stats for all active pools."""
    with _registry_lock:
        stats = [p.stats() for p in _pools.values()]
    return Result.success(stats)


def close_all():
    """Close all pools. Call on shutdown."""
    with _registry_lock:
        for pool in _pools.values():
            pool.close_all()
        _pools.clear()
    log.info("All DB pools closed")


if __name__ == "__main__":
    import tempfile, os

    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        test_db = f.name

    try:
        with connection(test_db) as conn:
            conn.execute("CREATE TABLE test (id INTEGER PRIMARY KEY, val TEXT)")
            conn.execute("INSERT INTO test VALUES (1, 'hello')")
            conn.commit()
            rows = conn.execute("SELECT * FROM test").fetchall()
            print(f"Rows: {[dict(r) for r in rows]}")

        # Stats
        r = pool_stats()
        print(f"Pool stats: {r.value}")

        # Concurrent access test
        import threading, time

        errors = []
        def worker(n):
            try:
                with connection(test_db) as c:
                    c.execute("INSERT INTO test VALUES (?, ?)", (n, f"worker-{n}"))
                    c.commit()
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=worker, args=(i+2,)) for i in range(10)]
        for t in threads: t.start()
        for t in threads: t.join()
        print(f"Concurrent writes: errors={len(errors)}")

        with connection(test_db) as conn:
            count = conn.execute("SELECT COUNT(*) FROM test").fetchone()[0]
            print(f"Total rows after concurrent writes: {count}")

    finally:
        close_all()
        os.unlink(test_db)
        print("Done.")
