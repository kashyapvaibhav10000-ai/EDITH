# episodic_memory.py
## Purpose
Stores full session conversations as episodes in ChromaDB for contextual recall.
## Key Functions
- `save_episode(session_id, queries, summary)` — embed and store session episode
- `recall_episodes(query, n)` — semantic search over past episodes
- `get_recent_episodes(n)` — fetch n most recent episodes by timestamp
- `get_episode_count()` — total episode count in collection
- `_get_episodic_collection()` — ChromaDB episodic_memory collection handle
## Imports From
config
## Imported By
session (end_session writes episode)
## Status
OK
## Notes
Each episode stores full turn list + LLM-generated summary. Enables "what did we discuss last Tuesday" recall.
