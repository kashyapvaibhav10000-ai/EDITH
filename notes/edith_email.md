# edith_email.py
## Purpose
Gmail compose/send via OAuth — AI-assisted email drafting with user confirmation.
## Key Functions
- `compose_email()` — interactive compose flow with AI draft + HITL confirm
- `draft_email_with_ai(instruction)` — LLM generates subject + body from natural language
- `send_email(service, to, subject, body)` — send via Gmail API
- `get_gmail_service()` — build authenticated Gmail API client
## Imports From
config
## Imported By
orchestrator, intent_dispatch
## Status
OK
## Notes
Uses TOKEN_PICKLE_FILE for OAuth token. Requires gmail send scope.
