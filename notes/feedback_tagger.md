# feedback_tagger.py
## Purpose
Links 👍👎 feedback to trace entries — feeds routing/model tuner.
## Key Functions
- `tag_feedback(trace_id, feedback_type, reason)` — write feedback to trace_logger
- `detect_implicit_feedback(trace_id, follow_up)` — infer positive/negative from follow-up text
- `get_feedback_context(trace_id)` — return full trace context for a feedback event
## Imports From
config, trace_logger
## Imported By
chat_server (feedback endpoint), telegram_bot
## Status
OK
## Notes
Phase 7.2. Implicit feedback detection uses keyword matching on follow-up queries.
