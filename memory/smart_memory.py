"""
Smart Memory Architecture - Hot RAM + Cold Disk Storage
Keeps recent memories in RAM for speed, archives old ones to SQLite.
RAM usage stays constant (~100MB) while remembering everything forever.

Phase 2 additions:
  - Thread-safe writes with threading.Lock
  - Recency decay scoring: old memories rank lower
  - Context compression: deduplicate overlapping RAG chunks
"""

import sqlite3
import time
import math
import json
import db_pool
import threading
from collections import OrderedDict
from difflib import SequenceMatcher
from config import (
    get_logger,
    MEMORY_ARCHIVE_PATH,
    SMART_COMPRESSION,
    SMART_MEMORY_MAX_RAM_ITEMS,
    SMART_MEMORY_MAX_RAM_MB,
    RECENCY_DECAY_HALFLIFE_DAYS,
)

log = get_logger("smart_memory")


class SmartMemoryManager:
    """Hybrid memory: RAM cache (hot) + SQLite archive (cold)"""

    def __init__(self, db_path, max_ram_items=50, max_ram_mb=100):
        self.db_path = db_path
        self.max_ram_items = max_ram_items
        self.max_ram_mb = max_ram_mb
        self.ram_cache = OrderedDict()  # LRU: oldest items first
        self._write_lock = threading.Lock()  # Phase 2: thread-safe writes
        self.sql_db = db_pool.get(db_path)
        self._init_db()
        log.info(f"SmartMemoryManager initialized. DB: {db_path}, Max RAM items: {max_ram_items}")

    def _init_db(self):
        """Create SQLite tables with FTS for fast searching"""
        cursor = self.sql_db.cursor()

        # Main memories table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS memories (
                id INTEGER PRIMARY KEY,
                key TEXT UNIQUE NOT NULL,
                value TEXT NOT NULL,
                category TEXT DEFAULT 'general',
                timestamp REAL NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # Full-text search table
        cursor.execute("""
            CREATE VIRTUAL TABLE IF NOT EXISTS memories_fts USING fts5(
                key, value, content=memories, content_rowid=id
            )
        """)

        # Indexes for fast queries
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_category ON memories(category)
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_timestamp ON memories(timestamp DESC)
        """)

        # Retrieval frequency column — additive migration, safe on existing DBs
        try:
            cursor.execute("ALTER TABLE memories ADD COLUMN retrieval_count INTEGER DEFAULT 0")
            log.info("Added retrieval_count column to memories table")
        except Exception:
            pass  # Column already exists

        self.sql_db.commit()
        log.info("SmartMemoryManager database initialized")

    def remember(self, key, value, category="general"):
        """
        Store memory in both cold (SQLite) and hot (RAM) storage.
        Auto-evicts oldest from RAM if over limit.
        Thread-safe with retry on write collision.
        """
        max_retries = 3
        for attempt in range(max_retries):
            try:
                with self._write_lock:
                    timestamp = time.time()

                    # Always write to SQLite first (cold storage)
                    cursor = self.sql_db.cursor()
                    cursor.execute("""
                        INSERT OR REPLACE INTO memories (key, value, category, timestamp)
                        VALUES (?, ?, ?, ?)
                    """, (key, json.dumps(value) if not isinstance(value, str) else value, category, timestamp))

                    # Also update FTS index
                    cursor.execute("""
                        INSERT OR REPLACE INTO memories_fts (rowid, key, value)
                        VALUES ((SELECT id FROM memories WHERE key = ?), ?, ?)
                    """, (key, key, value if isinstance(value, str) else json.dumps(value)))

                    self.sql_db.commit()

                    # Update RAM cache
                    if key in self.ram_cache:
                        del self.ram_cache[key]  # Move to end (most recent)

                    self.ram_cache[key] = {"value": value, "timestamp": timestamp, "retrieval_count": 0}

                    # Evict LRU if RAM cache too large
                    while len(self.ram_cache) > self.max_ram_items:
                        oldest_key = next(iter(self.ram_cache))
                        del self.ram_cache[oldest_key]
                        log.debug(f"Evicted oldest from RAM cache: {oldest_key}")

                return  # Success

            except sqlite3.OperationalError as e:
                if "locked" in str(e) and attempt < max_retries - 1:
                    wait = (2 ** attempt) * 0.1  # 0.1s, 0.2s, 0.4s
                    log.warning(f"DB locked, retrying in {wait}s (attempt {attempt+1})")
                    time.sleep(wait)
                else:
                    log.error(f"Error remembering {key} after {attempt+1} attempts: {e}")
            except Exception as e:
                log.error(f"Error remembering {key}: {e}")
                break

    @staticmethod
    def _recency_score(timestamp: float) -> float:
        """Compute recency decay score. Recent = 1.0, decays with age.

        Uses exponential decay with configurable half-life.
        """
        age_days = (time.time() - timestamp) / 86400
        halflife = RECENCY_DECAY_HALFLIFE_DAYS
        return math.exp(-0.693 * age_days / halflife)  # ln(2) ≈ 0.693

    @staticmethod
    def _combined_score(timestamp: float, retrieval_count: int) -> float:
        """Score = recency_decay * (1 + log(retrieval_count + 1)).

        Frequently recalled memories stay near the top regardless of age.
        A memory recalled 10 times scores ~3.4x higher than one recalled once.
        """
        recency = SmartMemoryManager._recency_score(timestamp)
        frequency_boost = 1.0 + math.log1p(retrieval_count)  # log1p(0)=0, log1p(9)≈2.3
        return recency * frequency_boost

    def recall(self, query, n=5):
        """
        Smart recall with combined recency + retrieval-frequency scoring.
        Check RAM first (fast), then SQLite (comprehensive).
        Results ranked by: recency_decay * log(retrieval_count + 1).
        Increments retrieval_count for every memory returned (frequency learning).
        Returns top n matches.
        """
        import re
        # Sanitize query for SQLite FTS5 (strip special syntax characters)
        safe_query = re.sub(r'[:\"^\*\|\(\)\[\]]', ' ', query)

        scored_results = []   # (score, value, key) tuples — key used to bump retrieval_count
        seen_keys = set()

        try:
            # Phase 1: Check RAM cache first (instant for recent memories)
            for key, data in list(self.ram_cache.items())[::-1]:  # Most recent first
                if key in seen_keys:
                    continue
                if query.lower() in str(data["value"]).lower() or query.lower() in key.lower():
                    rc = data.get("retrieval_count", 0)
                    score = self._combined_score(data["timestamp"], rc)
                    scored_results.append((score, data["value"], key))
                    seen_keys.add(key)

            # Phase 2: Search SQLite with FTS if not enough results found in RAM
            if len(scored_results) < n * 2:
                cursor = self.sql_db.cursor()

                # FTS query — include retrieval_count in SELECT
                cursor.execute("""
                    SELECT m.key, m.value, m.timestamp, COALESCE(m.retrieval_count, 0)
                    FROM memories m
                    WHERE m.id IN (
                        SELECT rowid FROM memories_fts
                        WHERE memories_fts MATCH ?
                        LIMIT ?
                    )
                    ORDER BY m.timestamp DESC
                """, (safe_query, (n * 2) - len(scored_results)))

                for row in cursor.fetchall():
                    k, value, ts, rc = row[0], row[1], row[2] or time.time(), row[3] or 0
                    if k in seen_keys:
                        continue
                    try:
                        parsed = json.loads(value)
                    except (json.JSONDecodeError, TypeError):
                        parsed = value
                    score = self._combined_score(ts, rc)
                    scored_results.append((score, parsed, k))
                    seen_keys.add(k)

                # LIKE fallback if FTS didn't return enough
                if len(scored_results) < n:
                    cursor.execute("""
                        SELECT key, value, timestamp, COALESCE(retrieval_count, 0)
                        FROM memories
                        WHERE value LIKE ? OR key LIKE ?
                        ORDER BY timestamp DESC
                        LIMIT ?
                    """, (f"%{query}%", f"%{query}%", n - len(scored_results)))

                    for row in cursor.fetchall():
                        k, value, ts, rc = row[0], row[1], row[2] or time.time(), row[3] or 0
                        if k in seen_keys:
                            continue
                        try:
                            parsed = json.loads(value)
                        except (json.JSONDecodeError, TypeError):
                            parsed = value
                        score = self._combined_score(ts, rc)
                        scored_results.append((score, parsed, k))
                        seen_keys.add(k)

        except Exception as e:
            log.error(f"Error recalling query '{query}': {e}")

        # Sort by combined score and return top n
        scored_results.sort(key=lambda x: x[0], reverse=True)
        top = scored_results[:n]

        # ── Increment retrieval_count for returned memories (frequency learning) ──
        if top:
            returned_keys = [k for _, _, k in top]
            try:
                cursor = self.sql_db.cursor()
                cursor.executemany(
                    "UPDATE memories SET retrieval_count = COALESCE(retrieval_count, 0) + 1 WHERE key = ?",
                    [(k,) for k in returned_keys]
                )
                self.sql_db.commit()
                # Also update RAM cache if present
                for k in returned_keys:
                    if k in self.ram_cache:
                        self.ram_cache[k]["retrieval_count"] = self.ram_cache[k].get("retrieval_count", 0) + 1
            except Exception as _re:
                log.debug(f"retrieval_count update failed: {_re}")

        return [val for _, val, _ in top]

    def get_all(self, category=None, limit=100):
        """Get all memories, optionally filtered by category"""
        try:
            cursor = self.sql_db.cursor()
            if category:
                cursor.execute("""
                    SELECT key, value FROM memories
                    WHERE category = ?
                    ORDER BY timestamp DESC
                    LIMIT ?
                """, (category, limit))
            else:
                cursor.execute("""
                    SELECT key, value FROM memories
                    ORDER BY timestamp DESC
                    LIMIT ?
                """, (limit,))

            results = []
            for key, value in cursor.fetchall():
                try:
                    results.append({"key": key, "value": json.loads(value)})
                except (json.JSONDecodeError, TypeError):
                    results.append({"key": key, "value": value})

            return results
        except Exception as e:
            log.error(f"Error getting all memories: {e}")
            return []

    def delete(self, key):
        """Remove a specific memory"""
        try:
            cursor = self.sql_db.cursor()
            cursor.execute("DELETE FROM memories WHERE key = ?", (key,))
            self.sql_db.commit()

            if key in self.ram_cache:
                del self.ram_cache[key]

            log.info(f"Deleted memory: {key}")
        except Exception as e:
            log.error(f"Error deleting {key}: {e}")

    def cleanup_old(self, days=30):
        """Delete memories older than N days"""
        try:
            cutoff_time = time.time() - (days * 86400)
            cursor = self.sql_db.cursor()
            cursor.execute("DELETE FROM memories WHERE timestamp < ?", (cutoff_time,))
            deleted_count = cursor.rowcount
            self.sql_db.commit()
            log.info(f"Cleaned up {deleted_count} memories older than {days} days")
            return deleted_count
        except Exception as e:
            log.error(f"Error cleaning up old memories: {e}")
            return 0

    def get_stats(self):
        """Get memory statistics"""
        try:
            cursor = self.sql_db.cursor()
            cursor.execute("SELECT COUNT(*) FROM memories")
            total_count = cursor.fetchone()[0]
            cursor.execute("SELECT SUM(LENGTH(value)) / 1024.0 FROM memories")
            total_size_kb = cursor.fetchone()[0] or 0

            return {
                "total_memories": total_count,
                "ram_cache_size": len(self.ram_cache),
                "disk_size_kb": total_size_kb,
                "disk_size_mb": total_size_kb / 1024.0
            }
        except Exception as e:
            log.error(f"Error getting stats: {e}")
            return {}

    def close(self):
        """Return database connection to pool"""
        try:
            db_pool.put(self.db_path, self.sql_db)
            self.sql_db = None
            log.info("SmartMemoryManager closed")
        except Exception as e:
            log.error(f"Error closing database: {e}")


class SmartMemory(SmartMemoryManager):
    """Backward-compatible alias for older imports of SmartMemory."""

    def __init__(
        self,
        db_path=MEMORY_ARCHIVE_PATH,
        max_ram_items=SMART_MEMORY_MAX_RAM_ITEMS,
        max_ram_mb=SMART_MEMORY_MAX_RAM_MB,
    ):
        super().__init__(db_path, max_ram_items=max_ram_items, max_ram_mb=max_ram_mb)
        self._hot = self.ram_cache


# ──────────────────────────────────────────────
# Context Compressor (Phase 2.4)
# ──────────────────────────────────────────────
def compress_context(chunks: list, similarity_threshold: float = 0.7) -> list:
    """Deduplicate overlapping RAG chunks before sending to LLM.

    Compares every pair of chunks using SequenceMatcher.
    If similarity > threshold, keeps the longer/more recent one.
    Returns deduplicated list.
    """
    if not SMART_COMPRESSION or len(chunks) <= 1:
        return chunks

    # Convert to strings for comparison
    str_chunks = [str(c) for c in chunks]
    keep = [True] * len(str_chunks)

    for i in range(len(str_chunks)):
        if not keep[i]:
            continue
        for j in range(i + 1, len(str_chunks)):
            if not keep[j]:
                continue
            sim = SequenceMatcher(None, str_chunks[i], str_chunks[j]).ratio()
            if sim >= similarity_threshold:
                # Keep the longer one
                if len(str_chunks[i]) >= len(str_chunks[j]):
                    keep[j] = False
                    log.debug(f"Compressed duplicate chunk ({sim:.0%} similar)")
                else:
                    keep[i] = False
                    log.debug(f"Compressed duplicate chunk ({sim:.0%} similar)")
                    break

    result = [chunks[i] for i in range(len(chunks)) if keep[i]]
    if len(result) < len(chunks):
        log.info(f"Context compressed: {len(chunks)} → {len(result)} chunks")
    return result
