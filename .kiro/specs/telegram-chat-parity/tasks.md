# Implementation Plan: Telegram Chat Parity

## Overview

All changes land in `telegram_bot.py`. The core change replaces the direct `dispatch()` call in `process_message()` with `orchestrator.chat()`, then adds helper functions, new commands, photo support, and inline HITL keyboards. The orchestrator, intent_dispatch, and handlers/shell are unchanged.

## Tasks

- [x] 1. Add module-level state and new helper utilities
  - [x] 1.1 Add `_hitl_msg_id: int | None = None` module-level variable and implement `_edith_error(e, context_hint)` formatter
    - Add the module-level variable `_hitl_msg_id` to `telegram_bot.py`
    - Implement `_edith_error(e, context_hint="")` that returns an EDITH-voiced error string with the exception message capped at 120 chars, containing the word "Boss", and never containing "Traceback" or "File " stack frame markers
    - Log the exception at ERROR level inside the helper
    - _Requirements: 11.1, 11.4_
  - [ ]* 1.2 Write property test for `_edith_error` — Property 12: EDITH error messages never expose raw tracebacks
    - **Property 12: EDITH error messages never expose raw tracebacks**
    - **Validates: Requirements 11.1, 11.4**
    - For any Python exception of any type and any message string, assert output does not contain `"Traceback"` or `"File "` and does contain `"Boss"`
  - [x] 1.3 Implement `_send_typing(chat_id)` helper
    - POST to `sendChatAction` with `action="typing"`, timeout=5, swallow all exceptions with a `log.warning`
    - _Requirements: 4.1, 4.2_
  - [x] 1.4 Implement `_build_reply_context(msg, user_input)` helper
    - Extract `msg.get("reply_to_message", {}).get("text", "")`, truncate quoted text to 200 chars, prepend `[Replying to: "<quoted>"] ` to `user_input`; return `user_input` unmodified if no `reply_to_message`
    - _Requirements: 9.1, 9.2, 9.3_
  - [ ]* 1.5 Write property test for `_build_reply_context` — Property 11: Reply context prepend is correctly formatted and bounded
    - **Property 11: Reply context prepend is correctly formatted and bounded**
    - **Validates: Requirements 9.1**
    - For any `reply_to_message` text and `user_input`, assert output starts with `[Replying to: "`, quoted portion ≤ 200 chars, and ends with `"] <user_input>` intact

- [x] 2. Implement `/history`, `/clear`, and `/status` command handlers
  - [x] 2.1 Implement `_handle_history_cmd()`
    - Import `_source_history` from `orchestrator`; slice last 20 items (10 turn pairs); format each with `👤` / `🤖` prefix, truncate text to 150 chars with `…`; return "No conversation history yet, Boss." if fewer than 2 entries
    - Send result with `parse_mode=None`
    - _Requirements: 5.1, 5.2, 5.3, 5.4_
  - [ ]* 2.2 Write property test for `_handle_history_cmd` — Property 6: History command returns at most 10 turns
    - **Property 6: History command returns at most 10 turns**
    - **Validates: Requirements 5.1**
    - For any list of N messages in `_source_history["telegram"]`, assert formatted output contains at most min(N // 2, 10) turn pairs
  - [ ]* 2.3 Write property test for history formatting — Property 7: History formatting truncates to 150 characters per turn
    - **Property 7: History formatting truncates to 150 characters per turn**
    - **Validates: Requirements 5.2**
    - For any message string of any length, assert each formatted turn has the correct emoji prefix and the text portion is at most 151 chars (150 + `…`)
  - [x] 2.4 Implement `_handle_clear_cmd()`
    - Import `_source_history` and `TELEGRAM_JSONL` from `orchestrator`; call `_source_history["telegram"].clear()`; atomically overwrite `TELEGRAM_JSONL` with an empty file via `tempfile.NamedTemporaryFile` + `os.replace`; return success or EDITH-flavoured disk-error string
    - _Requirements: 6.1, 6.2, 6.3, 6.4, 13.5_
  - [ ]* 2.5 Write property test for `_handle_clear_cmd` — Property 8: /clear produces empty history
    - **Property 8: /clear produces empty history**
    - **Validates: Requirements 6.1, 13.5**
    - For any pre-populated `_source_history["telegram"]`, after `_handle_clear_cmd()` succeeds, assert the list is empty and the JSONL file contains no non-empty lines
  - [x] 2.6 Implement `_handle_status_cmd()`
    - Collect: `smart_router.router_status().get("active_provider", "unavailable")`, `len(_source_history["telegram"])`, `smart_memory.count()`, `datetime.now().strftime("%H:%M %Z")`; each sub-call individually wrapped in `try/except`; format as plain-text with emoji labels, total ≤ 300 chars
    - _Requirements: 7.1, 7.2, 7.3, 7.4_
  - [ ]* 2.7 Write property test for `_handle_status_cmd` — Property 9: /status response is at most 300 characters
    - **Property 9: /status response is at most 300 characters**
    - **Validates: Requirements 7.2**
    - For any combination of valid status field values (provider name, history length, memory count, time string), assert formatted response length ≤ 300

- [x] 3. Replace `dispatch()` with `orchestrator.chat()` in `process_message()`
  - [x] 3.1 Refactor `process_message(text)` to call `orchestrator.chat()`
    - Keep existing open-loop / close-loop shortcut guards at the top
    - After shortcuts, call `_build_reply_context(msg, text)` to build `augmented_text` (thread the `msg` dict into `process_message` if not already available, or accept it as an optional param)
    - Replace `dispatch(DispatchContext(...))` with `orchestrator.chat(augmented_text, intent=detected_intent, source="telegram", device="telegram")`
    - Return the result string
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 1.6, 1.7, 1.8, 9.1, 9.2, 9.3_
  - [ ]* 3.2 Write property test for Telegram routing — Property 1: Telegram routing updates isolated source history
    - **Property 1: Telegram routing updates isolated source history**
    - **Validates: Requirements 1.1, 1.2**
    - For any valid text message, mock `orchestrator.chat`; after call assert `_source_history["telegram"]` grows by exactly 2, and `_source_history["widget"]` and `_source_history["voice"]` are unchanged
  - [ ]* 3.3 Write property test for history persistence — Property 2: Telegram history persistence round trip
    - **Property 2: Telegram history persistence round trip**
    - **Validates: Requirements 1.8, 13.2**
    - For any message string processed through `orchestrator.chat(msg, source="telegram", device="telegram")`, assert `data/telegram_memory.jsonl` contains at least one line with that message text afterwards

- [x] 4. Checkpoint — core pipeline change verified
  - Ensure existing tests pass, the open-loop/close-loop shortcuts still short-circuit correctly, and basic `process_message()` calls reach `orchestrator.chat`. Ask the user if questions arise.

- [ ] 5. Update `poll_telegram()` and `handle_telegram_update()` — typing, commands, HITL detection
  - [x] 5.1 Add typing indicator + `/history`, `/clear`, `/status` dispatch to both poll and webhook paths
    - Call `_send_typing(chat_id)` immediately after auth/rate-limit guards pass and before the placeholder send
    - Add command branches: `text == "/history"` → `_handle_history_cmd()`, `text == "/clear"` → `_handle_clear_cmd()`, `text == "/status"` → `_handle_status_cmd()`; send result directly, skip orchestrator
    - _Requirements: 4.1, 4.2, 4.3, 5.4, 6.4, 7.4, 12.1, 12.2_
  - [-] 5.2 Add `callback_query` branch to `poll_telegram()` and `handle_telegram_update()`
    - At the top of each update loop, check `if "callback_query" in update:` → call `_handle_callback_query(update["callback_query"])` and `continue`
    - _Requirements: 10.4, 10.5, 12.9_
  - [-] 5.3 Add HITL keyboard detection after `process_message()` returns
    - After getting `response` from `process_message()`/`orchestrator.chat()`, call `get_pending_action()`; if truthy call `_send_hitl_keyboard(msg_id, response)` and store `_hitl_msg_id = msg_id`; else edit placeholder with response
    - Wrap the full processing block in `try/except` using `_edith_error` for user-facing errors
    - _Requirements: 10.1, 10.4, 11.1, 11.2, 11.3, 11.4, 12.8_

- [ ] 6. Implement inline HITL keyboard helpers
  - [ ] 6.1 Implement `_answer_callback(cq_id, text="")` helper
    - POST to `answerCallbackQuery`, timeout=5, swallow exceptions with `log.warning`
    - _Requirements: 10.1, 10.5_
  - [ ] 6.2 Implement `_send_hitl_keyboard(msg_id, prompt_text)`
    - Build `inline_keyboard` with `[{"text": "✅ Yes, run it", "callback_data": "hitl_confirm"}, {"text": "❌ Cancel", "callback_data": "hitl_cancel"}]`
    - Call `editMessageText` with `chat_id`, `message_id`, `text=prompt_text`, and `reply_markup`
    - Swallow exceptions with `log.warning`
    - _Requirements: 10.1, 10.4_
  - [ ] 6.3 Implement `_handle_callback_query(cq)`
    - Extract `cq_id`, `data`, `msg_id` from `cq`; call `_answer_callback(cq_id, "")` immediately
    - If `get_pending_action()` is None: log warning and return
    - If `data == "hitl_confirm"`: call `execute_pending_action(pending)` in try/except, edit message with result, `reply_markup={}`, call `clear_pending_action()`
    - If `data == "hitl_cancel"`: call `clear_pending_action()`, edit message with "Cancelled, Boss.", `reply_markup={}`
    - _Requirements: 10.2, 10.3, 10.5, 10.6_

- [ ] 7. Implement photo / vision support
  - [ ] 7.1 Implement `_handle_photo(msg, chat_id)` function
    - Select highest-res photo via `msg["photo"][-1]`; call `getFile` to resolve `file_path`; download image bytes; write to temp file; build `DispatchContext(user_input=f"{caption} [image: {local_path}]", intent="vision", source="telegram", device="telegram")`; call `_handle_vision(ctx)`; clean up temp file in `finally`
    - Return EDITH-voiced error strings for download failure or vision unavailability
    - _Requirements: 8.1, 8.2, 8.3, 8.4, 8.5_
  - [ ]* 7.2 Write property test for photo resolution selection — Property 10: Photo resolution selection picks highest-resolution photo
    - **Property 10: Photo resolution selection picks the highest-resolution photo**
    - **Validates: Requirements 8.1**
    - For any list of 1+ `PhotoSize` dicts with distinct `width*height` values, assert the selected `file_id` belongs to the object with the largest `width*height`
  - [ ] 7.3 Add photo message branch to `poll_telegram()` and `handle_telegram_update()`
    - After existing text-message handling, add `elif "photo" in msg:` → `_send_typing(chat_id)`, send placeholder, call `_handle_photo(msg, chat_id)`, edit placeholder with result
    - Apply same rate-limit check as text messages
    - _Requirements: 8.1, 8.3, 8.6, 12.7_

- [ ] 8. Verify conversation DNA properties (property-based tests only — DNA code unchanged)
  - [ ]* 8.1 Write property test for DNA telegram max_length — Property 3: Conversation DNA enforces telegram max_length
    - **Property 3: Conversation DNA enforces telegram max_length**
    - **Validates: Requirements 1.4**
    - For any context dict with `device="telegram"`, assert `get_response_modifiers(ctx)["max_length"] <= 300`
  - [ ]* 8.2 Write property test for HIGH urgency DNA cap — Property 4: HIGH urgency caps DNA max_length to 250
    - **Property 4: HIGH urgency caps DNA max_length to 250**
    - **Validates: Requirements 2.2**
    - For any context dict with `urgency="HIGH"`, assert `get_response_modifiers(ctx)["max_length"] <= 250`
  - [ ]* 8.3 Write property test for frustrated emotion DNA tone — Property 5: Frustrated emotion sets DNA tone to empathetic
    - **Property 5: Frustrated emotion sets DNA tone to empathetic**
    - **Validates: Requirements 2.4**
    - For any context dict with `emotion="frustrated"`, assert `get_response_modifiers(ctx)["tone"] == "empathetic"`

- [ ] 9. Verify orchestrator history management properties (property-based tests only — orchestrator code unchanged)
  - [ ]* 9.1 Write property test for history load cap — Property 13: Telegram history load respects 20-turn cap
    - **Property 13: Telegram history load respects 20-turn cap**
    - **Validates: Requirements 13.1**
    - For any JSONL file containing N lines of valid JSON, assert `_load_telegram_history()` returns a list of at most 20 entries
  - [ ]* 9.2 Write property test for JSONL rotation — Property 14: JSONL rotation keeps file at most 500 lines
    - **Property 14: JSONL rotation keeps file at most 500 lines**
    - **Validates: Requirements 13.3**
    - For a JSONL file with exactly 500 lines, after `_append_telegram_jsonl(msg)`, assert the file has at most 500 lines (rotation should drop oldest 100 before appending)

- [ ] 10. Final checkpoint — end-to-end wiring complete
  - Ensure all non-optional tests pass; smoke-test the full message path (text → `orchestrator.chat()` → placeholder edit) with mocks; confirm all existing commands (`/mcpstatus`, `/mcp`, open-loop, close-loop) still work; ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional and can be skipped for a faster MVP
- All changes are confined to `telegram_bot.py` — no other files are modified
- Property tests should use `hypothesis` (already used elsewhere in the project) and run a minimum of 100 iterations each
- Checkpoints in tasks 4 and 10 are not leaf tasks and are not included in the dependency graph
- Each property test task is annotated with its property number and the requirement it validates
- Optional test sub-tasks will NOT be auto-implemented by the coding agent; they must be explicitly selected

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1", "1.3", "1.4"] },
    { "id": 1, "tasks": ["1.2", "1.5", "2.1", "2.4", "2.6"] },
    { "id": 2, "tasks": ["2.2", "2.3", "2.5", "2.7", "3.1", "6.1"] },
    { "id": 3, "tasks": ["3.2", "3.3", "5.1", "6.2", "7.1", "8.1", "8.2", "8.3"] },
    { "id": 4, "tasks": ["5.2", "5.3", "7.2", "9.1", "9.2"] },
    { "id": 5, "tasks": ["6.3", "7.3"] }
  ]
}
```
