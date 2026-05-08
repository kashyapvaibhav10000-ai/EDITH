# db_pool.py
## Purpose
Thread-safe SQLite connection pool with WAL mode — one pool per DB path.
## Key Functions
- `get(db_path, timeout)` — acquire connection from pool (blocks if full)
- `put(db_path, conn)` — return connection to pool
- `connection(db_path, timeout)` — context manager wrapper for get/put
- `pool_stats()` — return pool sizes and checked-out counts
- `close_all()` — drain and close all connections (shutdown)
- `_ConnectionPool` class — queue-backed pool with configurable size
## Imports From
config, errors
## Imported By
session, smart_memory, trace_logger
## Status
OK
## Notes
WAL mode enabled on first connection open. Prevents SQLite SQLITE_BUSY under concurrent access.
