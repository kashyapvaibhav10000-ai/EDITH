# Requirements Document

## Introduction

EDITH's Telegram bot currently routes messages through `intent_dispatch.dispatch()` directly, bypassing the full orchestrator pipeline. This means Telegram responses lack memory recall context, Conversation DNA style modifiers, emotion/urgency detection, post-turn reflection, skill injection, the EDITH persona system prompt, and compound intent (DAG) support — all of which are active in the web chat UI.

This feature closes that gap. After implementation, every Telegram message Vaibhav sends will flow through the same `orchestrator.chat()` pipeline as the web chat, giving him full EDITH intelligence from his phone. Additionally, several Telegram-native enhancements are added: typing indicators, new utility commands (`/history`, `/clear`, `/status`), photo/vision support, reply-threading context, inline HITL confirmation buttons, and EDITH-flavoured error messages.

---

## Glossary

- **Telegram_Bot**: The `telegram_bot.py` module that polls for or receives Telegram updates and sends replies.
- **Orchestrator**: The `orchestrator.py` module containing `chat()` and `chat_stream()`, which implement the full EDITH pipeline.
- **Pipeline**: The sequence of steps inside `orchestrator.chat()`: danger scan → memory recall → DNA modifiers → system prompt assembly → LLM call → post-turn reflection → history persistence.
- **Dispatcher**: `intent_dispatch.dispatch()` — the thin intent-to-handler router. Currently the sole path for Telegram messages; must remain available for intent-specific handlers called from within the Pipeline.
- **Conversation_DNA**: `conversation_dna.get_response_modifiers()` — produces tone, depth, and `max_length` (300 chars for device="telegram") from contextual signals.
- **Memory_Recall**: The four-tier recall in `orchestrator.chat()`: SmartMemory (hot RAM + SQLite) → ChromaDB vectors → graph triples → episodic episodes.
- **Post_Turn_Reflection**: The `_post_turn_reflection()` fire-and-forget thread that extracts facts, resolves contradictions, updates `memory.md`, and stores knowledge-graph triples after each turn.
- **Skill_Injection**: `skills_loader.get_skill_for_intent()` — appends matching SKILL.md content to the system prompt.
- **EDITH_Persona**: The full system prompt assembled inside `orchestrator.chat()`, including persona text, user profile (`user.md`), dynamic memory (`memory.md`), project state, channel persona suffix, and DNA style instruction.
- **Compound_Intent**: A user message containing two or more sequential tasks (e.g. "search for X then email it to me"), detected by `compound_dag.detect_compound()` and executed as a DAG.
- **HITL**: Human-In-The-Loop — a confirmation step before executing a destructive or irreversible shell command.
- **Placeholder_Edit_Pattern**: The UX pattern where a "⏳ On it, Boss…" message is sent immediately, then edited in-place when the response is ready.
- **Telegram_History**: `_source_history["telegram"]` in `orchestrator.py`, persisted to `data/telegram_memory.jsonl`.
- **Rate_Limiter**: The per-`chat_id` token bucket: 10 messages per 60-second window in `_tg_is_rate_limited()`.
- **Vision_Handler**: The `_handle_vision` intent handler capable of analyzing photos via `analyze_photo()`.
- **Owner**: Vaibhav — the sole authorised user, identified by `TELEGRAM_CHAT_ID`.

---

## Requirements

### Requirement 1: Full Orchestrator Pipeline for All Text Messages

**User Story:** As Vaibhav, I want every text message I send to EDITH via Telegram to go through the full `orchestrator.chat()` pipeline, so that Telegram responses have the same intelligence, memory, and personality as the web chat.

#### Acceptance Criteria

1. WHEN Telegram_Bot receives a text message from the Owner, THE Telegram_Bot SHALL route the message to `orchestrator.chat(user_input, intent=detected_intent, device="telegram", source="telegram")` instead of calling `intent_dispatch.dispatch()` directly.
2. WHEN `orchestrator.chat()` is called with `source="telegram"`, THE Orchestrator SHALL use `_source_history["telegram"]` as the active conversation history, leaving the widget and voice histories untouched.
3. WHEN `orchestrator.chat()` processes a Telegram message, THE Orchestrator SHALL inject all four tiers of Memory_Recall (SmartMemory, ChromaDB, graph triples, episodic episodes) into the system prompt context.
4. WHEN `orchestrator.chat()` processes a Telegram message, THE Orchestrator SHALL call `conversation_dna.get_response_modifiers()` with `device="telegram"`, enforcing a `max_length` of 300 characters on the Conversation_DNA output.
5. WHEN `orchestrator.chat()` processes a Telegram message, THE Orchestrator SHALL apply the EDITH_Persona system prompt, including the `CHANNEL_PERSONAS["telegram"]` suffix that instructs concise, plain-text replies.
6. WHEN `orchestrator.chat()` finishes processing a Telegram message, THE Orchestrator SHALL execute Post_Turn_Reflection asynchronously (fire-and-forget thread), saving facts to long-term memory and updating knowledge-graph triples.
7. WHEN `orchestrator.chat()` processes a Telegram message, THE Orchestrator SHALL perform Skill_Injection by calling `skills_loader.get_skill_for_intent(intent)` and appending any matching skill content to the system prompt.
8. WHEN a Telegram message is processed, THE Orchestrator SHALL append the user and assistant turns to `_source_history["telegram"]` and persist them to `data/telegram_memory.jsonl` for cross-restart continuity.

---

### Requirement 2: Emotion and Urgency Detection

**User Story:** As Vaibhav, I want EDITH to detect my emotional state and urgency from Telegram messages, so that her tone adjusts appropriately (calm when I'm stressed, immediate when I'm urgent).

#### Acceptance Criteria

1. WHEN Telegram_Bot routes a message to the Orchestrator, THE Orchestrator SHALL call `ml_router.detect_emotion_urgency(user_input)` before constructing the system prompt.
2. WHEN `detect_emotion_urgency()` returns `urgency="HIGH"`, THE Conversation_DNA SHALL cap `max_length` to 250 characters and instruct the LLM to answer immediately without preamble.
3. WHEN `detect_emotion_urgency()` returns `emotion="stressed"`, THE Conversation_DNA SHALL set tone to "calm" and cap `max_length` to 300 characters.
4. WHEN `detect_emotion_urgency()` returns `emotion="frustrated"`, THE Conversation_DNA SHALL set tone to "empathetic" and include a patient, solution-focused style instruction.
5. IF `ml_router.detect_emotion_urgency()` raises an exception, THEN THE Orchestrator SHALL continue processing with default values `emotion="neutral"` and `urgency="LOW"` and log a warning.

---

### Requirement 3: Compound Intent (DAG) Support

**User Story:** As Vaibhav, I want to send multi-step instructions to EDITH on Telegram (e.g. "search for X and then send the result to my email"), so that she executes each step in sequence without requiring separate messages.

#### Acceptance Criteria

1. WHEN Telegram_Bot receives a text message, THE Orchestrator SHALL call `compound_dag.detect_compound(user_input)` to check for multi-step intent before dispatching.
2. WHEN `detect_compound()` returns True and `split_into_tasks()` produces 2 or more tasks, THE Orchestrator SHALL execute the tasks as a DAG via `DAGExecutor`, passing `source="telegram"` in each sub-context.
3. WHEN a compound DAG completes successfully, THE Telegram_Bot SHALL send the combined result back to the Owner using the Placeholder_Edit_Pattern.
4. IF a DAG step fails, THEN THE Orchestrator SHALL include the partial results of completed steps and an EDITH-flavoured error note for the failed step in the final response.
5. IF `compound_dag` import fails or raises an exception, THEN THE Orchestrator SHALL fall back to single-intent dispatch and log a warning.

---

### Requirement 4: Typing Indicator

**User Story:** As Vaibhav, I want to see the Telegram "typing…" indicator while EDITH is processing my message, so that I know she received it and is working.

#### Acceptance Criteria

1. WHEN Telegram_Bot receives a message from the Owner and before sending the placeholder message, THE Telegram_Bot SHALL call the Telegram `sendChatAction` API with `action="typing"` for the Owner's `chat_id`.
2. WHEN sending the typing indicator fails due to a network or API error, THE Telegram_Bot SHALL log a warning and continue processing without interruption.
3. THE Telegram_Bot SHALL send the typing action once per received message and SHALL NOT repeat it in a polling loop.

---

### Requirement 5: /history Command

**User Story:** As Vaibhav, I want a `/history` command on Telegram that shows recent conversation turns, so that I can quickly see what I asked EDITH earlier without switching to the web UI.

#### Acceptance Criteria

1. WHEN Telegram_Bot receives the text `/history`, THE Telegram_Bot SHALL retrieve the last 10 turns (5 user + 5 assistant pairs) from `_source_history["telegram"]`.
2. WHEN formatting the history response, THE Telegram_Bot SHALL prefix each user turn with `👤` and each assistant turn with `🤖`, and truncate any individual turn to 150 characters with `…` if longer.
3. WHEN `_source_history["telegram"]` contains fewer than 2 entries, THE Telegram_Bot SHALL reply with "No conversation history yet, Boss."
4. THE Telegram_Bot SHALL NOT route `/history` through the Orchestrator pipeline; it SHALL be handled as a direct command.

---

### Requirement 6: /clear Command

**User Story:** As Vaibhav, I want a `/clear` command that wipes the Telegram conversation history, so that I can start fresh without old context bleeding into new sessions.

#### Acceptance Criteria

1. WHEN Telegram_Bot receives the text `/clear`, THE Telegram_Bot SHALL clear `_source_history["telegram"]` in memory and overwrite `data/telegram_memory.jsonl` with an empty file.
2. WHEN the clear operation succeeds, THE Telegram_Bot SHALL reply "🗑 Telegram history cleared, Boss. Fresh start."
3. IF writing to `data/telegram_memory.jsonl` raises an exception, THEN THE Telegram_Bot SHALL reply with an EDITH-flavoured error message indicating the in-memory history was cleared but disk persistence failed, and log the exception.
4. THE Telegram_Bot SHALL NOT route `/clear` through the Orchestrator pipeline.

---

### Requirement 7: /status Command

**User Story:** As Vaibhav, I want a `/status` command that shows EDITH's current system state on Telegram, so that I can quickly check health without opening the web UI.

#### Acceptance Criteria

1. WHEN Telegram_Bot receives the text `/status`, THE Telegram_Bot SHALL collect and format: active LLM provider (from `smart_router.router_status()`), Telegram history length, memory item count (from `smart_memory`), and current time.
2. WHEN formatting the `/status` response, THE Telegram_Bot SHALL use plain text with emoji labels and keep the total response under 300 characters.
3. IF any status sub-call raises an exception, THEN THE Telegram_Bot SHALL include `"unavailable"` for that field and continue assembling the status response.
4. THE Telegram_Bot SHALL NOT route `/status` through the Orchestrator pipeline.

---

### Requirement 8: Photo / Vision Message Support

**User Story:** As Vaibhav, I want to send a photo to EDITH via Telegram and receive an analysis, so that I can ask EDITH to describe, read, or reason about images from my phone.

#### Acceptance Criteria

1. WHEN Telegram_Bot receives an update containing a `photo` field, THE Telegram_Bot SHALL download the highest-resolution version of the photo from the Telegram file API.
2. WHEN the photo is downloaded successfully, THE Telegram_Bot SHALL route it to the `_handle_vision` handler (intent="vision") via a DispatchContext with `source="telegram"`, passing the local file path and any caption text as `user_input`.
3. WHEN the vision handler returns a result, THE Telegram_Bot SHALL deliver it using the Placeholder_Edit_Pattern.
4. IF the photo download fails, THEN THE Telegram_Bot SHALL reply "Couldn't download that photo, Boss. Try again?" and log the error.
5. IF Telegram_Bot receives an update containing a `photo` field but the `_handle_vision` handler is unavailable, THEN THE Telegram_Bot SHALL reply "Vision isn't available right now, Boss." and log the error.
6. WHEN processing a photo message, THE Telegram_Bot SHALL apply the same Rate_Limiter check as for text messages.

---

### Requirement 9: Reply-Thread Context Awareness

**User Story:** As Vaibhav, I want EDITH to be aware when I'm replying to a specific previous message in Telegram, so that she understands the context I'm replying to without me having to repeat it.

#### Acceptance Criteria

1. WHEN a Telegram update contains a `reply_to_message` field, THE Telegram_Bot SHALL extract the text of the replied-to message and prepend it to `user_input` in the format `[Replying to: "<quoted_text>"] <user_input>`, truncating `quoted_text` to 200 characters if longer.
2. WHEN passing the augmented `user_input` to `orchestrator.chat()`, THE Telegram_Bot SHALL pass the full augmented string so the Orchestrator has the reply context available in the prompt.
3. WHEN a Telegram update does NOT contain a `reply_to_message` field, THE Telegram_Bot SHALL pass `user_input` unmodified.

---

### Requirement 10: Inline HITL Confirmation Buttons for Shell Commands

**User Story:** As Vaibhav, I want EDITH to present an inline Yes/No keyboard on Telegram when she wants to run a shell command that requires my confirmation, so that I can approve or reject it with one tap instead of typing.

#### Acceptance Criteria

1. WHEN a Telegram message triggers a HITL shell confirmation request (i.e., the Dispatcher sets a pending action via `intent_dispatch.set_pending_action()`), THE Telegram_Bot SHALL send an inline keyboard with two buttons: "✅ Yes, run it" (callback_data="hitl_confirm") and "❌ Cancel" (callback_data="hitl_cancel").
2. WHEN the Owner taps "✅ Yes, run it", THE Telegram_Bot SHALL call `intent_dispatch.execute_pending_action()` with the stored pending action and edit the confirmation message with the result.
3. WHEN the Owner taps "❌ Cancel", THE Telegram_Bot SHALL call `intent_dispatch.clear_pending_action()` and edit the message to "Cancelled, Boss."
4. WHEN Telegram_Bot is operating in poll mode, THE Telegram_Bot SHALL process `callback_query` updates in the same polling loop that handles text messages.
5. IF a `callback_query` arrives but no pending action is stored, THEN THE Telegram_Bot SHALL answer the callback with "No pending action found." and log a warning.
6. THE inline keyboard SHALL be removed from the message after the Owner responds (by editing the message without a reply_markup).

---

### Requirement 11: EDITH-Flavoured Error Messages

**User Story:** As Vaibhav, I want any EDITH errors that surface on Telegram to sound like EDITH — direct, not robotic — so that the experience feels consistent even when things go wrong.

#### Acceptance Criteria

1. WHEN an unhandled exception occurs during message processing in Telegram_Bot, THE Telegram_Bot SHALL catch the exception and reply with an error message that matches EDITH's voice (e.g. "Hit a snag on my end, Boss. [brief error context]. Want me to try a different approach?") rather than exposing a raw Python traceback.
2. WHEN the LLM call inside `orchestrator.chat()` fails and the fallback also fails, THE Orchestrator SHALL return an error string starting with "[EDITH]" and Telegram_Bot SHALL forward it to the Owner.
3. WHEN an error message is delivered via Telegram, THE Telegram_Bot SHALL use the Placeholder_Edit_Pattern to replace the "⏳ On it, Boss..." placeholder with the error text.
4. THE Telegram_Bot SHALL log all exceptions at ERROR level before sending any user-facing error message.

---

### Requirement 12: Preserve Existing Telegram Commands and Behaviours

**User Story:** As Vaibhav, I want all existing Telegram commands and behaviours to keep working after the pipeline change, so that nothing I currently rely on breaks.

#### Acceptance Criteria

1. THE Telegram_Bot SHALL continue to handle `/mcpstatus` by calling `_handle_mcpstatus_cmd()` without routing through the Orchestrator pipeline.
2. THE Telegram_Bot SHALL continue to handle `/mcp <args>` by calling `_handle_mcp_cmd(args)` without routing through the Orchestrator pipeline.
3. THE Telegram_Bot SHALL continue to handle open-loop shortcuts — messages containing "loop", "remember", "note" — by calling `add_open_loop()` and returning immediately without routing through the Orchestrator pipeline.
4. THE Telegram_Bot SHALL continue to handle close-loop shortcuts — messages containing "close", "done", "resolved" — by calling `close_open_loop()` and returning immediately.
5. THE Telegram_Bot SHALL continue to send the weekly briefing via `send_weekly_briefing()` on the existing schedule (Sunday 08:00) and drift alerts every 6 hours.
6. THE Telegram_Bot SHALL continue to reject messages from any `chat_id` other than the Owner's `TELEGRAM_CHAT_ID` and log a warning for each rejected message.
7. THE Rate_Limiter (10 messages per 60 seconds per `chat_id`) SHALL remain enforced for all message types including photo messages and callback queries.
8. THE Placeholder_Edit_Pattern ("⏳ On it, Boss..." sent immediately, then edited with the final reply) SHALL remain the default UX for all routed messages.
9. THE Telegram_Bot SHALL continue to operate in both poll mode (`poll_telegram()`) and webhook mode (`handle_telegram_update()`) after all changes.

---

### Requirement 13: Telegram History Persistence and Continuity

**User Story:** As Vaibhav, I want my Telegram conversation history to survive EDITH daemon restarts, so that EDITH remembers what we talked about on Telegram even if the service restarts overnight.

#### Acceptance Criteria

1. THE Orchestrator SHALL pre-load `_source_history["telegram"]` from `data/telegram_memory.jsonl` on module import, retaining up to the most recent 20 turns.
2. WHEN `orchestrator.chat()` appends a new user or assistant message to `_source_history["telegram"]`, THE Orchestrator SHALL also append that message to `data/telegram_memory.jsonl`.
3. WHEN `data/telegram_memory.jsonl` exceeds 500 lines, THE Orchestrator SHALL rotate it by discarding the oldest 100 lines in an atomic file-replace operation.
4. IF `data/telegram_memory.jsonl` is corrupted or unreadable on load, THEN THE Orchestrator SHALL start with an empty Telegram history, log the error, and continue operating normally.
5. WHEN the `/clear` command is issued, THE Telegram_Bot SHALL set `_source_history["telegram"]` to an empty list in the Orchestrator's memory AND overwrite `data/telegram_memory.jsonl` with an empty file atomically.
