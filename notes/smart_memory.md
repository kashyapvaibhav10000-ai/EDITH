# smart_memory.py
## Purpose
Hot RAM + cold SQLite memory — constant ~100MB RAM with infinite cold storage.
## Key Functions
- `SmartMemoryManager` class:
  - `remember(key, value, category)` — write to RAM + archive to SQLite
  - `recall(query, n)` — RAM search first, SQLite FTS fallback
  - `forget(key)` — remove from RAM and SQLite
  - `get_stats()` — RAM size, archive count, compression ratio
- `compress_context(chunks, similarity_threshold)` — deduplicate similar memory chunks
## Imports From
db_pool, config
## Imported By
cognitive_profile
## Status
OK
## Notes
RAM capped at SMART_MEMORY_MAX_RAM_ITEMS (50) and SMART_MEMORY_MAX_RAM_MB (100). LRU eviction to SQLite.
