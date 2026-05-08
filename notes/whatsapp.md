# whatsapp.py

## Purpose
WhatsApp bridge via HTTP API to external whatsapp-web.js bridge on localhost

## Key Functions
- `is_available()` — checks `BRIDGE_URL/status` reachable and `ready==True`
- `send_message(contact, message)` — POST to `BRIDGE_URL/send`; returns success/error string
- `get_unread()` — GET `BRIDGE_URL/unread`; formats unread message list
- `draft_message(contact, message)` — dry-run, returns formatted draft string without sending

## Imports From
- `config.get_logger`
- `requests` (lazy, inside functions)
- `os` (reads `WHATSAPP_BRIDGE_URL` env var)

## Imported By
- `intent_dispatch.py` (lazy imports: `is_available`, `get_unread`, `draft_message`, `send_message`, `BRIDGE_URL`)
- `orchestrator.py` (`wa_send`, `wa_unread` aliases)
- `test_harness.py` (`send_message`, `is_available`, `BRIDGE_URL`, `_bridge_active`)

## Status
WARN — Fragile. Depends on persistent Chromium session staying alive.

## Notes
Session dies on browser crash or system reboot. No auto-reconnect. Full integration pending.
Bridge URL set via `WHATSAPP_BRIDGE_URL` in `.env`. If unset, all functions return stub responses.
Module is Phase 5.1 stub — bridge (whatsapp-web.js) must run separately in `~/whatsapp-bot/`.
