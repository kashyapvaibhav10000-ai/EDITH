from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
import uvicorn
import asyncio
import sys
import os
import tempfile
import re
import datetime
import threading
import subprocess
import shlex
import gc
import psutil
import uuid
import json
import traceback

# Ensure EDITH directory is in path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from orchestrator import chat, chat_stream, detect_intent
from voice import speak
from config import get_logger
from context import DispatchContext
from intent_dispatch import (
    dispatch, execute_pending_action,
    get_pending_action, set_pending_action, clear_pending_action,
    _extract_phone_number, _extract_sms_body,
)

log = get_logger("chat_server")


def _get_voice_memory_context(user_input: str) -> str:
    """Fetch relevant ChromaDB memory for voice query. Returns empty str on any error."""
    try:
        from config import get_chroma_client
        client = get_chroma_client()
        collection = client.get_collection("edith_history")
        results = collection.query(
            query_texts=[user_input],
            n_results=3,
            include=["documents"]
        )
        docs = results.get("documents", [[]])[0]
        if docs:
            return " | ".join(str(d)[:300] for d in docs)
    except Exception as e:
        log.debug(f"Voice memory fetch (non-fatal): {e}")
    return ""


app = FastAPI()

# ────────────────────────────────────────────────────
# API Key Authentication Middleware (before CORS)
# ────────────────────────────────────────────────────
_keys_raw = os.getenv("EDITH_API_KEYS", "") + "," + os.getenv("EDITH_API_KEY", "")
_VALID_API_KEYS = set(filter(None, _keys_raw.split(",")))

@app.middleware("http")
async def api_key_middleware(request: Request, call_next):
    """Validate API key for protected endpoints before CORS processing."""
    # Public endpoints that don't require auth
    public_paths = {"/", "/dashboard", "/ui", "/static"}
    if any(request.url.path.startswith(p) for p in public_paths):
        return await call_next(request)
    
    # Protected endpoints — require valid API key
    api_key = request.headers.get("X-API-Key", "") or request.headers.get("Authorization", "").replace("Bearer ", "")
    if not api_key or api_key not in _VALID_API_KEYS:
        return JSONResponse(
            status_code=401,
            content={"error": "Unauthorized: missing or invalid API key"}
        )
    return await call_next(request)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["POST", "GET", "DELETE"],
    allow_headers=["Content-Type", "X-Admin-Token"],
    allow_credentials=False,
)

# Mount static files for AudioWorklet and perception engine
_STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")
if os.path.isdir(_STATIC_DIR):
    app.mount("/static", StaticFiles(directory=_STATIC_DIR), name="static")

_UI_HTML_PATH        = os.path.join(os.path.dirname(os.path.abspath(__file__)), "edith_ui_new.html")
_DASHBOARD_HTML_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "edith_dashboard.html")


def verify_mcp_admin_token(supplied_token: str, expected_token: str = None) -> bool:
    """Return True when the supplied MCP admin token matches configured auth."""
    expected = expected_token if expected_token is not None else os.getenv("MCP_ADMIN_TOKEN", "")
    return bool(expected) and supplied_token == expected


def _check_mcp_admin(req: Request):
    """Require MCP_ADMIN_TOKEN for MCP mutation endpoints."""
    expected = os.getenv("MCP_ADMIN_TOKEN", "")
    if not expected:
        log.error("MCP_ADMIN_TOKEN not set; rejecting MCP mutation request")
        return JSONResponse(
            status_code=401,
            content={
                "ok": False,
                "error": "Unauthorized: MCP_ADMIN_TOKEN is not configured on the server.",
            },
        )
    supplied = req.headers.get("X-Admin-Token", "")
    if not verify_mcp_admin_token(supplied, expected):
        return JSONResponse(
            status_code=401,
            content={
                "ok": False,
                "error": "Unauthorized: missing or invalid X-Admin-Token header.",
            },
        )
    return None

@app.get("/", response_class=HTMLResponse)
def index():
    from fastapi.responses import RedirectResponse
    return RedirectResponse(url="/dashboard")

# ────────────────────────────────────────────────────
# Rate Limiting
# ────────────────────────────────────────────────────
import time
from fastapi.responses import JSONResponse

_rate_limit_cache = {}
_RATE_LIMIT_MAX = 120
_RATE_LIMIT_WINDOW = 60

@app.middleware("http")
async def rate_limit_middleware(request: Request, call_next):
    ip = request.client.host if request.client else "127.0.0.1"
    now = time.time()

    expired = [k for k, (_, ts) in _rate_limit_cache.items() if now - ts > 86400]
    for k in expired:
        del _rate_limit_cache[k]

    if ip in _rate_limit_cache:
        count, start_time = _rate_limit_cache[ip]
        if now - start_time > _RATE_LIMIT_WINDOW:
            _rate_limit_cache[ip] = (1, now)
        else:
            if count >= _RATE_LIMIT_MAX:
                return JSONResponse(status_code=429, content={"error": "Rate limit exceeded. Too many requests."})
            _rate_limit_cache[ip] = (count + 1, start_time)
    else:
        _rate_limit_cache[ip] = (1, now)
        
    return await call_next(request)
# ────────────────────────────────────────────────────
# Multi-turn conversation context for the widget
# ────────────────────────────────────────────────────
# M9: Import from shared_state to avoid circular imports
from shared_state import _widget_history, _widget_history_lock, add_to_history, get_history
_MAX_WIDGET_HISTORY = 10

# ── Repo DNA — competitive intelligence engine ──
try:
    from repo_dna import (
        analyze_repo as _analyze_repo,
        get_cached_analyses as _get_cached_analyses,
        clear_cache as _clear_repo_cache,
        watch_repo as _watch_repo,
        get_watched_repos as _get_watched_repos,
        check_watched_repos as _check_watched_repos,
        _build_edith_context_summary,
        mark_adapted as _mark_adapted,
        get_adapted_capabilities as _get_adapted_caps,
        RepoFetchError,
        RepoAnalysisError,
    )
    _REPO_DNA_OK = True
except ImportError:
    _REPO_DNA_OK = False

# ── Adapt status tracking (event-driven, module-level) ──
_adapt_results: dict = {}   # task_id → {status, summary/error}
_adapt_meta: dict = {}      # task_id → {capability, repo_url, target_file}

try:
    from event_bus import bus as _bus, Topic as _Topic

    def _on_agent_done(payload: dict) -> None:
        tid = payload.get("task_id", "")
        _adapt_results[tid] = {"status": "done", "summary": payload.get("summary", "")}
        if len(_adapt_results) > 200:
            _adapt_results.pop(next(iter(_adapt_results)))
        meta = _adapt_meta.pop(tid, None)
        if meta and _REPO_DNA_OK:
            try:
                _mark_adapted(meta["repo_url"], meta["capability"], meta["target_file"])
            except Exception as _me:
                log.warning(f"[repo_adapt] mark_adapted failed: {_me}")

    def _on_agent_error(payload: dict) -> None:
        tid = payload.get("task_id", "")
        _adapt_results[tid] = {"status": "failed", "error": payload.get("error", "")}
        if len(_adapt_results) > 200:
            _adapt_results.pop(next(iter(_adapt_results)))
        _adapt_meta.pop(tid, None)

    _bus.subscribe_fn(_Topic.AGENT_DONE, _on_agent_done)
    _bus.subscribe_fn(_Topic.AGENT_ERROR, _on_agent_error)
    _ADAPT_TRACKING_OK = True
except Exception:
    _ADAPT_TRACKING_OK = False


def _get_last_exchange():
    """Get the last user→assistant exchange for follow-up context."""
    with _widget_history_lock:
        values = list(_widget_history.values())
        if len(values) >= 2:
            return values[-2], values[-1]
    return None, None


def _is_followup(user_input):
    """Detect if this message is a follow-up to the previous exchange."""
    last_user, last_bot = _get_last_exchange()
    if not last_bot:
        return False, None

    lower = user_input.strip().lower()
    last_intent = last_bot.get("intent", "")
    last_reply = last_bot.get("content", "").lower()

    # Generic confirmation or cancellation
    if lower in ("yes", "y", "no", "n", "ok", "sure", "cancel", "nevermind", "stop"):
        return True, "confirmation"

    # Short replies might be follow-ups
    if len(lower.split()) <= 5:
        from intent import detect_intent as _detect
        new_intent = _detect(user_input)

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


# ────────────────────────────────────────────────────
# Streaming Endpoint
# ────────────────────────────────────────────────────
@app.post("/api/chat/stream")
async def chat_stream_endpoint(req: Request):
    """SSE Streaming endpoint for real-time chat replies."""
    data = await req.json()
    user_input = data.get("message", "")
    req_session_id = data.get("session_id")
    if not user_input:
        return {"reply": "Please provide your input.", "intent": "unknown"}

    # ── Handle Pending Action Confirmations before intent routing ──
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
        from smart_router import get_last_call_stats
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

            # Action intents: dispatch instead of chat_stream
            from intent_dispatch import INTENT_HANDLERS, dispatch as _dispatch_stream
            _ACTION_INTENTS = set(INTENT_HANDLERS.keys()) - {"chat", "lookup", "reason", "search"}
            if intent in _ACTION_INTENTS:
                log.info(f"[Stream] Action intent '{intent}' — dispatching")
                _ctx = DispatchContext(
                    user_input=user_input, intent=intent, source="stream",
                    chat_fn=chat, chat_stream_fn=chat_stream,
                )
                _result = await asyncio.to_thread(_dispatch_stream, _ctx)
                full_reply = _result if isinstance(_result, str) else str(_result)
                yield f"data: {json.dumps({'type': 'token', 'id': msg_id, 'token': full_reply})}\n\n"
                yield f"data: {json.dumps({'type': 'done', 'id': msg_id, 'provider': provider, 'intent': intent, 'tts_engine': 'piper'})}\n\n"
                return

            # --- local exec shortcut: never web-search / hallucinate local system queries ---
            from intent_dispatch import _run_local_exec as _rle
            try:
                _local_reply = await asyncio.to_thread(_rle, user_input)
            except Exception:
                _local_reply = None
            if _local_reply:
                full_reply = _local_reply
                yield f"data: {json.dumps({'type': 'start', 'id': msg_id, 'provider': 'local', 'intent': 'shell'})}\n\n"
                yield f"data: {json.dumps({'type': 'token', 'id': msg_id, 'token': full_reply})}\n\n"
                yield f"data: {json.dumps({'type': 'done', 'id': msg_id, 'provider': 'local', 'intent': 'shell', 'tts_engine': 'piper'})}\n\n"
                return

            # --- async search enrichment (thread-isolated to avoid blocking event loop) ---
            _enriched_input = user_input
            try:
                import re as _re
                from datetime import datetime, timezone, timedelta
                from search import web_search as _web_search, format_results as _fmt
                _TEMPORAL = _re.compile(
                    r"\b(who won|score|result|ipl|cricket|football|election|stock|"
                    r"price|match|latest|today|current|news|recent|now|happening|"
                    r"update|yesterday|tonight|who is|what happened)\b",
                    _re.IGNORECASE
                )
                if intent in {"search", "lookup"} or _TEMPORAL.search(user_input):
                    _ist = timezone(timedelta(hours=5, minutes=30))
                    _now = datetime.now(_ist)
                    _sq = user_input
                    if not _re.search(r'\b20\d{2}\b', user_input):
                        _sq = f"Today is {_now.strftime('%A %B %d %Y')}, India IST. {user_input}"
                    _results_r = await asyncio.to_thread(_web_search, _sq)
                    _results = _results_r.value if _results_r.ok else []
                    _formatted = _fmt(_results)
                    if _formatted and "error" not in _formatted.lower():
                        _enriched_input = (
                            f"Web search results for '{user_input}':\n{_formatted}\n\n"
                            f"Using the above results, answer: {user_input}"
                        )
                        log.info(f"Stream search enriched (async): {_sq[:80]}")
            except Exception as _e:
                log.warning(f"stream search enrichment failed: {_e}")
            # --- end async search enrichment ---

            for token in chat_stream(_enriched_input, intent=intent):
                full_reply += token
                current_sentence += token
                yield f"data: {json.dumps({'type': 'token', 'id': msg_id, 'token': token})}\n\n"
                
                # Check for sentence boundaries: . ! ? : ; or 4+ chars minimum
                stripped = current_sentence.strip()
                if re.search(r'[.!?:;]\s*$', stripped):
                    if len(stripped) >= 4 or stripped in ("Done.", "Yes.", "No.", "Ok.", "Sure.", "Got it."):
                        def speak_sent(text):
                            try:
                                from voice import speak_sentence
                                speak_sentence(text)
                            except Exception as e:
                                log.warning(f"Sentence TTS error: {e}")
                        threading.Thread(target=speak_sent, args=(current_sentence.strip(),), daemon=True).start()
                    current_sentence = ""
            
            try:
                from smart_router import get_last_call_stats
                provider_data = get_last_call_stats().get("provider", "unknown")
                if provider_data and provider_data != "unknown":
                    provider = provider_data
            except Exception:
                pass
            
            tts_engine = "piper"
            try:
                from config import USE_GROQ_TTS, USE_CHATTERBOX
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


# ────────────────────────────────────────────────────
# Main Chat Endpoint (dispatch via DispatchContext)
# ────────────────────────────────────────────────────
@app.post("/api/chat")
async def chat_endpoint(req: Request):
    data = await req.json()
    user_input = data.get("message", "")
    req_session_id = data.get("session_id")
    if not user_input:
        return {"reply": "Please provide your input.", "intent": "unknown"}

    # ── Handle Pending Action Confirmations (YES/NO) ──
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

    # ── Check if this is a follow-up to the previous exchange ──
    is_fu, fu_type = _is_followup(user_input)
    if is_fu:
        reply, intent = _handle_followup(user_input, fu_type)
        _track_widget_msg(user_input, "user", intent)
        _track_widget_msg(reply, "assistant", intent)
        return {"reply": reply, "intent": intent}

    intent = detect_intent(user_input)
    log.info(f"[Widget] Intent: {intent} | Input: {user_input[:80]}")

    # ── Build DispatchContext and route ──
    ctx = DispatchContext(
        user_input=user_input,
        intent=intent,
        source="widget",
        chat_fn=chat,
        chat_stream_fn=chat_stream,
    )
    reply = await asyncio.to_thread(dispatch, ctx)

    _track_widget_msg(user_input, "user", intent)
    _track_widget_msg(reply, "assistant", intent)
    used_sid = _persist_exchange(user_input, reply, req_session_id)

    # Tag implicit feedback on the previous exchange (lazy import, never blocks response)
    try:
        from feedback_tagger import detect_implicit_feedback
        from trace_logger import get_recent_traces
        _recent = get_recent_traces(limit=2)
        if len(_recent) >= 2:
            _prev_trace_id = _recent[1].get("trace_id")
            if _prev_trace_id:
                detect_implicit_feedback(_prev_trace_id, user_input)
    except Exception:
        pass

    return {"reply": reply, "intent": intent, "session_id": used_sid}


# ────────────────────────────────────────────────────
# Voice Pipeline Endpoints
# ────────────────────────────────────────────────────

@app.post("/api/voice/transcribe")
async def voice_transcribe_endpoint(request: Request):
    tmp_path = None
    try:
        log.info(f"voice/transcribe called, content-type: {request.headers.get('content-type')}, body will be read")
        audio_bytes = await request.body()
        if not audio_bytes or len(audio_bytes) < 4000:
            log.warning(f"Audio blob too small: {len(audio_bytes)} bytes — rejecting")
            return JSONResponse({"error": "No audio received"}, status_code=400)

        mime_type = request.headers.get("content-type", "audio/webm")
        with tempfile.NamedTemporaryFile(suffix=".webm", delete=False) as tmp:
            tmp.write(audio_bytes)
            tmp_path = tmp.name

        from voice import _last_intent, _transcribe_local
        from config import PRIVATE_INTENTS
        is_private = _last_intent in PRIVATE_INTENTS

        engine_used = "local"
        try:
            if is_private:
                transcript = _transcribe_local(tmp_path)
            else:
                import requests as _req
                import vault
                groq_key = vault.get_secret("GROQ_API_KEY", "") or os.getenv("GROQ_API_KEY", "")
                if not groq_key:
                    transcript = _transcribe_local(tmp_path)
                else:
                    # Browser already does RMS check via AudioContext — skip unreliable server-side WebM byte check
                    with open(tmp_path, "rb") as f:
                        audio_data = f.read()
                    try:
                        ctx_parts = []
                        from shared_state import get_recent_context as _get_ctx
                        for m in _get_ctx(max_items=2):
                            if isinstance(m, dict):
                                ctx_parts.append(f"{m.get('role','')}: {str(m.get('content',''))[:300]}")
                        ctx_str = " | ".join(ctx_parts) if ctx_parts else ""
                        stt_prompt = "EDITH AI assistant. User speaks English Hindi Hinglish."
                        if ctx_str:
                            stt_prompt += f" Recent context: {ctx_str}"
                    except Exception:
                        stt_prompt = "EDITH AI assistant. User speaks English Hindi Hinglish."
                    resp = _req.post(
                        "https://api.groq.com/openai/v1/audio/transcriptions",
                        headers={"Authorization": f"Bearer {groq_key}"},
                        files={"file": ("audio.webm", audio_data, mime_type)},
                        data={
                            "model": "whisper-large-v3-turbo",
                            "prompt": stt_prompt,
                        },
                        timeout=30,
                    )
                    if resp.status_code == 200:
                        transcript = resp.json().get("text", "").strip()
                        engine_used = "groq"
                    else:
                        log.warning(f"Groq STT failed {resp.status_code}: {resp.text}")
                        transcript = _transcribe_local(tmp_path)
        finally:
            try:
                os.unlink(tmp_path)
            except Exception:
                pass

        log.info(f"Voice STT: {engine_used} → {transcript[:50]}")
        if not transcript or not transcript.strip():
            return JSONResponse({"error": "Could not transcribe audio"}, status_code=400)

        # Hallucination filter — known Whisper ghost phrases on silent/noise audio
        WHISPER_HALLUCINATIONS = {
            "thank you", "thanks", "thanks for watching",
            "thanks for watching!", "thank you for watching",
            "bye", "goodbye", "good bye", "see you",
            "subtitles by", "www.", "http", "subtitled by",
            ".", "..", "...", "!", "?", "-", "—",
            "you", "the", "a", "an", "and", "to",
            "i", "it", "in", "is", "be", "was",
        }
        transcript_clean = transcript.strip()
        transcript_lower = transcript_clean.lower().strip()
        transcript_words = transcript_lower.split()

        if len(transcript_words) < 2 or len(transcript_clean) < 5:
            log.warning(f"Transcript too short: '{transcript_clean}' — rejecting")
            return JSONResponse({"error": "Could not transcribe audio"}, status_code=400)

        if transcript_lower in WHISPER_HALLUCINATIONS:
            log.warning(f"Hallucination detected: '{transcript_clean}' — rejecting")
            return JSONResponse({"error": "Could not transcribe audio"}, status_code=400)

        if re.match(r'^[\d\s\.\,\!\?\-\_]+$', transcript_lower):
            log.warning(f"Numbers/punctuation only: '{transcript_clean}' — rejecting")
            return JSONResponse({"error": "Could not transcribe audio"}, status_code=400)

        # Semantic check: must have at least one content word (len > 2, not a stopword)
        _STOPWORDS = {
            "the", "a", "an", "is", "it", "in", "on", "at", "to", "for",
            "of", "and", "or", "but", "not", "no", "so", "do", "did",
            "can", "will", "was", "are", "be", "has", "had", "have",
            "he", "she", "we", "you", "they", "me", "him", "her",
            "ok", "okay", "yes", "yep", "yeah", "nope", "hmm", "uh", "um",
        }
        content_words = [w for w in transcript_words if len(w) > 2 and w not in _STOPWORDS]
        if not content_words:
            log.warning(f"No content words in transcript: '{transcript_clean}' — rejecting")
            return JSONResponse({"error": "Could not transcribe audio"}, status_code=400)

        log.info(f"Transcript accepted: '{transcript_clean[:60]}'")
        return JSONResponse({"transcript": transcript_clean, "status": "ok"})
    except Exception as e:
        log.error(f"voice/transcribe FATAL: {traceback.format_exc()}")
        if tmp_path:
            try:
                os.unlink(tmp_path)
            except Exception:
                pass
        return JSONResponse({"error": str(e), "detail": traceback.format_exc()}, status_code=500)


@app.post("/api/voice/respond")
async def voice_respond_endpoint(request: Request):
    """SSE Streaming endpoint for voice responses with sentence-level TTS."""
    data = await request.json()
    user_input = data.get("text", "").strip()
    if not user_input:
        return {"error": "No text provided"}
    
    import config as _cfg
    from intent import detect_intent
    intent = detect_intent(user_input)

    # Voice mode triggers — switch TTS engine
    user_lower = user_input.lower().strip()
    if _cfg.FRIEND_VOICE_TRIGGER in user_lower:
        _cfg.PREFER_FAST_TTS = False
        log.info("Switched to friend voice mode (Chatterbox)")
        async def _friend_gen():
            yield f"data: {json.dumps({'type': 'start', 'intent': 'chat'})}\n\n"
            yield f"data: {json.dumps({'type': 'token', 'text': 'Switching to friend voice mode.'})}\n\n"
            yield f"data: {json.dumps({'type': 'done'})}\n\n"
        return StreamingResponse(_friend_gen(), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    if _cfg.NORMAL_VOICE_TRIGGER in user_lower:
        _cfg.PREFER_FAST_TTS = True
        log.info("Switched to normal voice mode (Groq Orpheus)")
        async def _normal_gen():
            yield f"data: {json.dumps({'type': 'start', 'intent': 'chat'})}\n\n"
            yield f"data: {json.dumps({'type': 'token', 'text': 'Switching to normal voice mode.'})}\n\n"
            yield f"data: {json.dumps({'type': 'done'})}\n\n"
        return StreamingResponse(_normal_gen(), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    # Voice auth — block sensitive intents + keyword-detected sensitive topics
    VOICE_SENSITIVE_INTENTS = {"vault", "shell", "email", "delete", "agent"}
    VOICE_SENSITIVE_KEYWORDS = {"vault", "password", "passwd", "credential", "secret", "sudo", "shell"}
    _is_sensitive = (intent in VOICE_SENSITIVE_INTENTS or
                     any(kw in user_lower for kw in VOICE_SENSITIVE_KEYWORDS))
    if _is_sensitive:
        log.info(f"Sensitive intent '{intent}' from voice — requiring confirmation")
        async def _sensitive_gen():
            yield f"data: {json.dumps({'type': 'start', 'intent': intent})}\n\n"
            yield f"data: {json.dumps({'type': 'token', 'text': 'This is a sensitive command. Please confirm by typing in the chat panel.'})}\n\n"
            yield f"data: {json.dumps({'type': 'done'})}\n\n"
        return StreamingResponse(_sensitive_gen(), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    # Track in conversation history
    add_to_history("user", user_input)

    async def event_generator():
        # FIX 3: Drain any leftover sentences from previous request
        try:
            from voice import _tts_queue, _tts_active
            import queue as _queue_module
            import time as _time
            # H8: Wait 500ms — give current sentence time to finish
            _time.sleep(0.5)
            # Now drain stale queue
            drained = 0
            while True:
                try:
                    _tts_queue.get_nowait()
                    _tts_queue.task_done()
                    drained += 1
                except _queue_module.Empty:
                    break
            if drained > 0:
                log.info(f"TTS queue flushed {drained} stale sentences")
            # Kill any active TTS
            _tts_active.clear()
            # Kill aplay and chatterbox if running (H1: use PID tracking)
            try:
                from voice import _aplay_pid, _aplay_pid_lock
                with _aplay_pid_lock:
                    pid = _aplay_pid
                if pid:
                    import os, signal
                    try:
                        os.kill(pid, signal.SIGTERM)
                        log.info(f"Killed aplay PID {pid}")
                    except (ProcessLookupError, OSError):
                        pass
                else:
                    import subprocess
                    subprocess.run(["pkill", "-f", "aplay"], capture_output=True)
            except Exception as e:
                log.warning(f"aplay kill error: {e}")
                import subprocess
                subprocess.run(["pkill", "-f", "aplay"], capture_output=True)
            # NOTE: Do NOT kill chatterbox_worker here — it holds the warm model in RAM.
            # Killing it forces 70s cold reload on next TTS call. Drain queue + kill aplay only.
        except Exception as e:
            log.warning(f"TTS flush error: {e}")
        
        try:
            log.info(f"🎙️ Voice respond: {user_input}")
            
            # FIX 7: Assign unique request ID and track it globally
            global _current_voice_request_id
            request_id = str(uuid.uuid4())[:8]
            with _voice_request_lock:
                _current_voice_request_id = request_id
            log.info(f"Voice request {request_id} started")

            # V12: Join previous TTS threads (2s grace) before clearing — prevents stale audio bleed
            for _prev_t in list(_active_tts_threads):
                _prev_t.join(timeout=2.0)
            _active_tts_threads.clear()
            
            yield f"data: {json.dumps({'type': 'start', 'intent': intent})}\n\n"
            full_reply = ""
            current_sentence = ""

            # Action intents: dispatch instead of chat_stream
            from intent_dispatch import INTENT_HANDLERS, dispatch as _dispatch
            ACTION_INTENTS = set(INTENT_HANDLERS.keys()) - {"chat", "lookup", "reason", "search"}
            if intent in ACTION_INTENTS:
                log.info(f"🎙️ Voice action intent '{intent}' — dispatching")
                _ctx = DispatchContext(
                    user_input=user_input, intent=intent, source="voice",
                    chat_fn=chat, chat_stream_fn=chat_stream,
                )
                _result = await asyncio.to_thread(_dispatch, _ctx)
                full_reply = _result if isinstance(_result, str) else str(_result)
                yield f"data: {json.dumps({'type': 'token', 'text': full_reply})}\n\n"
                add_to_history("assistant", full_reply)
                yield f"data: {json.dumps({'type': 'done'})}\n\n"
                return

            memory_context = _get_voice_memory_context(user_input)
            if memory_context:
                log.info(f"Voice memory context: {memory_context[:80]}")
            log.info(f"🎙️ Starting chat_stream...")

            # --- async search enrichment for voice path ---
            _enriched_voice_input = user_input
            try:
                import re as _vre
                from datetime import datetime, timezone, timedelta
                from search import web_search as _vws, format_results as _vfmt
                _VTEMPORAL = _vre.compile(
                    r"\b(who won|score|result|ipl|cricket|football|election|stock|"
                    r"price|match|latest|today|current|news|recent|now|happening|"
                    r"update|yesterday|tonight|who is|what happened)\b",
                    _vre.IGNORECASE
                )
                if intent in {"search", "lookup"} or _VTEMPORAL.search(user_input):
                    _vist = timezone(timedelta(hours=5, minutes=30))
                    _vnow = datetime.now(_vist)
                    _vsq = user_input
                    if not _vre.search(r'\b20\d{2}\b', user_input):
                        _vsq = f"Today is {_vnow.strftime('%A %B %d %Y')}, India IST. {user_input}"
                    _vr = await asyncio.to_thread(_vws, _vsq)
                    _vresults = _vr.value if _vr.ok else []
                    _vformatted = _vfmt(_vresults)
                    if _vformatted and "error" not in _vformatted.lower():
                        _enriched_voice_input = (
                            f"Web search results for '{user_input}':\n{_vformatted}\n\n"
                            f"Using the above results, answer: {user_input}"
                        )
                        log.info(f"Voice stream search enriched (async): {_vsq[:80]}")
            except Exception as _ve:
                log.warning(f"voice stream search enrichment failed: {_ve}")
            # --- end async search enrichment ---

            # H4: Start barge-in monitor BEFORE token loop
            def _on_barge_in():
                log.info("Barge-in detected — stopping TTS, restarting listen")
                _barge_in_triggered.set()
                _restart_listen.set()
                try:
                    from voice import _tts_queue, _tts_active, _aplay_pid, _aplay_pid_lock
                    import queue as _q
                    _tts_active.clear()
                    while True:
                        try:
                            _tts_queue.get_nowait()
                            _tts_queue.task_done()
                        except _q.Empty:
                            break
                    _tts_queue.put(None)
                    # H1: Kill aplay by PID
                    with _aplay_pid_lock:
                        pid = _aplay_pid
                    if pid:
                        import os, signal
                        try:
                            os.kill(pid, signal.SIGTERM)
                            log.info(f"Killed aplay PID {pid}")
                        except (ProcessLookupError, OSError):
                            pass
                    else:
                        import subprocess
                        subprocess.run(["pkill", "-f", "aplay"],
                                      capture_output=True)
                except Exception as e:
                    log.warning(f"Barge-in TTS kill error: {e}")
            
            try:
                from voice import start_barge_in_monitor
                start_barge_in_monitor(_on_barge_in)
                log.info("Barge-in monitor started before first token")
            except Exception as e:
                log.warning(f"Barge-in start error: {e}")

            for token in chat_stream(_enriched_voice_input, intent=intent):
                full_reply += token
                current_sentence += token
                log.debug(f"🎙️ Token: {len(token)} chars")
                yield f"data: {json.dumps({'type': 'token', 'text': token})}\n\n"
                
                # Check for sentence boundaries: . ! ? : ; or 4+ chars minimum
                stripped = current_sentence.strip()
                if re.search(r'[.!?:;]\s*$', stripped):
                    if len(stripped) >= 4 or stripped in ("Done.", "Yes.", "No.", "Ok.", "Sure.", "Got it."):
                        # FIX 7: Wrapper to skip stale TTS from old requests
                        def _speak_if_current(s=current_sentence.strip(), rid=request_id):
                            with _voice_request_lock:
                                if _current_voice_request_id != rid:
                                    log.info(f"Skipping stale TTS from request {rid}")
                                    return
                            try:
                                from voice import speak_sentence as vs
                                vs(s)
                            except Exception as e:
                                log.warning(f"Sentence TTS error: {e}")
                        _tts_t = threading.Thread(target=_speak_if_current, daemon=True)
                        _tts_t.start()
                        _active_tts_threads.append(_tts_t)
                    current_sentence = ""
            
            # Flush any trailing sentence fragment not caught by punctuation check
            if current_sentence.strip() and len(current_sentence.strip()) >= 4:
                def _speak_tail(s=current_sentence.strip(), rid=request_id):
                    with _voice_request_lock:
                        if _current_voice_request_id != rid:
                            return
                    try:
                        from voice import speak_sentence as vs
                        vs(s)
                    except Exception as e:
                        log.warning(f"Tail TTS error: {e}")
                _tts_t = threading.Thread(target=_speak_tail, daemon=True)
                _tts_t.start()
                _active_tts_threads.append(_tts_t)
                current_sentence = ""

            # Track response in conversation history
            add_to_history("assistant", full_reply)

            log.info(f"🎙️ Stream done: {len(full_reply)} chars")
            
            # UPGRADE B: Send TTS engine info for orb color
            tts_engine = "piper"
            try:
                from config import USE_GROQ_TTS, USE_CHATTERBOX, PREFER_FAST_TTS
                if USE_GROQ_TTS and PREFER_FAST_TTS:
                    tts_engine = "groq"
                elif USE_CHATTERBOX:
                    tts_engine = "chatterbox"
            except Exception:
                pass
            yield f"data: {json.dumps({'type': 'tts_engine', 'engine': tts_engine})}\n\n"
            yield f"data: {json.dumps({'type': 'done'})}\n\n"
            # V8: if barge-in fired during this response, tell frontend to re-enter listen state
            if _restart_listen.is_set():
                _restart_listen.clear()
                log.info("Barge-in triggered relisten — notifying frontend")
                yield f"data: {json.dumps({'type': 'relisten'})}\n\n"
        except Exception as e:
            log.error(f"Voice respond error: {e}", exc_info=True)
            yield f"data: {json.dumps({'type': 'error', 'message': str(e)})}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.post("/api/voice/mic-lock")
async def mic_lock_endpoint():
    """Browser mic activated — set MIC_IN_USE CrossProcessEvent to block wake_listener."""
    try:
        from voice import MIC_IN_USE
        MIC_IN_USE.set()
        import wake_listener as _wl
        _wl.pause()
    except Exception as e:
        log.warning(f"mic-lock error: {e}")
    return {"status": "locked"}


@app.post("/api/voice/mic-unlock")
async def mic_unlock_endpoint():
    """Browser mic released — clear MIC_IN_USE CrossProcessEvent."""
    try:
        from voice import MIC_IN_USE
        MIC_IN_USE.clear()
        import wake_listener as _wl
        _wl.resume()
    except Exception as e:
        log.warning(f"mic-unlock error: {e}")
    return {"status": "unlocked"}


@app.post("/api/voice/warmup-chatterbox")
async def warmup_chatterbox_endpoint():
    """Spawn Chatterbox worker the moment mic activates — absorbs 70s cold-start before TTS needed."""
    def _warmup():
        try:
            from config import USE_CHATTERBOX
            if not USE_CHATTERBOX:
                return
            from voice import _get_chatterbox_worker
            _get_chatterbox_worker()
            log.info("Chatterbox worker warmed up via mic-activate trigger")
        except Exception as e:
            log.warning(f"Chatterbox warmup error: {e}")
    import threading as _threading
    _threading.Thread(target=_warmup, daemon=True, name="chatterbox-warmup").start()
    return {"status": "warming"}


@app.post("/api/voice/stop-tts")
async def stop_tts_endpoint():
    """FIX 6: Aggressive TTS kill — drain queue, kill worker, kill processes."""
    def _kill_all_tts():
        try:
            import queue as _q
            from voice import (
                _tts_queue,
                _tts_active,
                _tts_worker_thread
            )
            import subprocess
            
            # Step 1: Signal stop
            _tts_active.clear()
            
            # Step 2: Drain entire queue
            drained = 0
            while True:
                try:
                    _tts_queue.get_nowait()
                    _tts_queue.task_done()
                    drained += 1
                except _q.Empty:
                    break
            
            # Step 3: Put poison pill to kill worker
            _tts_queue.put(None)
            
            # Step 4: Kill audio processes (H1: use PID tracking)
            try:
                from voice import _aplay_pid, _aplay_pid_lock
                with _aplay_pid_lock:
                    pid = _aplay_pid
                if pid:
                    import os, signal
                    try:
                        os.kill(pid, signal.SIGTERM)
                        log.info(f"Killed aplay PID {pid}")
                    except (ProcessLookupError, OSError):
                        pass
                else:
                    subprocess.run(
                        ["pkill", "-f", "aplay"],
                        capture_output=True,
                        timeout=2
                    )
            except Exception as e:
                log.warning(f"aplay kill error: {e}")
                subprocess.run(
                    ["pkill", "-f", "aplay"],
                    capture_output=True,
                    timeout=2
                )
            # Do NOT kill chatterbox_worker — preserve warm model in RAM for next TTS call.
            log.info(f"TTS killed: drained {drained} sentences")
            
        except Exception as e:
            log.warning(f"TTS kill error: {e}")
    
    threading.Thread(target=_kill_all_tts, daemon=True).start()
    return {"status": "ok", "message": "TTS stopped"}


def _track_widget_msg(content, role, intent):
    """Track messages for multi-turn context."""
    with _widget_history_lock:
        msg_id = len(_widget_history)
        _widget_history[msg_id] = {"role": role, "content": content, "intent": intent}
        while len(_widget_history) > _MAX_WIDGET_HISTORY * 2:
            oldest = next(iter(_widget_history))
            del _widget_history[oldest]


def _persist_exchange(user_msg: str, assistant_msg: str, session_id: str = None) -> str:
    """Persist a user+assistant exchange to conversation_json in sessions table. Returns used session_id."""
    try:
        from session import get_session_id, start_session as _start_session
        import time
        session_id = session_id or get_session_id()
        if not session_id or session_id == "unknown":
            session_id = _start_session("web")
        _db = os.path.join(os.path.dirname(os.path.abspath(__file__)), "session_state.db")
        import sqlite3 as _sqlite3
        conn = _sqlite3.connect(_db)
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


def _handle_followup(user_input, fu_type):
    """Handle a follow-up message using context from the previous exchange."""
    last_user, last_bot = _get_last_exchange()

    if fu_type == "call_followup":
        number = _extract_phone_number(user_input.strip())
        if number:
            from phone import initiate_call
            initiate_call(number)
            return f"📞 Calling {number} now.", "call"
        return "That doesn't look like a valid number, Boss. Give me something like +919305819663.", "call"

    elif fu_type == "sms_followup":
        from phone import send_sms
        original_msg = last_user.get("content", "") if last_user else ""
        body = _extract_sms_body(original_msg)
        if not body:
            m = re.search(r"(?:say|saying|text|send)\s+(.+)", original_msg, re.IGNORECASE)
            body = m.group(1).strip() if m else "hi"
        number = _extract_phone_number(user_input.strip())
        if number:
            send_sms(number, body)
            return f'📱 SMS sent to {number}: "{body}"', "sms"
        return "That doesn't look like a valid number, Boss. Try: +91XXXXXXXXXX", "sms"

    elif fu_type == "self_improve_accept":
        from life_os import add_open_loop
        proposal = last_bot.get("content", "")[:200] if last_bot else "last proposal"
        add_open_loop(f"Implement upgrade: {proposal[:100]}")
        return "✅ Got it, Boss. I've added this upgrade proposal to your open loops for implementation.", "self_improve"

    elif fu_type == "confirmation":
        context = f"Previous: {last_bot.get('content', '')[:200]}\nUser follow-up: {user_input}"
        return chat(context, intent="chat"), "chat"

    elif fu_type == "search_followup":
        context = last_bot.get("content", "") if last_bot else ""
        return chat(f"Previous answer: {context[:500]}\n\nUser follow-up: {user_input}", intent="search"), "search"

    elif fu_type == "clarification":
        context = last_bot.get("content", "") if last_bot else ""
        prev_intent = last_user.get("intent", "chat") if last_user else "chat"
        return chat(f"Previous: {context[:500]}\n\nUser follow-up: {user_input}", intent=prev_intent), prev_intent

    return chat(user_input, intent="chat"), "chat"


# ────────────────────────────────────────────────────
# Memory Monitor
# ────────────────────────────────────────────────────
def _memory_monitor():
    """Background thread to monitor and prevent memory leaks."""
    import time
    process = psutil.Process(os.getpid())
    while True:
        try:
            time.sleep(300)
            memory_info = process.memory_info()
            memory_mb = memory_info.rss / 1024 / 1024
            log.info(f"Memory usage: {memory_mb:.2f} MB")
            if memory_mb > 500:
                log.warning(f"High memory usage ({memory_mb:.2f} MB). Running GC.")
                gc.collect()
                memory_mb = process.memory_info().rss / 1024 / 1024
                log.info(f"After GC: {memory_mb:.2f} MB")
        except Exception as e:
            log.error(f"Memory monitor error: {e}")


# ────────────────────────────────────────────────────
# Phase 6 API Endpoints
# ────────────────────────────────────────────────────
import asyncio
import datetime as _dt

# FIX 7: Request ID tracking to prevent stale TTS
_current_voice_request_id = None
_voice_request_lock = threading.Lock()

# V8: Barge-in signal — set when user interrupts, cleared by /api/voice/barge-in-complete
_barge_in_triggered = threading.Event()
# V8: Relisten flag — set by _on_barge_in to tell SSE generator to emit 'relisten' event
_restart_listen = threading.Event()

# V12: Track TTS threads so new request can join/cancel previous
_active_tts_threads: list = []

@app.get("/api/health-check")
async def api_health_check():
    """Run full system validation and return health report as JSON."""
    from validator import validate_all
    results = validate_all(emit_events=False)
    return results


@app.get("/api/system-status")
async def api_status_legacy():
    """Legacy redirect to combined /api/status. Included for backwards compatibility."""
    from fastapi.responses import RedirectResponse
    return RedirectResponse(url="/api/status")

@app.get("/api/recent_traces")
async def api_recent_traces(limit: int = 20):
    """Return last N routing traces from the archive DB."""
    import sqlite3 as _sql
    from config import MEMORY_ARCHIVE_PATH
    def _fetch():
        try:
            conn = _sql.connect(MEMORY_ARCHIVE_PATH)
            cur = conn.cursor()
            cur.execute("""
                SELECT * FROM (
                    SELECT provider, date, call_count FROM api_usage
                ) LIMIT ?
            """, (limit,))
            rows = [{"provider": r[0], "date": r[1], "call_count": r[2]} for r in cur.fetchall()]
            conn.close()
            return rows
        except Exception:
            return []
    traces = await asyncio.to_thread(_fetch)
    return {"traces": traces}


@app.get("/api/monitor_schedule")
async def api_monitor_schedule():
    """Return last maintenance timestamps + static schedule."""
    from monitor import _load_maintenance_state
    state = await asyncio.to_thread(_load_maintenance_state)
    return {
        "last_maintenance": state.get("last_maintenance"),
        "last_backup": state.get("last_backup"),
        "static_schedule": [
            {"time": "02:30", "job": "Idle Memory Consolidation", "freq": "daily"},
            {"time": "03:00", "job": "Nightly Backup + Cleanup", "freq": "daily"},
            {"time": "07:00", "job": "Weather Pre-fetch", "freq": "daily"},
            {"time": "08:00", "job": "Daily Report Pre-fetch", "freq": "daily"},
            {"time": "12:00", "job": "Graph Triple Extraction", "freq": "daily"},
            {"freq": "every 5m", "job": "KDE Connect Heartbeat"},
            {"freq": "every 10m", "job": "Proactive Checks"},
            {"time": "21:00", "job": "Weekly Briefing Prep", "freq": "sunday"},
        ],
    }


@app.post("/api/feedback")
async def api_feedback(req: Request):
    """Tag a trace with thumbs_up / thumbs_down feedback."""
    data = await req.json()
    trace_id = data.get("trace_id", "")
    feedback = data.get("feedback", "")
    if not trace_id or feedback not in ("thumbs_up", "thumbs_down"):
        return {"ok": False, "error": "trace_id and valid feedback (thumbs_up|thumbs_down) required"}
    import sqlite3 as _sql
    from config import MEMORY_ARCHIVE_PATH
    def _tag():
        try:
            conn = _sql.connect(MEMORY_ARCHIVE_PATH)
            cur = conn.cursor()
            cur.execute("""
                CREATE TABLE IF NOT EXISTS feedback (
                    trace_id TEXT PRIMARY KEY,
                    feedback TEXT,
                    reason TEXT,
                    created_at TEXT
                )
            """)
            cur.execute("""
                INSERT OR REPLACE INTO feedback (trace_id, feedback, reason, created_at)
                VALUES (?, ?, ?, ?)
            """, (trace_id, feedback, data.get("reason", ""), _dt.datetime.now().isoformat()))
            conn.commit()
            conn.close()
            # Also tag via feedback_tagger so tuner can read it
            try:
                from feedback_tagger import tag_feedback
                tag_feedback(trace_id, feedback, data.get("reason", ""))
            except Exception as e:
                log.debug(f"feedback_tagger.tag_feedback failed (non-fatal): {e}")
            return True
        except Exception as e:
            log.error(f"Feedback tag failed: {e}")
            return False
    ok = await asyncio.to_thread(_tag)
    return {"ok": ok}


# ────────────────────────────────────────────────────
# Dashboard Route
# ────────────────────────────────────────────────────
@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard():
    try:
        with open(_DASHBOARD_HTML_PATH, 'r') as f:
            return f.read()
    except Exception as e:
        return HTMLResponse(f"<h1>UI error: {e}</h1>", status_code=500)


# ────────────────────────────────────────────────────
# New Dashboard API Endpoints
# ────────────────────────────────────────────────────

@app.get("/api/costs")
async def api_costs():
    """J4 — return last 7 days of API call costs grouped by provider."""
    try:
        import time as _t, db_pool
        from config import MEMORY_ARCHIVE_PATH
        from smart_router import _daily_calls, DAILY_LIMITS
        since = _t.time() - 7 * 86400
        with db_pool.connection(MEMORY_ARCHIVE_PATH) as conn:
            rows = conn.execute(
                "SELECT provider, SUM(input_tokens_est), SUM(output_tokens_est), COUNT(*) FROM api_costs WHERE timestamp > ? GROUP BY provider",
                (since,)
            ).fetchall()
        result = {}
        for provider, tin, tout, calls in rows:
            daily = _daily_calls.get(provider, 0)
            limit = DAILY_LIMITS.get(provider, 9999)
            result[provider] = {
                "calls_7d": calls,
                "input_tokens_est": tin or 0,
                "output_tokens_est": tout or 0,
                "cost_usd_est": 0.0,
                "today_calls": daily,
                "daily_limit": limit,
                "near_limit": daily >= limit * 0.8,
            }
        return result
    except Exception as e:
        return {"error": str(e)}


@app.get("/api/provider-latencies")
async def api_provider_latencies():
    """Return latest per-provider latency (seconds) from smart_router."""
    try:
        from smart_router import _provider_latencies
        return _provider_latencies
    except Exception as e:
        return {"error": str(e)}


@app.get("/api/stats")
async def api_stats_proxy():
    """Proxy to dashboard stats — serves dashboard.py data from port 8001."""
    try:
        import dashboard as _dash
        return await asyncio.to_thread(lambda: {
            "system": _dash.get_system_stats(),
            "model": _dash.get_active_model(),
            "models": _dash.get_ollama_models(),
            "logs": _dash.get_recent_logs(),
            "modules": _dash.get_edith_modules(),
            "mcp": _dash.get_mcp_status(),
            "time": __import__("datetime").datetime.now().strftime("%H:%M:%S"),
            "date": __import__("datetime").datetime.now().strftime("%A, %d %B %Y"),
        })
    except Exception as e:
        log.error(f"api/stats proxy error: {e}")
        return {"error": str(e)}


@app.get("/api/status")
async def api_status_combined():
    """Combined system, active provider, Ollama state, and circuit breaker status."""
    try:
        from circuit_breaker import get_all_status, check_ollama_health
        from smart_router import _daily_calls, DAILY_LIMITS, _has_key, _is_provider_cooled_down, _is_under_daily_limit
        from monitor import check_ram, check_disk, check_cpu

        res = await asyncio.to_thread(check_ollama_health)
        ollama_up = res.ok if hasattr(res, 'ok') else res
        
        cb_states = get_all_status()

        sys_data = await asyncio.to_thread(lambda: {
            "ram": check_ram(),
            "disk": check_disk(),
            "cpu": check_cpu(),
        })

        providers = {}
        for p in ["groq", "gemini", "nvidia", "openrouter", "ollama"]:
            providers[p] = {
                "has_key": _has_key(p),
                "cooled_down": _is_provider_cooled_down(p),
                "under_limit": _is_under_daily_limit(p),
                "daily_calls": _daily_calls.get(p, 0),
                "daily_limit": DAILY_LIMITS.get(p, 999),
                "circuit": cb_states.get(p, {}).get("state", "CLOSED"),
            }

        active_provider = "ollama"
        for p in ["groq", "gemini", "nvidia", "openrouter", "ollama"]:
            if providers[p]["has_key"] and providers[p]["cooled_down"] and providers[p]["under_limit"] and providers[p]["circuit"] != "OPEN":
                active_provider = p
                break

        from search import get_search_status
        return {
            "system": sys_data,
            "active_provider": active_provider,
            "ollama_running": ollama_up,
            "circuit_breakers": cb_states,
            "providers": providers,
            "search_providers": get_search_status(),
            "timestamp": _dt.datetime.now().isoformat(),
        }
    except Exception as e:
        log.error(f"Status API failed: {e}")
        return {"error": str(e)}


@app.get("/api/voice-status")
async def api_voice_status():
    """Return current voice mode (normal, private) and TTS engine color."""
    try:
        from voice import get_last_intent
        from config import PRIVATE_INTENTS, USE_GROQ_TTS, USE_CHATTERBOX
        
        last_intent = get_last_intent()
        is_private = last_intent in PRIVATE_INTENTS if last_intent else False
        
        tts_engine = "piper"
        if USE_CHATTERBOX:
            tts_engine = "chatterbox"
        elif USE_GROQ_TTS:
            tts_engine = "groq"
        
        tts_colors = {
            "chatterbox": "#ff6b35",
            "groq": "#00d4ff",
            "piper": "#4ecdc4",
        }
        
        return {
            "mode": "private" if is_private else "normal",
            "tts_engine": tts_engine,
            "tts_color": tts_colors.get(tts_engine, "#4ecdc4"),
            "timestamp": _dt.datetime.now().isoformat(),
        }
    except Exception as e:
        log.error(f"Voice status API failed: {e}")
        return {"mode": "normal", "tts_engine": "piper", "error": str(e)}


@app.post("/api/voice/barge-in-complete")
async def api_barge_in_complete():
    """Clear barge-in trigger — called by dashboard JS to re-enable mic button."""
    _barge_in_triggered.clear()
    return {"status": "ok", "barge_in_active": False}


@app.get("/api/voice/barge-in-status")
async def api_barge_in_status():
    """Poll endpoint — returns whether barge-in was triggered."""
    return {"barge_in_triggered": _barge_in_triggered.is_set()}


@app.get("/api/last-memory")
async def api_last_memory():
    """Return last 3 memories from SmartMemoryManager."""
    try:
        from config import MEMORY_ARCHIVE_PATH
        import sqlite3 as _sql

        def _fetch():
            conn = _sql.connect(MEMORY_ARCHIVE_PATH)
            cur = conn.cursor()
            cur.execute(
                "SELECT key, value, timestamp FROM memories ORDER BY timestamp DESC LIMIT 3"
            )
            rows = [{"key": r[0], "value": r[1], "timestamp": r[2]} for r in cur.fetchall()]
            conn.close()
            return rows

        memories = await asyncio.to_thread(_fetch)
        return {"memories": memories}
    except Exception as e:
        return {"error": str(e), "memories": []}


@app.get("/api/phone")
async def api_phone():
    """KDE Connect battery + last notification. Returns offline if unavailable."""
    try:
        from phone import get_battery, get_notifications, phone_status

        def _fetch():
            battery_raw = get_battery()
            notifs_raw = get_notifications()
            status = phone_status()
            return battery_raw, notifs_raw, status

        battery_raw, notifs_raw, status = await asyncio.to_thread(_fetch)

        if "not connected" in status.lower() or "not installed" in status.lower() or "unavailable" in status.lower():
            return {"battery": None, "status": "offline", "last_notification": None}

        import re as _re
        battery_match = _re.search(r"(\d+)", battery_raw or "")
        battery = int(battery_match.group(1)) if battery_match else None

        notif_lines = [l.strip() for l in (notifs_raw or "").splitlines() if l.strip()]
        last_notif = notif_lines[0] if notif_lines else None

        return {"battery": battery, "status": "online", "last_notification": last_notif}
    except Exception as e:
        return {"battery": None, "status": "offline", "last_notification": None, "error": str(e)}


@app.get("/api/weather-status")
async def api_weather_status():
    """Return current weather from weather.py get_current_weather()."""
    try:
        from weather import get_current_weather
        result = await asyncio.to_thread(get_current_weather)
        if result is None:
            return {"error": "Weather unavailable"}
        return result
    except Exception as e:
        return {"error": str(e)}


@app.get("/api/traces/recent")
async def api_traces_recent(limit: int = 20):
    """Return last 20 traces from trace_log.db."""
    try:
        from config import EDITH_PATH
        import sqlite3 as _sql

        _trace_db = os.path.join(EDITH_PATH, "trace_log.db")

        def _fetch():
            if not os.path.exists(_trace_db):
                return []
            conn = _sql.connect(_trace_db)
            cur = conn.cursor()
            cur.execute(
                "SELECT trace_id, user_input, intent, created_at, final_status, total_layers "
                "FROM trace_index ORDER BY created_at DESC LIMIT ?",
                (limit,)
            )
            rows = [
                {
                    "trace_id": r[0],
                    "user_input": r[1],
                    "intent": r[2],
                    "created_at": r[3],
                    "final_status": r[4],
                    "total_layers": r[5],
                }
                for r in cur.fetchall()
            ]
            conn.close()
            return rows

        traces = await asyncio.to_thread(_fetch)
        return {"traces": traces}
    except Exception as e:
        return {"error": str(e), "traces": []}


@app.get("/api/logs/stream")
async def api_logs_stream():
    """SSE endpoint tailing edith.log. Sends last 100 lines on connect then streams new ones."""
    from config import EDITH_PATH as _EDITH_PATH
    log_path = os.path.join(_EDITH_PATH, "logs", "edith.log")

    async def _generate():
        try:
            if os.path.exists(log_path):
                with open(log_path, "r") as f:
                    lines = f.readlines()
                    for line in lines[-100:]:
                        yield f"data: {line.rstrip()}\n\n"

            with open(log_path, "a+") as _:
                pass

            import time as _time
            last_size = os.path.getsize(log_path) if os.path.exists(log_path) else 0
            while True:
                await asyncio.sleep(0.5)
                if not os.path.exists(log_path):
                    continue
                cur_size = os.path.getsize(log_path)
                if cur_size > last_size:
                    with open(log_path, "r") as f:
                        f.seek(last_size)
                        new_lines = f.read()
                    last_size = cur_size
                    for line in new_lines.splitlines():
                        if line.strip():
                            yield f"data: {line}\n\n"
        except Exception as e:
            yield f"data: [LOG_ERROR] {e}\n\n"

    return StreamingResponse(_generate(), media_type="text/event-stream")


# ────────────────────────────────────────────────────
# MCP API Endpoints
# ────────────────────────────────────────────────────

@app.get("/api/mcp/status")
async def api_mcp_status():
    """Return enabled/disabled status, tool count, and last_called for all MCP servers."""
    try:
        import mcp_bridge
        status = await asyncio.to_thread(mcp_bridge.get_mcp_status)
        return status
    except Exception as e:
        log.error(f"MCP status error: {e}")
        return {"error": str(e)}


@app.get("/api/mcp/tools/{server_name}")
async def api_mcp_tools(server_name: str):
    """Return list of available tools for a named MCP server."""
    try:
        import mcp_bridge
        tools = await asyncio.to_thread(mcp_bridge.list_mcp_tools, server_name)
        return {"server": server_name, "tools": tools}
    except Exception as e:
        log.error(f"MCP tools error [{server_name}]: {e}")
        return {"server": server_name, "tools": [], "error": str(e)}


@app.post("/api/mcp/call")
async def api_mcp_call(req: Request):
    """Call a tool on an MCP server. Body: {server, tool, arguments}."""
    denied = _check_mcp_admin(req)
    if denied:
        return denied
    data = await req.json()
    server = data.get("server", "")
    tool = data.get("tool", "")
    arguments = data.get("arguments", {})
    if not server or not tool:
        return {"error": "server and tool fields required"}
    try:
        import mcp_bridge
        result = await asyncio.to_thread(
            mcp_bridge.call_mcp_server, server, tool, arguments
        )
        return {"result": result, "server": server, "tool": tool}
    except Exception as e:
        log.error(f"MCP call error [{server}/{tool}]: {e}")
        return {"result": None, "server": server, "tool": tool, "error": str(e)}


@app.get("/api/mcp/config")
async def api_mcp_config_get():
    """Return full mcp_config.json contents."""
    try:
        import mcp_bridge
        cfg = await asyncio.to_thread(mcp_bridge._load_config)
        return cfg
    except Exception as e:
        log.error(f"MCP config get error: {e}")
        return {"error": str(e)}


@app.post("/api/mcp/config/add")
async def api_mcp_config_add(req: Request):
    """Add or update an MCP server. Body: {name, command, args, env_vars, description, allowed_intents, enabled}."""
    denied = _check_mcp_admin(req)
    if denied:
        return denied
    data = await req.json()
    name = data.get("name", "").strip()
    command = data.get("command", "").strip()
    if not name or not command:
        return {"ok": False, "error": "name and command required"}
    try:
        import mcp_bridge
        cfg = mcp_bridge._load_config()
        cfg.setdefault("servers", {})[name] = {
            "enabled": data.get("enabled", False),
            "command": command,
            "args": data.get("args", []),
            "description": data.get("description", ""),
            "allowed_intents": data.get("allowed_intents", ["mcp"]),
            "env_vars": data.get("env_vars", {}),
        }
        await asyncio.to_thread(mcp_bridge.save_config, cfg)
        return {"ok": True, "name": name}
    except Exception as e:
        log.error(f"MCP config add error: {e}")
        return {"ok": False, "error": str(e)}


@app.post("/api/mcp/config/toggle/{server_name}")
async def api_mcp_config_toggle(server_name: str, req: Request):
    """Toggle enabled/disabled for a named server."""
    denied = _check_mcp_admin(req)
    if denied:
        return denied
    try:
        import mcp_bridge
        cfg = mcp_bridge._load_config()
        servers = cfg.get("servers", {})
        if server_name not in servers:
            return {"ok": False, "error": f"Server '{server_name}' not found"}
        servers[server_name]["enabled"] = not servers[server_name].get("enabled", False)
        new_state = servers[server_name]["enabled"]
        await asyncio.to_thread(mcp_bridge.save_config, cfg)
        return {"ok": True, "name": server_name, "enabled": new_state}
    except Exception as e:
        log.error(f"MCP toggle error [{server_name}]: {e}")
        return {"ok": False, "error": str(e)}


@app.delete("/api/mcp/config/remove/{server_name}")
async def api_mcp_config_remove(server_name: str, req: Request):
    """Remove an MCP server entry from config."""
    denied = _check_mcp_admin(req)
    if denied:
        return denied
    try:
        import mcp_bridge
        cfg = mcp_bridge._load_config()
        servers = cfg.get("servers", {})
        if server_name not in servers:
            return {"ok": False, "error": f"Server '{server_name}' not found"}
        del servers[server_name]
        await asyncio.to_thread(mcp_bridge.save_config, cfg)
        return {"ok": True, "removed": server_name}
    except Exception as e:
        log.error(f"MCP remove error [{server_name}]: {e}")
        return {"ok": False, "error": str(e)}


# ══════════════════════════════════════════════════════════════
# O6: Webhook Triggers — receive push events from external services
# ══════════════════════════════════════════════════════════════

_WEBHOOK_TOKEN = os.getenv("EDITH_WEBHOOK_TOKEN", "")

def _verify_webhook(req: Request) -> bool:
    """Verify webhook via X-Webhook-Token header (skip if token not configured)."""
    if not _WEBHOOK_TOKEN:
        return True
    return req.headers.get("X-Webhook-Token", "") == _WEBHOOK_TOKEN


@app.post("/webhook/{source}")
async def webhook_trigger(source: str, req: Request):
    """
    O6: Push-event webhook. source = github | telegram | calendar | generic.
    Body: {"event": "push", "message": "...", "payload": {...}}
    Routes through EDITH orchestrator as channel source='webhook'.
    Set EDITH_WEBHOOK_TOKEN env var to require auth.
    """
    if not _verify_webhook(req):
        return JSONResponse(status_code=401, content={"ok": False, "error": "Unauthorized"})

    allowed_sources = {"github", "telegram", "calendar", "generic", "alert"}
    if source not in allowed_sources:
        return JSONResponse(status_code=400, content={"ok": False, "error": f"Unknown source '{source}'"})

    try:
        body = await req.json()
    except Exception:
        body = {}

    event   = body.get("event", "push")
    message = body.get("message", "")
    payload = body.get("payload", {})

    # Build a natural-language description EDITH can act on
    if not message:
        if source == "github":
            repo   = payload.get("repository", {}).get("full_name", "unknown repo")
            ref    = payload.get("ref", "")
            pusher = payload.get("pusher", {}).get("name", "someone")
            message = f"GitHub {event} on {repo} ({ref}) by {pusher}"
        elif source == "calendar":
            message = f"Calendar event: {payload.get('summary', event)}"
        elif source == "alert":
            message = f"Alert [{event}]: {payload.get('text', json.dumps(payload)[:200])}"
        else:
            message = f"Webhook event from {source}: {event}"

    log.info(f"[webhook/{source}] {event}: {message[:100]}")

    def _process():
        from orchestrator import chat
        return chat(message, intent="chat", source="webhook")

    try:
        reply = await asyncio.to_thread(_process)
    except Exception as e:
        log.error(f"Webhook processing error: {e}")
        reply = f"[EDITH] Webhook received but processing failed: {e}"

    # If Telegram is configured, push the reply back
    try:
        from telegram_bot import send_message as _tg_send
        await asyncio.to_thread(_tg_send, f"[{source.upper()} webhook]\n{message}\n\n{reply}")
    except Exception:
        pass

    return {"ok": True, "source": source, "event": event, "reply": reply}


@app.post("/tg_webhook")
async def tg_webhook(req: Request):
    """
    Telegram Bot API webhook endpoint.
    nginx maps /<BOT_TOKEN> → http://127.0.0.1:8001/tg_webhook.
    Only active on cloud node (EDITH_NODE_TYPE=cloud).
    """
    if os.getenv("EDITH_NODE_TYPE", "local") != "cloud":
        return JSONResponse(status_code=403, content={"ok": False, "error": "Webhook only active on cloud node"})
    try:
        update = await req.json()
    except Exception:
        return JSONResponse(status_code=400, content={"ok": False})
    try:
        from telegram_bot import handle_telegram_update
        await asyncio.to_thread(handle_telegram_update, update)
    except Exception as e:
        log.error(f"tg_webhook handler error: {e}")
    return {"ok": True}


def _graceful_shutdown():
    """Flush memories on shutdown."""
    log.info("Graceful shutdown initiated — flushing data...")
    try:
        import threading
        from devlog import _sync_to_simplenote
        _t = threading.Thread(target=_sync_to_simplenote, daemon=True)
        _t.start()
        _t.join(timeout=3.0)
    except Exception as e:
        log.error(f"DevLog flush failed: {e}")
        
    try:
        from config import get_chroma_client
        client = get_chroma_client()
        # Chroma V0.4+ doesn't require persist() but older clients might
        if hasattr(client, 'persist'):
            client.persist()
    except Exception:
        pass
        
    try:
        from session import _persist_session
        _persist_session()
    except Exception as e:
        log.error(f"Session save failed: {e}")


# ══════════════════════════════════════════════════════════════
# DEV PANEL API
# ══════════════════════════════════════════════════════════════
import glob as _glob
import asyncio as _asyncio
import urllib.request as _urlreq
import json as _json2

_EDITH_DIR          = os.path.expanduser("~/EDITH")
_MAX_CHARS_PER_FILE = 4000
_MAX_FILES          = 8

_SYSTEM_QA = (
    "You are EDITH's self-awareness module with full access to her source code. "
    "Answer architecture and development questions accurately and concisely. "
    "Reference specific function names, classes, and line details when relevant."
)

_SYSTEM_COUNCIL = """You are EDITH's Council of Minds. Four internal personas analyse the question and debate.

STRATEGIST — long-term architecture, scalability, design principles
CRITIC      — flaws, edge cases, tech debt, failure modes
BUILDER     — concrete next steps, exact code actions needed
FUTURIST    — ambitious possibilities, what EDITH could become

Respond in this exact format (no preamble):
STRATEGIST: <2-3 sentences>
CRITIC: <2-3 sentences>
BUILDER: <2-3 sentences>
FUTURIST: <2-3 sentences>
CONSENSUS: <1-2 sentences final verdict>"""

_SYSTEM_NEXT = (
    "You are EDITH's self-awareness module. Based on the provided codebase, "
    "identify the single most impactful next thing to build. "
    "Be specific: module name, key functions to write, why it matters most right now. "
    "No generic advice — ground everything in the actual code provided."
)


@app.get("/api/devpanel/modules")
async def devpanel_modules():
    modules = []
    for fp in sorted(_glob.glob(os.path.join(_EDITH_DIR, "*.py"))):
        name = os.path.basename(fp)
        try:
            with open(fp) as fh:
                lines = sum(1 for _ in fh)
        except Exception:
            lines = 0
        modules.append({"name": name, "lines": lines})
    return {"modules": modules}


@app.post("/api/devpanel/query")
async def devpanel_query(req: Request):
    body  = await req.json()
    query = body.get("query", "").strip()
    mode  = body.get("mode", "qa")
    files = body.get("files", [])[:_MAX_FILES]

    if not query:
        return {"error": "Empty query."}

    ctx_parts = []
    for fname in files:
        fp = os.path.join(_EDITH_DIR, fname)
        if not os.path.abspath(fp).startswith(_EDITH_DIR):
            continue
        try:
            with open(fp) as fh:
                raw = fh.read()[:_MAX_CHARS_PER_FILE]
            ctx_parts.append(f"=== {fname} ===\n{raw}")
        except Exception:
            pass

    context = "\n\n".join(ctx_parts) if ctx_parts else "(no files loaded)"
    system  = {"qa": _SYSTEM_QA, "council": _SYSTEM_COUNCIL, "next": _SYSTEM_NEXT}.get(mode, _SYSTEM_QA)

    full_msg = f"[SYSTEM ROLE]\n{system}\n\n[CODEBASE CONTEXT]\n{context}\n\n[QUESTION]\n{query}"

    def _call():
        payload = _json2.dumps({"message": full_msg}).encode()
        rq = _urlreq.Request(
            "http://localhost:8001/api/chat",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST"
        )
        with _urlreq.urlopen(rq, timeout=90) as r:
            return _json2.loads(r.read())

    try:
        data   = await _asyncio.get_event_loop().run_in_executor(None, _call)
        answer = data.get("reply") or data.get("response") or data.get("message") or str(data)
    except Exception as e:
        answer = f"[ERROR — could not reach chat endpoint]\n{type(e).__name__}: {e}"

    return {"response": answer}


# ────────────────────────────────────────────────────
# Session History Endpoints
# ────────────────────────────────────────────────────

@app.get("/api/sessions")
async def get_sessions():
    try:
        import sqlite3 as _sq
        from datetime import date, timedelta
        _db = os.path.join(os.path.dirname(os.path.abspath(__file__)), "session_state.db")
        conn = _sq.connect(_db)
        rows = conn.execute(
            "SELECT session_id, conversation_json, start_time FROM sessions "
            "WHERE session_id IS NOT NULL "
            "ORDER BY last_active DESC LIMIT 50"
        ).fetchall()
        conn.close()
        today = date.today().isoformat()
        yesterday = (date.today() - timedelta(days=1)).isoformat()
        result = {"today": [], "yesterday": [], "older": []}
        for sid, cjson, start_time in rows:
            turns = json.loads(cjson or "[]")
            first_user = next((t["content"] for t in turns if t.get("role") == "user"), None)
            title = (first_user[:40] + ("..." if len(first_user) > 40 else "")) if first_user else f"New Chat ({sid})"
            item = {
                "session_id": sid,
                "title": title,
                "timestamp": start_time or "",
                "message_count": len(turns) // 2,
            }
            day = (start_time or "")[:10]
            if day == today:
                result["today"].append(item)
            elif day == yesterday:
                result["yesterday"].append(item)
            else:
                result["older"].append(item)
        return result
    except Exception as e:
        log.warning(f"get_sessions failed: {e}")
        return {"today": [], "yesterday": [], "older": []}


@app.post("/api/sessions/new")
async def create_session_endpoint(request: Request):
    try:
        import sqlite3 as _sq
        body = await request.json()
        sid = body.get("session_id") or f"web_{int(__import__('time').time())}"
        _db = os.path.join(os.path.dirname(os.path.abspath(__file__)), "session_state.db")
        now = datetime.datetime.now().isoformat()
        conn = _sq.connect(_db)
        conn.execute(
            "INSERT OR IGNORE INTO sessions (session_id, device, start_time, last_active, status, conversation_json) VALUES (?,?,?,?,?,?)",
            (sid, "web", now, now, "active", "[]")
        )
        conn.commit()
        conn.close()
        return {"ok": True, "session_id": sid}
    except Exception as e:
        log.warning(f"create_session failed: {e}")
        return {"ok": False, "error": str(e)}


@app.get("/api/sessions/{session_id}/messages")
async def get_session_messages(session_id: str):
    try:
        import sqlite3 as _sq
        _db = os.path.join(os.path.dirname(os.path.abspath(__file__)), "session_state.db")
        conn = _sq.connect(_db)
        row = conn.execute(
            "SELECT conversation_json FROM sessions WHERE session_id=?", (session_id,)
        ).fetchone()
        conn.close()
        turns = json.loads(row[0]) if row and row[0] else []
        return {"messages": turns}
    except Exception as e:
        log.warning(f"get_session_messages failed: {e}")
        return {"messages": []}


# ── REPO DNA ENDPOINTS ──────────────────────────────────────────────────────

_REPO_URL_RE = re.compile(r"^https://github\.com/[\w\-]+/[\w\-]+$")


@app.post("/api/repo/analyze")
async def repo_analyze(request: Request):
    if not _REPO_DNA_OK:
        return JSONResponse({"error": "repo_dna module not available"}, status_code=503)
    try:
        body = await request.json()
        repo_url = (body.get("repo_url") or "").strip().rstrip("/")
        force_refresh = bool(body.get("force_refresh", False))
        if not _REPO_URL_RE.match(repo_url):
            return JSONResponse({"error": "Invalid URL", "detail": "Must match https://github.com/owner/repo"}, status_code=400)
        log.info(f"[repo_dna] analyze requested: {repo_url} force={force_refresh}")
        analysis = _analyze_repo(repo_url, force_refresh=force_refresh)
        return JSONResponse(analysis)
    except RepoFetchError as exc:
        log.warning(f"[repo_dna] fetch error: {exc}")
        return JSONResponse({"error": "Fetch failed", "detail": str(exc)}, status_code=400)
    except RepoAnalysisError as exc:
        log.warning(f"[repo_dna] analysis error: {exc}")
        return JSONResponse({"error": "Analysis failed", "detail": str(exc)}, status_code=500)
    except Exception as exc:
        log.warning(f"[repo_dna] unexpected: {exc}")
        return JSONResponse({"error": "Internal error", "detail": str(exc)}, status_code=500)


@app.get("/api/repo/analyses")
async def repo_analyses():
    if not _REPO_DNA_OK:
        return JSONResponse({"error": "repo_dna module not available"}, status_code=503)
    try:
        all_analyses = _get_cached_analyses()
        items = [
            {
                "repo_name": a.get("repo_name", ""),
                "repo_url": a.get("repo_url", ""),
                "analyzed_at": a.get("analyzed_at", ""),
                "steal_this_count": len(a.get("steal_this", [])),
                "quick_wins_count": len(a.get("quick_wins", [])),
            }
            for a in all_analyses
        ]
        return JSONResponse(items)
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=500)


@app.post("/api/repo/watch")
async def repo_watch(request: Request):
    if not _REPO_DNA_OK:
        return JSONResponse({"error": "repo_dna module not available"}, status_code=503)
    try:
        body = await request.json()
        repo_url = (body.get("repo_url") or "").strip().rstrip("/")
        if not _REPO_URL_RE.match(repo_url):
            return JSONResponse({"error": "Invalid URL", "detail": "Must match https://github.com/owner/repo"}, status_code=400)
        added = _watch_repo(repo_url)
        return JSONResponse({"watching": True, "added": added, "repo_url": repo_url})
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=500)


@app.get("/api/repo/watched")
async def repo_watched():
    if not _REPO_DNA_OK:
        return JSONResponse({"error": "repo_dna module not available"}, status_code=503)
    try:
        return JSONResponse(_get_watched_repos())
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=500)


_COMPARE_CATEGORIES = [
    "Memory Systems", "LLM Routing", "Voice Pipeline", "Agent Capabilities",
    "UI/Interface", "Integrations", "Security", "Reliability", "Code Quality", "Unique Features",
]

@app.post("/api/repo/compare")
async def repo_compare(request: Request):
    if not _REPO_DNA_OK:
        return JSONResponse({"error": "repo_dna module not available"}, status_code=503)
    try:
        body = await request.json()
        repo_url = (body.get("repo_url") or "").strip().rstrip("/")
        if not _REPO_URL_RE.match(repo_url):
            return JSONResponse({"error": "Invalid URL"}, status_code=400)

        # Must have cached analysis
        all_analyses = _get_cached_analyses()
        cached = next((a for a in all_analyses if a.get("repo_url") == repo_url), None)
        if not cached:
            return JSONResponse({"error": "analyze first", "detail": "Run analyze before compare"}, status_code=404)

        edith_summary = _build_edith_context_summary()
        compare_prompt = f"""EDITH self-knowledge (live scan):
{edith_summary}

Target repo analysis:
{json.dumps(cached, indent=2)}

Produce a head-to-head comparison for these exact categories: {', '.join(_COMPARE_CATEGORIES)}

Return ONLY valid JSON with no prose outside it:
{{
  "categories": [
    {{
      "name": "category name",
      "edith_score": 1,
      "repo_score": 1,
      "edith_note": "what EDITH has",
      "repo_note": "what repo has",
      "winner": "edith|repo|tie"
    }}
  ],
  "overall_winner": "edith|repo|tie",
  "edith_advantages": ["..."],
  "repo_advantages": ["..."],
  "verdict": "2-3 sentence summary"
}}

Score 1-10. winner must be exactly edith, repo, or tie. Output exactly {len(_COMPARE_CATEGORIES)} categories."""

        import smart_router as _sr
        raw = _sr.smart_call(
            prompt=compare_prompt,
            intent="repo_analyze",
            system="You are EDITH's competitive intelligence engine. Return ONLY valid JSON.",
        )

        try:
            result = json.loads(raw)
        except json.JSONDecodeError:
            m = re.search(r"\{[\s\S]+\}", raw)
            result = json.loads(m.group(0)) if m else {"error": "LLM returned non-JSON", "raw": raw}

        result["repo_url"] = repo_url
        result["repo_name"] = cached.get("repo_name", "")
        return JSONResponse(result)
    except json.JSONDecodeError as exc:
        return JSONResponse({"error": "Parse failed", "detail": str(exc)}, status_code=500)
    except Exception as exc:
        log.warning(f"[repo_compare] {exc}")
        return JSONResponse({"error": str(exc)}, status_code=500)


@app.delete("/api/repo/cache")
async def repo_clear_cache(repo_url: str = None):
    if not _REPO_DNA_OK:
        return JSONResponse({"error": "repo_dna module not available"}, status_code=503)
    try:
        url = (repo_url or "").strip() or None
        _clear_repo_cache(url)
        return JSONResponse({"cleared": True, "repo_url": url or "all"})
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=500)


# ── Repo DNA — Click-to-adapt endpoints ──────────────────────────────────────

try:
    from agent import start_agent_task as _start_agent_task, execute_agent_task as _execute_agent_task
    _AGENT_OK = True
except ImportError:
    _AGENT_OK = False

try:
    from devlog import add_entry as _devlog_add_entry
    _DEVLOG_OK = True
except ImportError:
    _DEVLOG_OK = False

_ADAPT_PREVIEW_SYSTEM = (
    "You are EDITH's code architect. Given a capability from a competitor repo "
    "(may be JS, Rust, TypeScript, or any language), your job is to:\n"
    "1. Understand the CONCEPT behind the capability — not the syntax.\n"
    "2. Decide if EDITH actually needs this. EDITH is a Python backend AI daemon: "
    "no browser, no UI state, no Node.js, no Redux, no DOM.\n"
    "3. If applicable: implement in idiomatic Python using EDITH's existing patterns. "
    "Translate concepts — never copy JS/Rust syntax, class names, or polyfills.\n"
    "4. If not applicable: say so and explain why.\n\n"
    "TARGET_FILE must be one of the EDITH Python files listed in the prompt. "
    "If no existing file fits, use 'utils.py'.\n\n"
    "Format your response EXACTLY as:\n"
    "TARGET_FILE: <real_edith_file.py>\n"
    "APPLICABLE: yes/no\n"
    "REASON: <one line>\n"
    "```python\n<Python implementation, or empty block if not applicable>\n```"
)


@app.post("/api/repo/adapt-preview")
async def repo_adapt_preview(request: Request):
    if not _REPO_DNA_OK:
        return JSONResponse({"error": "repo_dna module not available"}, status_code=503)
    try:
        import glob as _glob
        body = await request.json()
        steal_item = body.get("steal_item") or {}
        repo_url = (body.get("repo_url") or "").strip()

        capability = steal_item.get("capability") or steal_item.get("title") or "unknown"
        description = steal_item.get("description") or steal_item.get("what") or ""
        steal_from = steal_item.get("steal_from") or steal_item.get("file_hint") or ""

        _edith_dir = os.path.dirname(os.path.abspath(__file__))
        edith_files = sorted(
            os.path.basename(f) for f in _glob.glob(os.path.join(_edith_dir, "*.py"))
        )
        file_list_str = ", ".join(edith_files)

        task_description = (
            f"Implement '{capability}' in EDITH. "
            f"Pattern source: {steal_from or 'see repo'}. "
            f"Repo: {repo_url}. "
            f"What it does: {description}"
        )
        prompt = (
            f"Capability to steal: {capability}\n"
            f"What it does: {description}\n"
            f"Source file in their repo: {steal_from}\n"
            f"Their repo: {repo_url}\n\n"
            f"EDITH Python files (flat directory, no subdirs): {file_list_str}\n\n"
            "Generate a Python implementation sketch for EDITH. "
            "TARGET_FILE must be one of the files listed above."
        )

        import smart_router as _sr
        raw = _sr.smart_call(
            prompt=prompt,
            intent="repo_analyze",
            system=_ADAPT_PREVIEW_SYSTEM,
        )

        target_file = "utils.py"
        applicable = True
        reason = ""
        for line in raw.splitlines():
            if line.startswith("TARGET_FILE:"):
                candidate = line.split(":", 1)[1].strip()
                if candidate in edith_files:
                    target_file = candidate
            elif line.startswith("APPLICABLE:"):
                applicable = line.split(":", 1)[1].strip().lower() == "yes"
            elif line.startswith("REASON:"):
                reason = line.split(":", 1)[1].strip()

        return JSONResponse({
            "diff_preview": raw,
            "target_file": target_file,
            "task_description": task_description,
            "capability": capability,
            "applicable": applicable,
            "reason": reason,
        })
    except Exception as exc:
        log.warning(f"[repo_adapt] preview error: {exc}")
        return JSONResponse({"error": str(exc)}, status_code=500)


@app.post("/api/repo/adapt-confirm")
async def repo_adapt_confirm(request: Request):
    if not _AGENT_OK:
        return JSONResponse({"error": "agent module not available"}, status_code=503)
    try:
        body = await request.json()
        confirmed = bool(body.get("confirmed", False))
        task_description = (body.get("task_description") or "").strip()
        target_file = (body.get("target_file") or "").strip()
        capability = (body.get("capability") or "").strip()
        repo_url = (body.get("repo_url") or "").strip()

        if not confirmed:
            return JSONResponse({"status": "rejected"})

        if not task_description:
            return JSONResponse({"error": "task_description required"}, status_code=400)

        # Plan the task
        plan_result = _start_agent_task(task_description)
        if not plan_result.ok:
            return JSONResponse({"error": f"Planning failed: {plan_result.error}"}, status_code=500)

        task_id = plan_result.value["task_id"]

        # Stash metadata for AGENT_DONE handler to call mark_adapted on success
        _adapt_meta[task_id] = {
            "capability": capability,
            "repo_url": repo_url,
            "target_file": target_file,
        }

        # Execute async in background thread
        exec_result = _execute_agent_task(task_id)
        if not exec_result.ok:
            _adapt_meta.pop(task_id, None)
            return JSONResponse({"error": f"Execution failed: {exec_result.error}"}, status_code=500)

        # Devlog entry
        if _DEVLOG_OK:
            try:
                _devlog_add_entry(
                    change=f"repo_dna: Adapted '{capability}' from {repo_url} → {target_file}",
                    reason="repo_dna click-to-adapt HITL confirm",
                    status="applied",
                    error="",
                    next_plan=f"verify changes in {target_file or 'EDITH'}",
                )
            except Exception as dl_exc:
                log.warning(f"[repo_adapt] devlog write failed: {dl_exc}")

        return JSONResponse({
            "status": "queued",
            "task_id": task_id,
            "message": f"Agent executing '{capability}' adaptation in background.",
        })
    except Exception as exc:
        log.warning(f"[repo_adapt] confirm error: {exc}")
        return JSONResponse({"error": str(exc)}, status_code=500)


@app.get("/api/repo/adapt-status/{task_id}")
async def repo_adapt_status(task_id: str):
    result = _adapt_results.get(task_id, {"status": "pending"})
    return JSONResponse(result)


# ── Repo DNA — Gap plan (strategic gap → sub-task decomposition) ──────────────

_sigs_cache: dict = {"data": None, "mtime": 0.0}

def _get_edith_signatures() -> dict:
    import glob as _g
    edith_dir = os.path.dirname(os.path.abspath(__file__))
    files = sorted(_g.glob(os.path.join(edith_dir, "*.py")))
    max_mtime = max((os.path.getmtime(f) for f in files), default=0.0)
    if _sigs_cache["mtime"] == max_mtime and _sigs_cache["data"] is not None:
        return _sigs_cache["data"]
    _BLOCKLIST = {"config.py", "vault.py", "voice.py"}
    sigs: dict = {}
    for fpath in files:
        fname = os.path.basename(fpath)
        if fname in _BLOCKLIST:
            continue
        try:
            defs = [l.strip() for l in open(fpath) if l.strip().startswith("def ")]
            if defs:
                sigs[fname] = defs
        except Exception:
            pass
    _sigs_cache.update({"data": sigs, "mtime": max_mtime})
    return sigs

def _get_all_fns_in_file(fname: str) -> set:
    edith_dir = os.path.dirname(os.path.abspath(__file__))
    fpath = os.path.join(edith_dir, fname)
    fns: set = set()
    if not os.path.exists(fpath):
        return fns
    try:
        for line in open(fpath):
            s = line.strip()
            if s.startswith("def "):
                fns.add(s.split("(")[0].replace("def ", "").strip())
    except Exception:
        pass
    return fns

def _read_file_skeleton(fname: str) -> str:
    edith_dir = os.path.dirname(os.path.abspath(__file__))
    fpath = os.path.join(edith_dir, fname)
    if not os.path.exists(fpath):
        return ""
    try:
        return "".join(open(fpath).readlines()[:200])
    except Exception:
        return ""

_GAP_PLAN_SYSTEM = (
    "You are EDITH's code architect. Decompose a capability gap into 3-5 sub-tasks. "
    "Each sub-task adds ONE new Python function to the target file. "
    "Rules: ADD ONLY. Never modify existing functions. Python only. Max 40 lines per function. "
    "Return JSON only, no markdown fences:\n"
    '{"target_file":"filename.py","reason":"one sentence",'
    '"subtasks":[{"id":1,"title":"...","function_name":"...","description":"...","lines_estimate":20}]}'
)


@app.post("/api/repo/gap-plan")
async def repo_gap_plan(request: Request):
    if not _REPO_DNA_OK:
        return JSONResponse({"error": "repo_dna module not available"}, status_code=503)
    try:
        body = await request.json()
        gap = body.get("gap") or {}
        repo_url = (body.get("repo_url") or "").strip()

        capability = gap.get("capability") or ""
        what = gap.get("what") or ""
        why = gap.get("why") or ""

        all_sigs = _get_edith_signatures()
        sigs_text = "\n".join(
            f"{fname}:\n" + "\n".join(f"  {d}" for d in defs)
            for fname, defs in all_sigs.items()
        )
        edith_files = sorted(all_sigs.keys())

        prompt = (
            f"Gap: {capability}\nWhat: {what}\nWhy: {why}\n\n"
            f"EDITH files + their functions:\n{sigs_text}\n\n"
            f"Pick the best existing file as target. Decompose into 3-5 sub-tasks. "
            f"TARGET_FILE must be one of: {', '.join(edith_files)}\n"
            "Return JSON only."
        )

        import smart_router as _sr
        import json as _json, re as _re
        raw = _sr.smart_call(prompt=prompt, intent="repo_analyze", system=_GAP_PLAN_SYSTEM)

        result: dict = {}
        for attempt in [
            lambda: _json.loads(raw.strip()),
            lambda: _json.loads(_re.sub(r'```[a-z]*\n?', '', raw).strip()),
            lambda: _json.loads(_re.search(r'\{[\s\S]+\}', raw).group(0)),
        ]:
            try:
                result = attempt()
                break
            except Exception:
                pass

        _BLOCKLIST = {"config.py", "vault.py", "voice.py"}
        target_file = result.get("target_file", "utils.py")
        if target_file in _BLOCKLIST or not target_file.endswith(".py") or target_file not in all_sigs:
            target_file = "utils.py"

        existing_fns = _get_all_fns_in_file(target_file)
        file_skeleton = _read_file_skeleton(target_file)

        subtasks = [
            t for t in (result.get("subtasks") or [])
            if isinstance(t, dict) and t.get("function_name") not in existing_fns
        ]

        return JSONResponse({
            "target_file": target_file,
            "pick_reason": result.get("reason", ""),
            "file_skeleton": file_skeleton,
            "subtasks": subtasks,
            "capability": capability,
            "repo_url": repo_url,
        })
    except Exception as exc:
        log.warning(f"[repo_gap_plan] error: {exc}")
        return JSONResponse({"error": str(exc)}, status_code=500)


# ── Repo DNA — EDITH self-audit ──────────────────────────────────────────────

_audit_cache: dict = {"result": None, "ts": 0.0}


def _audit_edith_self() -> dict:
    import time, re as _re, json as _json
    import smart_router as _sr

    edith_dir = os.path.dirname(os.path.abspath(__file__))

    # Parse CLAUDE.md — extract all .py filenames mentioned
    claude_md_path = os.path.join(edith_dir, "CLAUDE.md")
    claude_md = open(claude_md_path, errors="ignore").read() if os.path.exists(claude_md_path) else ""
    module_map_files = list(set(_re.findall(r'\b[\w_]+\.py\b', claude_md)))
    actual_files = set(f for f in os.listdir(edith_dir) if f.endswith(".py"))
    missing_files = [f for f in module_map_files if f not in actual_files]

    # 4-Vision function checks — verify key functions exist in vision files
    _VISION_EXPECTED = {
        "cognitive_profile.py": ["update_profile", "detect_drift", "get_profile"],
        "self_improve.py": ["run_scheduled_improvement", "monitor_arxiv"],
        "life_os.py": ["weekly_briefing", "simulate_branches"],
        "council.py": ["council_debate", "run_council"],
    }
    vision_gaps = [
        f"{vf}: missing `{fn}`"
        for vf, fns in _VISION_EXPECTED.items()
        for fn in fns
        if fn not in _get_all_fns_in_file(vf)
    ]

    # Function signatures for LLM context (capped to avoid token overflow)
    all_sigs = _get_edith_signatures()
    sigs_text = "\n".join(
        f"{fname}: {', '.join(d.split('(')[0].replace('def ', '') for d in defs[:8])}"
        for fname, defs in list(all_sigs.items())[:30]
    )

    prompt = (
        f"EDITH CLAUDE.md lists these .py files:\n{', '.join(module_map_files[:60])}\n\n"
        f"Files MISSING from disk: {', '.join(missing_files) or 'none'}\n\n"
        f"4-Vision function checks: {'; '.join(vision_gaps) or 'all present'}\n\n"
        f"Actual implemented functions (sample):\n{sigs_text}\n\n"
        "Find up to 8 notable gaps between documented architecture and actual implementation. "
        "Return JSON array only, no markdown:\n"
        '[{"capability":"short name","claimed":"what docs say","reality":"what code has",'
        '"severity":"critical|medium|low","target_file":"which .py to fix"}]'
    )

    raw = _sr.smart_call(
        prompt=prompt, intent="repo_analyze",
        system="EDITH code auditor. Analyze concrete evidence. Return JSON array only, no markdown.",
    )

    gaps: list = []
    for attempt in [
        lambda: _json.loads(raw.strip()),
        lambda: _json.loads(_re.sub(r'```[a-z]*\n?', '', raw).strip()),
        lambda: _json.loads((_re.search(r'\[[\s\S]+\]', raw) or type('x', (), {'group': lambda *_: '[]'})()).group(0)),
    ]:
        try:
            result = attempt()
            if isinstance(result, list):
                gaps = result
                break
        except Exception:
            pass

    # Hard-inject confirmed missing files as critical items
    for mf in missing_files[:3]:
        if not any(mf in g.get("capability", "") for g in gaps):
            gaps.insert(0, {
                "capability": f"Missing module: {mf}",
                "claimed": f"CLAUDE.md lists {mf} in module map",
                "reality": "File does not exist on disk",
                "severity": "critical",
                "target_file": mf,
            })

    return {
        "summary": f"Found {len(gaps)} gaps between CLAUDE.md and actual code.",
        "audit_gaps": gaps,
        "missing_files": missing_files,
        "vision_gaps": vision_gaps,
        "timestamp": __import__("datetime").datetime.utcnow().isoformat(),
    }


@app.post("/api/repo/self-audit")
async def repo_self_audit():
    if not _REPO_DNA_OK:
        return JSONResponse({"error": "repo_dna module not available"}, status_code=503)
    import time as _time
    now = _time.time()
    if _audit_cache["result"] is not None and now - _audit_cache["ts"] < 300:
        return JSONResponse({**_audit_cache["result"], "cached": True})
    try:
        result = _audit_edith_self()
        _audit_cache.update({"result": result, "ts": now})
        return JSONResponse(result)
    except Exception as exc:
        log.warning(f"[self_audit] error: {exc}")
        return JSONResponse({"error": str(exc)}, status_code=500)


@app.post("/api/repo/watch-check")
async def repo_watch_check():
    """Manual trigger for watched repo check."""
    if not _REPO_DNA_OK:
        return JSONResponse({"error": "repo_dna module not available"}, status_code=503)
    try:
        updated = _check_watched_repos()
        return JSONResponse({"updated": updated, "count": len(updated)})
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=500)


if __name__ == "__main__":
    import atexit
    import signal
    import subprocess
    
    # Register graceful shutdown
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))
    signal.signal(signal.SIGINT, lambda *_: sys.exit(0))
    atexit.register(_graceful_shutdown)

    # Start DevLog background sync (30 min interval)
    from devlog import start_devlog
    start_devlog()
    log.info("DevLog sync thread started from chat_server.")

    # Start memory monitor in background
    monitor_thread = threading.Thread(target=_memory_monitor, daemon=True)
    monitor_thread.start()

    log.info("Starting EDITH chat_server on http://127.0.0.1:8001")
    uvicorn.run(app, host="127.0.0.1", port=8001)
