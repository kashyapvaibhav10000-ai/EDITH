# devlog.py
## Purpose
Developer changelog — logs changes/reasons/status, syncs to Simplenote and Telegram.
## Key Functions
- `add_entry(change, reason, status, error, next_plan)` — append timestamped entry to DEVLOG_PATH
- `parse_log_command(text)` — parse natural language devlog command
- `_generate_status_report()` — LLM-generated summary of recent entries
- `_send_telegram_report(report)` — push report to Telegram
- `_sync_to_simplenote()` — upload devlog to Simplenote note
- `start_devlog()` — start background sync thread
## Imports From
vault, config
## Imported By
background_daemon (nightly report), intent_dispatch
## Status
OK
## Notes
Sync interval configurable. Simplenote creds from vault.
