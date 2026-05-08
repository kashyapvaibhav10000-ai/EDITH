# rag.py
## Purpose
LlamaIndex RAG over notes directory — semantic search and Q&A on personal documents.
## Key Functions
- `build_index()` — load NOTES_DIR documents, build VectorStoreIndex with Ollama embeddings
- `index_directory(path)` — index arbitrary directory path
- `query_rag(question, index)` — query index, return Result with answer
## Imports From
config, errors
## Imported By
orchestrator, intent_dispatch
## Status
OK
## Notes
Uses OllamaEmbedding (nomic-embed-text) + Ollama LLM. Index rebuilt on demand — no persistence between restarts.
