# graph_memory.py
## Purpose
Knowledge graph (GraphRAG) using NetworkX — entity-relationship extraction from conversations.
## Key Functions
- `extract_triples(text)` — LLM-extract (subject, relation, object) triples from text
- `add_triples(triples)` — add edges to graph, save to edith_graph.json
- `ingest_text(text)` — extract + store triples in one call
- `extract_and_store_triples(text)` — alias with count return
- `query_graph(topic, depth)` — BFS from topic node, return subgraph summary
- `graph_stats()` — node/edge counts
- `_load_graph()` / `_save_graph(G)` — persist NetworkX DiGraph to JSON
## Imports From
config, smart_router
## Imported By
session (end_session ingests conversation)
## Status
OK
## Notes
Graph stored at MEMORY_DB_PATH/edith_graph.json. Grows unbounded — no pruning yet.
