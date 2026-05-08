# telegram_bot.py
## Purpose
Telegram bot — full EDITH terminal over Telegram with weekly briefings and drift alerts.
## Key Functions
- `poll_telegram()` — long-poll loop, dispatch messages to process_message()
- `process_message(text)` — full intent routing pipeline for Telegram input
- `send_telegram(message, parse_mode)` — send message via Bot API
- `send_telegram_placeholder(text)` — send "thinking..." message, return message_id
- `edit_telegram_message(message_id, text, parse_mode)` — update placeholder in place
- `send_weekly_briefing()` — push life_os weekly briefing to Telegram
- `send_drift_alert()` — push cognitive drift warning
- `start_briefing_scheduler()` — schedule Monday briefings
- `_handle_mcpstatus_cmd()` / `_handle_mcp_cmd(args)` — /mcp admin commands
## Imports From
vault, config, session, cognitive_profile, event_bus
## Imported By
background_daemon (starts poll loop)
## Status
OK
## Notes
Bot token from vault. Placeholder + edit pattern avoids sending multiple messages during streaming.
