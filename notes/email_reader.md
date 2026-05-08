# email_reader.py
## Purpose
IMAP email reader with AI summarization — inbox check via imapclient.
## Key Functions
- `check_inbox(limit, unread_only)` — fetch + summarize emails, return Result
- `fetch_emails(folder, limit, unread_only)` — raw IMAP fetch with decoded headers/body
- `summarize_emails(emails)` — LLM summary of fetched email list
- `connect()` — authenticated IMAP connection using vault credentials
- `decode_str(s)` / `get_body(msg)` — email header/body decode helpers
## Imports From
vault, config, errors
## Imported By
orchestrator, intent_dispatch, background_daemon (prefetch)
## Status
OK
## Notes
Email credentials loaded from vault. Supports INBOX and custom folders.
