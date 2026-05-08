# edith_arch_updater.py
## Purpose
Boot script that AST-scans codebase and pushes architecture diagram to Joplin note.
## Key Functions
- `scan_codebase(edith_dir)` — AST walk all .py files, extract imports/functions/classes
- `build_scan_text(scan)` — format scan dict into Groq-friendly text
- `push_to_joplin(content, notebook_id)` — upsert note via Joplin REST API
- `get_or_create_notebook(name)` — find/create Joplin notebook
- `wait_for_joplin(max_wait)` — poll until Joplin REST API responds
- `internet_ok(host, port, timeout)` — TCP check before cloud calls
- `FileScanner` class — configurable file walker
## Imports From
none (standalone — reads .env directly)
## Imported By
edith_arch_boot.sh (systemd service)
## Status
OK
## Notes
Runs as separate systemd service `edith-arch-updater.service`. Standalone — no shared imports.
