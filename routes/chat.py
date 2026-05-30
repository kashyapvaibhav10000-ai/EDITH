import asyncio
import json
import os
import re
import sys
import threading
import uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, StreamingResponse

# Add parent directory to path to allow imports
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import USE_CHATTERBOX, USE_GROQ_TTS, get_logger
from context import DispatchContext
from feedback_tagger import detect_implicit_feedback
from intent import detect_intent
from intent_dispatch import (INTENT_HANDLERS, _run_local_exec,
                             clear_pending_action, dispatch,
                             execute_pending_action, get_pending_action)
from life_os import add_open_loop
from orchestrator import chat, chat_stream
from phone import initiate_call, send_sms
from search import format_results as _fmt
from search import web_search as _web_search
from session import get_session_id
from session import start_session as _start_session
from shared_state import (_widget_history, _widget_history_lock,
                          add_to_history, get_history)
from smart_router import get_last_call_stats
from trace_logger import get_recent_traces
from voice import speak_sentence

log = get_logger("chat_routes")
router = APIRouter()

_DISPATCH_LOCK = asyncio.Lock()
_SIDE_EFFECT_INTENTS = {"email", "sms", "call", "calendar_create", "shell", "agent", "create_file", "delete_file"}
_MAX_WIDGET_HISTORY = 50
_MAX_WIDGET_HISTORY_BYTES = 512 * 1024  # 512KB total cap

def _trim_history_if_needed():
    with _widget_history_lock:
        while len(_widget_history) > _MAX_WIDGET_HISTORY * 2:
            _widget_history.pop(next(iter(_widget_history)))
        while len(_widget_history) > 1:
            total = sum(len(str(v)) for v in _widget_history.values())
            if total <= _MAX_WIDGET_HISTORY_BYTES:
                break
            _widget_history.pop(next(iter(_widget_history)))

def _track_widget_msg(content, role, intent):
    with _widget_history_lock:
        msg_id = len(_widget_history)
        _widget_history[msg_id] = {"role": role, "content": content, "intent": intent}
    _trim_history_if_needed()

def _persist_exchange(user_msg: str, assistant_msg: str, session_id: str = None) -> str:
    try:
        import time
        session_id = session_id or get_session_id()
        if not session_id or session_id == "unknown":
            session_id = _start_session("web")
        _db = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "session_state.db")
        import sqlite3
        conn = sqlite3.connect(_db)
        c = conn.cursor()
        row = c.execute("SELECT conversation_json FROM sessions WHERE session_id=?", (session_id,)).fetchone()
        turns = json.loads(row[0]) if row and row[0] else []
        ts = time.strftime("%H:%M")
        turns.append({"role": "user", "content": user_msg, "ts": ts})
        turns.append({"role": "assistant", "content": assistant_msg, "ts": ts})
        if len(turns) > 100:
            turns = turns[-100:]
        c.execute("UPDATE sessions SET conversation_json=? WHERE session_id=?", (json.dumps(turns), session_id))
        conn.commit()
        conn.close()
        return session_id
    except Exception as e:
        log.warning(f"persist_exchange failed: {e}")
        return session_id or ""

def _get_last_exchange():
    with _widget_history_lock:
        values = list(_widget_history.values())
        if len(values) >= 2:
            return values[-2], values[-1]
    return None, None

def _is_followup(user_input):
    last_user, last_bot = _get_last_exchange()
    if not last_bot:
        return False, None
    lower = user_input.strip().lower()
    last_intent = last_bot.get("intent", "")
    last_reply = last_bot.get("content", "").lower()
    if lower in ("yes", "y", "no", "n", "ok", "sure", "cancel", "nevermind", "stop"):
        return True, "confirmation"
    if len(lower.split()) <= 5:
        new_intent = detect_intent(user_input)
        if new_intent not in ("chat", "unknown", last_intent):
            has_digits = bool(re.search(r'\d', lower))
            if last_intent in ("call", "sms") and has_digits:
                pass
            else:
                return False, None
        if last_intent == "call" and ("whom" in last_reply or "number" in last_reply or "who" in last_reply):
            return True, "call_followup"
        if last_intent in ("phone", "sms") and ("whom" in last_reply or "number" in last_reply or "who" in last_reply):
            return True, "sms_followup"
        if last_intent == "self_improve" and any(w in lower for w in ["ok", "yes", "add", "approve", "do it", "go ahead"]):
            return True, "self_improve_accept"
    return False, None

def _handle_followup(user_input, fu_type):
    last_user, last_bot = _get_last_exchange()
    if fu_type == "call_followup":
        number = _extract_phone_number(user_input.strip())
        if number:
            initiate_call(number)
            return f"📞 Calling {number} now.", "call"
        return "That doesn't look like a valid number. Give me something like +919305819663.", "call"
    elif fu_type == "sms_followup":
        original_msg = last_user.get("content", "") if last_user else ""
        body = _extract_sms_body(original_msg)
        if not body:
            m = re.search(r"(?:say|saying|text|send)\s+(.+)", original_msg, re.IGNORECASE)
            body = m.group(1).strip() if m else "hi"
        number = _extract_phone_number(user_input.strip())
        if number:
            send_sms(number, body)
            return f'📱 SMS sent to {number}: "{body}"', "sms"
        return "That doesn't look like a valid number. Try: +91XXXXXXXXXX", "sms"
    elif fu_type == "self_improve_accept":
        proposal = last_bot.get("content", "")[:200] if last_bot else "last proposal"
        add_open_loop(f"Implement upgrade: {proposal[:100]}")
        return "✅ Got it, Boss. I've added this upgrade proposal to your open loops for implementation.", "self_improve"
    elif fu_type == "confirmation":
        context = f"Previous: {last_bot.get('content', '')[:200]}\nUser follow-up: {user_input}"
        return chat(context, intent="chat"), "chat"
    context = last_bot.get("content", "") if last_bot else ""
    prev_intent = last_user.get("intent", "chat") if last_user else "chat"
    return chat(f"Previous: {context[:500]}\n\nUser follow-up: {user_input}", intent=prev_intent), prev_intent

@router.post("/api/chat/stream")
async def chat_stream_endpoint(req: Request):
    data = await req.json()
    user_input = data.get("message", "")
    req_session_id = data.get("session_id")
    if not user_input:
        return {"reply": "Please provide your input.", "intent": "unknown"}
    pending = get_pending_action()
    if pending:
        ans = user_input.strip().upper()
        if ans in ("YES", "Y"):
            try:
                reply = execute_pending_action(pending)
            except Exception as e:
                reply = f"❌ Error executing action: {e}"
            clear_pending_action()
            _track_widget_msg(user_input, "user", "confirm")
            _track_widget_msg(reply, "assistant", "executed")
            msg_id = str(uuid.uuid4())
            async def _pending_sse_yes():
                yield f"data: {json.dumps({'type': 'start', 'id': msg_id, 'provider': 'local', 'intent': 'executed'})}\n\n"
                yield f"data: {json.dumps({'type': 'token', 'id': msg_id, 'token': reply})}\n\n"
                yield f"data: {json.dumps({'type': 'done', 'id': msg_id, 'provider': 'local', 'intent': 'executed', 'tts_engine': 'piper'})}\n\n"
            return StreamingResponse(_pending_sse_yes(), media_type="text/event-stream")
        elif ans in ("NO", "N", "CANCEL", "STOP"):
            clear_pending_action()
            _track_widget_msg(user_input, "user", "cancel")
            _track_widget_msg("Action cancelled.", "assistant", "cancelled")
            msg_id = str(uuid.uuid4())
            async def _pending_sse_no():
                yield f"data: {json.dumps({'type': 'start', 'id': msg_id, 'provider': 'local', 'intent': 'cancelled'})}\n\n"
                yield f"data: {json.dumps({'type': 'token', 'id': msg_id, 'token': 'Action cancelled.'})}\n\n"
                yield f"data: {json.dumps({'type': 'done', 'id': msg_id, 'provider': 'local', 'intent': 'cancelled', 'tts_engine': 'piper'})}\n\n"
            return StreamingResponse(_pending_sse_no(), media_type="text/event-stream")
        else:
            clear_pending_action()
    intent = detect_intent(user_input)
    msg_id = str(uuid.uuid4())
    try:
        provider = get_last_call_stats().get("provider", "unknown")
    except Exception:
        provider = "unknown"
    async def event_generator():
        nonlocal provider
        try:
            yield f"data: {json.dumps({'type': 'start', 'id': msg_id, 'provider': provider, 'intent': intent})}\n\n"
            yield f"data: {json.dumps({'type': 'transcript', 'text': user_input})}\n\n"
            full_reply = ""
            current_sentence = ""
            _ACTION_INTENTS = set(INTENT_HANDLERS.keys()) - {"chat", "lookup", "reason", "search"}
            if intent in _ACTION_INTENTS:
                log.info(f"[Stream] Action intent '{intent}' — dispatching")
                _ctx = DispatchContext(user_input=user_input, intent=intent, source="stream", chat_fn=chat, chat_stream_fn=chat_stream)
                if intent in _SIDE_EFFECT_INTENTS:
                    async with _DISPATCH_LOCK:
                        _result = await asyncio.to_thread(dispatch, _ctx)
                else:
                    _result = await asyncio.to_thread(dispatch, _ctx)
                full_reply = _result if isinstance(_result, str) else str(_result)
                yield f"data: {json.dumps({'type': 'token', 'id': msg_id, 'token': full_reply})}\n\n"
                yield f"data: {json.dumps({'type': 'done', 'id': msg_id, 'provider': provider, 'intent': intent, 'tts_engine': 'piper'})}\n\n"
                return
            if intent == "shell":
                try:
                    _local_reply = await asyncio.to_thread(_run_local_exec, user_input)
                except Exception:
                    _local_reply = None
                if _local_reply:
                    full_reply = _local_reply
                    yield f"data: {json.dumps({'type': 'start', 'id': msg_id, 'provider': 'local', 'intent': 'shell'})}\n\n"
                    yield f"data: {json.dumps({'type': 'token', 'id': msg_id, 'token': full_reply})}\n\n"
                    yield f"data: {json.dumps({'type': 'done', 'id': msg_id, 'provider': 'local', 'intent': 'shell', 'tts_engine': 'piper'})}\n\n"
                    return
            _enriched_input = user_input
            try:
                _TEMPORAL = re.compile(r"\b(who won|score|result|ipl|cricket|football|election|stock|price|match|latest|today|current|news|recent|now|happening|update|yesterday|tonight|who is|what happened)\b", re.IGNORECASE)
                if intent in {"search", "lookup"} or _TEMPORAL.search(user_input):
                    _ist = timezone(timedelta(hours=5, minutes=30))
                    _now = datetime.now(_ist)
                    _sq = user_input
                    if not re.search(r'\b20\d{2}\b', user_input):
                        _sq = f"Today is {_now.strftime('%A %B %d %Y')}, India IST. {user_input}"
                    _results_r = await asyncio.to_thread(_web_search, _sq)
                    _results = _results_r.value if _results_r.ok else []
                    _formatted = _fmt(_results)
                    if _formatted and "error" not in _formatted.lower():
                        _enriched_input = (f"Web search results for '{user_input}':\n{_formatted}\n\n"
                                         f"Using the above results, answer: {user_input}")
                        log.info(f"Stream search enriched (async): {_sq[:80]}")
            except Exception as _e:
                log.warning(f"stream search enrichment failed: {_e}")
            for token in chat_stream(_enriched_input, intent=intent):
                full_reply += token
                current_sentence += token
                yield f"data: {json.dumps({'type': 'token', 'id': msg_id, 'token': token})}\n\n"
                stripped = current_sentence.strip()
                if re.search(r'[.!?:;]\s*$', stripped):
                    if len(stripped) >= 4 or stripped in ("Done.", "Yes.", "No.", "Ok.", "Sure.", "Got it."):
                        threading.Thread(target=speak_sentence, args=(current_sentence.strip(),), daemon=True).start()
                    current_sentence = ""
            try:
                provider_data = get_last_call_stats().get("provider", "unknown")
                if provider_data and provider_data != "unknown":
                    provider = provider_data
            except Exception:
                pass
            tts_engine = "piper"
            try:
                if USE_CHATTERBOX:
                    tts_engine = "chatterbox"
                elif USE_GROQ_TTS:
                    tts_engine = "groq"
            except Exception:
                pass
            used_sid = _persist_exchange(user_input, full_reply, req_session_id)
            yield f"data: {json.dumps({'type': 'done', 'id': msg_id, 'provider': provider, 'intent': intent, 'tts_engine': tts_engine, 'session_id': used_sid})}\n\n"
        except Exception as e:
            log.error(f"Streaming error: {e}")
            yield f"data: {json.dumps({'type': 'error', 'id': msg_id, 'error': str(e)})}\n\n"
    return StreamingResponse(event_generator(), media_type="text/event-stream")

@router.post("/api/chat")
async def chat_endpoint(req: Request):
    data = await req.json()
    user_input = data.get("message", "")
    req_session_id = data.get("session_id")
    if not user_input:
        return {"reply": "Please provide your input.", "intent": "unknown"}
    pending = get_pending_action()
    if pending:
        ans = user_input.strip().upper()
        if ans in ["YES", "Y"]:
            clear_pending_action()
            try:
                reply = execute_pending_action(pending)
            except Exception as e:
                reply = f"Error executing action: {e}"
            _track_widget_msg(user_input, "user", "confirm")
            _track_widget_msg(reply, "assistant", "executed")
            return {"reply": reply, "intent": "executed"}
        elif ans in ["NO", "N", "CANCEL", "STOP"]:
            clear_pending_action()
            _track_widget_msg(user_input, "user", "cancel")
            _track_widget_msg("Action cancelled.", "assistant", "cancelled")
            return {"reply": "Action cancelled.", "intent": "cancelled"}
        else:
            clear_pending_action()
    is_fu, fu_type = _is_followup(user_input)
    if is_fu:
        reply, intent = _handle_followup(user_input, fu_type)
        _track_widget_msg(user_input, "user", intent)
        _track_widget_msg(reply, "assistant", intent)
        return {"reply": reply, "intent": intent}
    intent = detect_intent(user_input)
    log.info(f"[Widget] Intent: {intent} | Input: {user_input[:80]}")
    # Recall memory for context injection
    from orchestrator import recall, recall_episodes
    _memories = recall(user_input)
    _episodes = recall_episodes(user_input, n=1)
    _mem_list = [m["value"] for m in _memories if isinstance(m, dict) and "value" in m] or _memories
    _memory_context = "\n".join(str(m) for m in _mem_list) if _mem_list else ""
    if _episodes:
        _memory_context += f"\n\nPast Session: {_episodes[0]}"
    ctx = DispatchContext(user_input=user_input, intent=intent, source="widget",
                          chat_fn=chat, chat_stream_fn=chat_stream,
                          memory_context=_memory_context)
    if intent in _SIDE_EFFECT_INTENTS:
        async with _DISPATCH_LOCK:
            reply = await asyncio.to_thread(dispatch, ctx)
    else:
        reply = await asyncio.to_thread(dispatch, ctx)
    _track_widget_msg(user_input, "user", intent)
    _track_widget_msg(reply, "assistant", intent)
    used_sid = _persist_exchange(user_input, reply, req_session_id)
    try:
        _recent = get_recent_traces(limit=2)
        if len(_recent) >= 2:
            _prev_trace_id = _recent[1].get("trace_id")
            if _prev_trace_id:
                detect_implicit_feedback(_prev_trace_id, user_input)
    except Exception:
        pass
    return {"reply": reply, "intent": intent, "session_id": used_sid}
