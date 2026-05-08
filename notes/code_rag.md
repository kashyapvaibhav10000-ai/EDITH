# code_rag.py
## Purpose
Code-aware RAG — indexes Python/JS codebase into ChromaDB for semantic code search.
## Key Functions
- `index_codebase()` — walk CODE_DIRS, chunk files, embed into ChromaDB
- `extract_python_chunks(filepath)` — AST-based function/class extraction
- `extract_js_chunks(filepath)` — JS file chunking
- `query_code(question, n)` — retrieve top-n relevant code chunks
- `ask_code(question)` — query + LLM synthesis answer
- `_get_codebase_collection()` — get ChromaDB codebase collection
## Imports From
config
## Imported By
orchestrator (coding intents), intent_dispatch
## Status
OK
## Notes
Skips dirs listed in SKIPPED_DIRS. Supports Python + JS extensions.
