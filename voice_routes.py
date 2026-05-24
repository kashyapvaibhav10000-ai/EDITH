"""
Voice I/O Routes for EDITH Chat Server

Handles all voice input/output endpoints:
- STT (speech-to-text) via Groq or local engine
- TTS (text-to-speech) streaming responses
- Microphone locking/unlocking
- Barge-in interruption signaling
- Voice mode switching (friend/normal)
"""

import asyncio
import datetime as _dt
import json
import logging
import os
import re
import subprocess
import tempfile
import threading
import traceback

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, StreamingResponse

# Ensure EDITH directory is in path
import sys
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from config import get_logger
from shared_state import _widget_history, _widget_history_lock, add_to_history, get_history

log = get_logger("voice_routes")

# ────────────────────────────────────────────────────
# Global State for Voice Pipeline
# ────────────────────────────────────────────────────

# V8: Barge-in signal — set when user interrupts, cleared by /api/voice/barge-in-complete
_barge_in_triggered = threading.Event()

# V8: Relisten flag — set by _on_barge_in to tell SSE generator to emit 'relisten' event
_restart_listen = threading.Event()

# V12: Track TTS threads so new request can join/cancel previous
_active_tts_threads: list = []

# FIX 7: Request ID tracking to prevent stale TTS
_current_voice_request_id = None
_voice_request_lock = threading.Lock()

_MAX_WIDGET_HISTORY = 10


# ────────────────────────────────────────────────────
# Helper Functions
# ────────────────────────────────────────────────────

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


# ────────────────────────────────────────────────────
# Voice Route Endpoints
# ────────────────────────────────────────────────────

def register_voice_routes(app: FastAPI):
    """Register all voice routes with FastAPI app."""
    
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
                
                with _voice_request_lock:
                    global _current_voice_request_id
                    _current_voice_request_id = str(id(request))
                
                _tts_active.set()
                
                # Try to drain before starting new TTS
                try:
                    while True:
                        _tts_queue.get_nowait()
                        _tts_queue.task_done()
                except _queue_module.Empty:
                    pass
            except Exception as e:
                log.warning(f"TTS queue drain error (non-fatal): {e}")

            try:
                from orchestrator import chat_stream
                from voice import _on_barge_in, _tts_queue, _tts_active
                
                yield f"data: {json.dumps({'type': 'start', 'intent': intent})}\n\n"
                
                full_reply = ""
                token_count = 0
                
                # Stream LLM response
                async for token in chat_stream(user_input, intent, {"source": "voice"}):
                    if not _tts_active.is_set():
                        break
                    
                    full_reply += token
                    token_count += 1
                    
                    if token_count % 5 == 0:
                        yield f"data: {json.dumps({'type': 'token', 'text': token})}\n\n"
                    
                    # Check for barge-in
                    if _barge_in_triggered.is_set():
                        _barge_in_triggered.clear()
                        log.info("Barge-in detected during TTS streaming")
                        yield f"data: {json.dumps({'type': 'barge_in'})}\n\n"
                        break
                
                add_to_history("assistant", full_reply)
                _persist_exchange(user_input, full_reply)
                
                yield f"data: {json.dumps({'type': 'done'})}\n\n"
            except asyncio.CancelledError:
                log.info("Voice respond stream cancelled")
            except Exception as e:
                log.error(f"Voice respond FATAL: {traceback.format_exc()}")
                yield f"data: {json.dumps({'type': 'error', 'error': str(e)})}\n\n"
            finally:
                try:
                    from voice import _tts_active
                    _tts_active.clear()
                except Exception:
                    pass

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
        threading.Thread(target=_warmup, daemon=True, name="chatterbox-warmup").start()
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
