# edith_scanner.py
## Purpose
Standalone flow scanner — AST-scans all .py files and generates HTML visualization.
## Key Functions
- `scan(edith_dir)` — walk .py files, extract metadata into module dicts
- `build_html(modules, scanned_at, edith_dir)` — generate edith_flow.html
- `extract_docstring(path)` / `extract_first_comment(path)` — module description extraction
- `extract_imports(path, all_stems)` — local import graph edges
- `extract_functions(path)` — list function names
- `count_lines(path)` — LOC count
## Imports From
none (standalone)
## Imported By
none (run directly: `python edith_scanner.py`)
## Status
OK
## Notes
Outputs `edith_flow.html`. Run anytime to refresh the architecture map.
