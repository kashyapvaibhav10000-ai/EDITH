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

                    self.ram_cache[key] = {"value": value, "timestamp": timestamp}

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

    def recall(self, query, n=3):
        """
        Smart recall with recency decay scoring.
        Check RAM first (fast), then SQLite (comprehensive).
        Results are ranked by: keyword_match * recency_score.
        Returns top n matches.
        """
        import re
        # Sanitize query for SQLite FTS5 (strip special syntax characters)
        safe_query = re.sub(r'[:\"^\*\|\(\)\[\]]', ' ', query)
        
        scored_results = []  # (score, value) tuples

        try:
            # Phase 1: Check RAM cache first (instant for recent memories)
            for key, data in list(self.ram_cache.items())[::-1]:  # Most recent first
                if query.lower() in str(data["value"]).lower() or query.lower() in key.lower():
                    score = self._recency_score(data["timestamp"])
                    scored_results.append((score, data["value"]))

            # Phase 2: Search SQLite with FTS if not enough results found in RAM
            if len(scored_results) < n * 2:  # Fetch extra candidates for re-ranking
                cursor = self.sql_db.cursor()

                # FTS query for full-text search
                cursor.execute("""
                    SELECT value, timestamp FROM memories
                    WHERE id IN (
                        SELECT rowid FROM memories_fts
                        WHERE memories_fts MATCH ?
                        LIMIT ?
                    )
                    ORDER BY timestamp DESC
                """, (safe_query, (n * 2) - len(scored_results)))

                for row in cursor.fetchall():
                    value = row[0]
                    ts = row[1] if len(row) > 1 else time.time()
                    try:
                        parsed = json.loads(value)
                    except (json.JSONDecodeError, TypeError):
                        parsed = value
                    score = self._recency_score(ts)
                    scored_results.append((score, parsed))

                # If FTS didn't find enough, try LIKE search (fallback)
                if len(scored_results) < n:
                    cursor.execute("""
                        SELECT value, timestamp FROM memories
                        WHERE value LIKE ? OR key LIKE ?
                        ORDER BY timestamp DESC
                        LIMIT ?
                    """, (f"%{query}%", f"%{query}%", n - len(scored_results)))

                    for row in cursor.fetchall():
                        value = row[0]
                        ts = row[1] if len(row) > 1 else time.time()
                        try:
                            parsed = json.loads(value)
                        except (json.JSONDecodeError, TypeError):
                            parsed = value
                        score = self._recency_score(ts)
                        scored_results.append((score, parsed))

        except Exception as e:
            log.error(f"Error recalling query '{query}': {e}")

        # Sort by recency-weighted score (highest first) and return top n
        scored_results.sort(key=lambda x: x[0], reverse=True)
        return [val for _, val in scored_results[:n]]

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
