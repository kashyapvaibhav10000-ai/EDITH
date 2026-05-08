# cleanup.py
## Purpose
ChromaDB memory cleanup — prunes stale/duplicate embeddings from memory collection.
## Key Functions
- `cleanup()` — main prune routine, removes old/low-score embeddings
- `_get_memory_collection()` — get ChromaDB edith_memory collection
## Imports From
config
## Imported By
background_daemon (nightly maintenance)
## Status
OK
## Notes
Run nightly during `_run_nightly_maintenance()`.
