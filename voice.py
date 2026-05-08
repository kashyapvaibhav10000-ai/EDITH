"""
EDITH Voice Module — v3.0
- Phase 0: IS_VOICE_ACTIVE flag
- Phase 1: Groq Whisper large-v3-turbo STT, local tiny.en fallback
- Phase 2: Sentence-streaming TTS queue (Piper)
- Phase 3: Groq Orpheus TTS (playai-tts)
- Phase 4: Chatterbox voice clone (friend.wav) — lazy load, opt-in
"""

import subprocess
import tempfile
import os
import re
import threading
import time
import queue

import config
from config import (
    PIPER_PATH, PIPER_MODEL, WHISPER_MODEL_PATH, get_logger,
    GROQ_STT_MODEL, GROQ_STT_URL,
    GROQ_TTS_MODEL, GROQ_TTS_VOICE,
    USE_GROQ_TTS, USE_CHATTERBOX, CHATTERBOX_VENV_PYTHON,
)

log = get_logger("voice")

# ── Whisper fallback model (tiny.en — kept in RAM after first load) ──
_whisper_model = None
_whisper_lock = threading.Lock()


# ── Cross-process Event — file flag + threading.Event ────────────────────────
# threading.Event alone only syncs threads in one process. File flag syncs
# across widget/daemon/wake_listener processes that share the same filesystem.
class CrossProcessEvent:
    """threading.Event that mirrors state to a file for cross-process visibility."""
    def __init__(self, flag_path: str):
        self._event = threading.Event()
        self._flag = flag_path
        # Clear stale flag only if the owning PID is dead
        try:
            with open(self._flag) as _f:
                _pid = int(_f.read().strip())
            try:
                os.kill(_pid, 0)  # 0 = existence check, no signal sent
            except (ProcessLookupError, PermissionError):
                os.unlink(self._flag)  # PID dead → stale
        except (FileNotFoundError, ValueError, OSError):
            pass  # no flag or unreadable → nothing to clear

    def set(self):
        try:
            with open(self._flag, 'w') as f:
                f.write(str(os.getpid()))
        except Exception:
            pass
        self._event.set()

    def clear(self):
        try:
            os.unlink(self._flag)
        except (FileNotFoundError, OSError):
            pass
        self._event.clear()

    def is_set(self) -> bool:
        return os.path.exists(self._flag)

    def wait(self, timeout=None):
        if self._event.is_set():
            return True
        deadline = (time.time() + timeout) if timeout is not None else None
        while True:
            if self.is_set():
                self._event.set()
                return True
            if deadline is not None and time.time() >= deadline:
                return self.is_set()
            time.sleep(0.05)


# ── TTS guard — mic stays silent while EDITH is speaking ──
_tts_active = CrossProcessEvent("/tmp/edith_tts_active")
_tts_lock = threading.Lock()

# ── TTS request-level mutex to prevent concurrent TTS launches ──
_tts_request_lock = threading.Lock()
_tts_request_active = threading.Event()
_tts_worker_thread: threading.Thread = None

# ── Shared mic mutex ──
MIC_IN_USE = CrossProcessEvent("/tmp/edith_mic_in_use")

# ── Last intent seen (set by orchestrator/dispatch before each turn) ──
_last_intent: str = ""

# ── Barge-in monitor ──
_barge_in_active = threading.Event()

# ── aplay PID tracker (H1: prevent pkill all) ──
_aplay_pid: int = None
_aplay_pid_lock = threading.Lock()

# ── Chatterbox persistent worker ──
_chatterbox_proc: subprocess.Popen = None
_chatterbox_lock = threading.Lock()
_chatterbox_last_used: float = 0.0  # epoch seconds of last speak_chatterbox() call
_CHATTERBOX_IDLE_TTL = 300          # kill worker after 5 min idle

# ── Import PRIVATE_INTENTS from config (avoid duplication) ──
from config import PRIVATE_INTENTS

VOICES_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "voices")
FRIEND_WAV = os.path.join(VOICES_DIR, "friend.wav")


# ──────────────────────────────────────────────
# Whisper fallback loader
# ──────────────────────────────────────────────
def _get_whisper():
    global _whisper_model
    with _whisper_lock:
        if _whisper_model is None:
            log.info("Loading faster-whisper tiny.en fallback model...")
            from faster_whisper import WhisperModel
            _whisper_model = WhisperModel("tiny.en", device="cpu", compute_type="int8")
            log.info("faster-whisper fallback loaded.")
    return _whisper_model


# ──────────────────────────────────────────────
# STT — Groq Whisper primary + local fallback
# ──────────────────────────────────────────────
def detect_language_hint(audio_data: bytes) -> str:
    """
    Quick heuristic — let Groq auto-detect.
    Returns language hint for logging only.
    Groq whisper-large-v3-turbo handles Hindi/Hinglish/English natively.
    """
    # Always let Groq auto-detect — it handles
    # Hindi, Hinglish, English, code-switching natively
    # No explicit language parameter = best accuracy
    return "auto"

def _get_stt_context() -> str:
    """Get last conversation turn as STT context hint for Whisper prompt."""
    try:
        # M9: Import from shared_state to avoid circular imports
        from shared_state import get_history, _widget_history_lock
        with _widget_history_lock:
            history = get_history()
            if history:
                last = list(history.values())[-2:]
                parts = []
                for msg in last:
                    if isinstance(msg, dict):
                        role = msg.get("role", "")
                        content = str(msg.get("content", ""))[:300]
                        parts.append(f"{role}: {content}")
                return " | ".join(parts)
    except Exception:
        pass
    return ""


# ──────────────────────────────────────────────
# M5: Transcript Stabilizer  
# ──────────────────────────────────────────────
class TranscriptStabilizer:
    """Filter minor ASR variations, stabilize output with state tracking."""
    def __init__(self, max_history=5):
        self.history = []
        self.max_history = max_history
    
    def stabilize(self, transcript: str) -> str:
        """Filter punctuation/casing variance; return most stable version."""
        if not transcript:
            return ""
        normalized = transcript.lower().strip()
        # Check if similar to recent history (80%+ match)
        for prev in self.history[-2:]:
            prev_norm = prev.lower().strip()
            # Simple similarity: if any substring match of length > 0.7*min_len
            min_len = min(len(normalized), len(prev_norm))
            if min_len > 0:
                common = sum(1 for a, b in zip(normalized, prev_norm) if a == b)
                if common / min_len > 0.8:
                    return prev  # Return previous exact form (punctuation preserved)
        self.history.append(transcript)
        self.history = self.history[-self.max_history:]  # Keep last N only
        return transcript


_transcript_stabilizer = TranscriptStabilizer()


# ──────────────────────────────────────────────
# M6: Rapidfuzz Fuzzy Correction
# ──────────────────────────────────────────────
class FuzzyCorrector:
    """Correct common ASR errors using fuzzy matching against known phrases."""
    def __init__(self):
        self.known_phrases = {
            "edith": ["edit", "edie", "e d i t h"],
            "groq": ["grok", "grow", "g r o q"],
            "python": ["paython", "python", "pyton"],
            "code": ["coed", "coach", "kode"],
            "search": ["search", "serch", "search"],
            "gmail": ["g mail", "gmail"],
            "reminder": ["remind", "reminder"],
            "weather": ["wheather", "weather"],
        }
    
    def correct(self, transcript: str) -> str:
        """Fuzzy match transcript words against known phrases; correct if >85% match."""
        if not transcript:
            return transcript
        words = transcript.split()
        corrected_words = []
        for word in words:
            best_match = None
            best_score = 0
            for correct_form, aliases in self.known_phrases.items():
                for alias in aliases:
                    try:
                        from rapidfuzz import fuzz
                        score = fuzz.ratio(word.lower(), alias.lower()) / 100.0
                        if score > best_score:
                            best_score = score
                            best_match = correct_form
                    except ImportError:
                        pass
            if best_score > 0.85 and best_match:
                corrected_words.append(best_match)
            else:
                corrected_words.append(word)
        result = " ".join(corrected_words)
        if result != transcript:
            log.debug(f"FuzzyCorrect: '{transcript}' → '{result}'")
        return result


_fuzzy_corrector = FuzzyCorrector()


def _transcribe_groq(wav_path: str) -> str:
    """Send WAV to Groq Whisper large-v3-turbo. Returns transcript or raises."""
    import vault
    groq_key = vault.get_secret("GROQ_API_KEY", "") or os.getenv("GROQ_API_KEY", "")
    if not groq_key:
        raise ValueError("No GROQ_API_KEY — cannot use Groq STT")

    import requests
    with open(wav_path, "rb") as f:
        audio_bytes = f.read()

    resp = requests.post(
        GROQ_STT_URL,
        headers={"Authorization": f"Bearer {groq_key}"},
        files={"file": ("audio.wav", audio_bytes, "audio/wav")},
        data={
            "model": GROQ_STT_MODEL,
            "prompt": "EDITH AI assistant. User speaks English Hindi Hinglish." + (
                f" Recent context: {_get_stt_context()}" if _get_stt_context() else ""
            ) + (
                " [PHRASE_BIAS] EDITH Groq Whisper Copilot Python coding scheduling"if _get_stt_context() else ""
            ),
        },
        timeout=15,
    )
    resp.raise_for_status()
    text = resp.json().get("text", "").strip()
    if not text:
        raise ValueError("Groq STT returned empty transcript")
    log.info("STT: Groq auto-detect language (Hindi/Hinglish/English supported)")
    return text



def _transcribe_local(wav_path: str) -> str:
    """Local faster-whisper tiny.en fallback."""
    model = _get_whisper()
    segments, _ = model.transcribe(wav_path, beam_size=1)
    return " ".join([s.text for s in segments]).strip()


def _transcribe_sarvam(wav_path: str) -> str:
    """S3: Sarvam Saaras v3 STT — Indian-English / Hindi / Hinglish optimized."""
    import vault
    api_key = vault.get_secret("SARVAM_API_KEY", "") or os.getenv("SARVAM_API_KEY", "")
    if not api_key:
        raise ValueError("No SARVAM_API_KEY — skipping Sarvam STT")
    from sarvamai import SarvamAI
    client = SarvamAI(api_subscription_key=api_key)
    with open(wav_path, "rb") as f:
        response = client.speech_to_text.transcribe(
            file=f,
            model="saaras:v3",
            language_code="hi-IN",  # auto-detect Hindi/English/Hinglish
        )
    text = (response.transcript or "").strip()
    if not text:
        raise ValueError("Sarvam returned empty transcript")
    log.info(f"STT: Sarvam Saaras v3 returned {len(text)} chars")
    return text


def transcribe(wav_path: str) -> str:
    """
    Transcribe audio file.
    - If last intent was private (vault/shell/email) → local only.
    - Otherwise try Groq first, then Sarvam (Indian-English), fall back to local.
    """
    global _last_intent

    if _last_intent in PRIVATE_INTENTS:
        log.info(f"STT: private intent ({_last_intent}) → local Whisper only")
        text = _transcribe_local(wav_path)
    else:
        try:
            log.info("STT: trying Groq Whisper large-v3-turbo")
            text = _transcribe_groq(wav_path)
            log.info(f"STT: Groq returned {len(text)} chars")
        except Exception as groq_err:
            log.warning(f"STT: Groq failed ({groq_err}) → trying Sarvam")
            try:
                text = _transcribe_sarvam(wav_path)
            except Exception as sarvam_err:
                log.warning(f"STT: Sarvam failed ({sarvam_err}) → local fallback")
                text = _transcribe_local(wav_path)
    
    # M5: Stabilize transcript to filter minor VAR variations
    text = _transcript_stabilizer.stabilize(text)
    
    # M6: Apply fuzzy correction for common ASR errors
    text = _fuzzy_corrector.correct(text)
    
    return text



def get_last_intent() -> str:
    return _last_intent

def set_last_intent(intent: str):
    """Called by orchestrator/dispatch after each turn to gate STT privacy."""
    global _last_intent
    _last_intent = intent


# ──────────────────────────────────────────────
# TTS engines
# ──────────────────────────────────────────────
def speak_piper(text: str):
    """Piper TTS — local, always available."""
    global _aplay_pid
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
        out_file = f.name
    try:
        subprocess.run(
            [PIPER_PATH, "--model", PIPER_MODEL, "--output_file", out_file],
            input=text.encode(),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=30,
        )
        try:
            import sounddevice as sd
            import soundfile as sf
            data, samplerate = sf.read(out_file)
            sd.play(data, samplerate)
            sd.wait()
        except Exception:
            # aplay fallback if sounddevice unavailable or fails
            aplay_proc = subprocess.Popen(
                ["aplay", "-D", "pulse", "-q", out_file],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
            )
            with _aplay_pid_lock:
                _aplay_pid = aplay_proc.pid
            aplay_proc.wait()
            with _aplay_pid_lock:
                _aplay_pid = None
    finally:
        try:
            os.unlink(out_file)
        except OSError:
            pass


def speak_groq_orpheus(text: str):
    """
    Groq Orpheus TTS (playai-tts / Fritz-PlayAI).
    Streams audio response directly to aplay subprocess — no disk write.
    Raises on any error so caller can fall back to Piper.
    """
    global _aplay_pid
    import vault
    groq_key = vault.get_secret("GROQ_API_KEY", "") or os.getenv("GROQ_API_KEY", "")
    if not groq_key:
        raise ValueError("No GROQ_API_KEY — cannot use Groq TTS")

    import requests
    resp = requests.post(
        "https://api.groq.com/openai/v1/audio/speech",
        headers={
            "Authorization": f"Bearer {groq_key}",
            "Content-Type": "application/json",
        },
        json={
            "model": GROQ_TTS_MODEL,
            "input": text,
            "voice": GROQ_TTS_VOICE,
        },
        stream=True,
        timeout=20,
    )
    resp.raise_for_status()

    # H7: Check content type
    content_type = resp.headers.get("content-type", "")
    log.info(f"Groq TTS content-type: {content_type}")
    
    if "mpeg" in content_type or "mp3" in content_type:
        aplay_cmd = ["ffplay", "-nodisp", "-autoexit", "-"]
    elif "wav" in content_type:
        aplay_cmd = ["aplay", "-D", "pulse", "-q", "-"]
    else:
        aplay_cmd = ["aplay", "-D", "pulse", "-q", "-f", "S16_LE", "-r", "24000", "-c", "1", "-"]
    
    aplay = subprocess.Popen(
        aplay_cmd,
        stdin=subprocess.PIPE,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    # H1: Track aplay PID
    with _aplay_pid_lock:
        _aplay_pid = aplay.pid
    try:
        for chunk in resp.iter_content(chunk_size=4096):
            if chunk:
                aplay.stdin.write(chunk)
        aplay.stdin.close()
        try:
            aplay.wait(timeout=60)
        except subprocess.TimeoutExpired:
            log.warning("Groq TTS: aplay hung — killing")
            aplay.kill()
    except Exception:
        aplay.kill()
        raise
    finally:
        with _aplay_pid_lock:
            _aplay_pid = None


CHATTERBOX_WORKER = os.path.join(os.path.dirname(os.path.abspath(__file__)), "chatterbox_worker.py")


def _chatterbox_idle_killer():
    """Background thread: kill Chatterbox worker after IDLE_TTL seconds of no TTS calls."""
    while True:
        time.sleep(60)
        global _chatterbox_proc, _chatterbox_last_used
        with _chatterbox_lock:
            if _chatterbox_proc is not None and _chatterbox_proc.poll() is None:
                idle = time.time() - _chatterbox_last_used
                if idle >= _CHATTERBOX_IDLE_TTL:
                    log.info(f"TTS: Chatterbox idle {idle:.0f}s — killing worker to free RAM")
                    try:
                        _chatterbox_proc.stdin.close()
                        _chatterbox_proc.terminate()
                        _chatterbox_proc.wait(timeout=5)
                    except Exception:
                        try:
                            _chatterbox_proc.kill()
                        except Exception:
                            pass
                    _chatterbox_proc = None


threading.Thread(target=_chatterbox_idle_killer, daemon=True, name="chatterbox-idle-killer").start()


_CHATTERBOX_READY_TIMEOUT = 120  # seconds to wait for model load on cold start

def _get_chatterbox_worker() -> subprocess.Popen:
    """Spawn worker if needed and block until it sends {"status":"ready"}.
    Returns process or raises RuntimeError if model fails to load."""
    global _chatterbox_proc
    with _chatterbox_lock:
        if _chatterbox_proc is None or _chatterbox_proc.poll() is not None:
            log.info("TTS: spawning Chatterbox worker — waiting for model load (~70s cold)")
            _chatterbox_proc = subprocess.Popen(
                [CHATTERBOX_VENV_PYTHON, CHATTERBOX_WORKER],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
            )
            # Wait for {"status": "ready"} before returning
            ready_holder = [None]
            def _read_ready():
                try:
                    ready_holder[0] = _chatterbox_proc.stdout.readline()
                except Exception:
                    pass
            t = threading.Thread(target=_read_ready, daemon=True)
            t.start()
            t.join(timeout=_CHATTERBOX_READY_TIMEOUT)
            if t.is_alive() or not ready_holder[0]:
                _chatterbox_proc.kill()
                _chatterbox_proc = None
                raise RuntimeError(f"Chatterbox model failed to load in {_CHATTERBOX_READY_TIMEOUT}s")
            import json as _json
            msg = _json.loads(ready_holder[0].strip())
            if msg.get("status") == "error":
                _chatterbox_proc.kill()
                _chatterbox_proc = None
                raise RuntimeError(f"Chatterbox worker error: {msg.get('message')}")
            log.info("TTS: Chatterbox worker ready")
    return _chatterbox_proc


def speak_chatterbox(text: str):
    """
    Chatterbox TTS — voice-cloned from voices/friend.wav.
    Uses a persistent worker process (stdin/stdout JSON protocol) to avoid
    repeated model load overhead. Falls back to Piper on any error.
    Phase 4 — requires USE_CHATTERBOX=True and friend.wav present.
    Returns False if unavailable (caller falls back to Piper).
    """
    global _chatterbox_proc, _chatterbox_last_used
    if not os.path.exists(FRIEND_WAV):
        log.debug(f"Chatterbox skipped: friend.wav missing at {FRIEND_WAV}")
        return False

    if not os.path.exists(CHATTERBOX_VENV_PYTHON):
        log.debug(f"Chatterbox skipped: venv not found at {CHATTERBOX_VENV_PYTHON}")
        return False

    _chatterbox_last_used = time.time()  # reset idle timer on every TTS call
    out_file = None
    try:
        import json as _json
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False, dir="/tmp") as f:
            out_file = f.name

        worker = _get_chatterbox_worker()
        try:
            worker.stdin.write(_json.dumps({"text": text, "out_wav": out_file}) + "\n")
            worker.stdin.flush()
        except (BrokenPipeError, OSError) as e:
            raise RuntimeError(f"Chatterbox stdin broken: {e}")

        resp_holder = [None]
        def _read():
            try:
                resp_holder[0] = worker.stdout.readline()
            except Exception:
                pass
        t = threading.Thread(target=_read, daemon=True)
        t.start()
        t.join(timeout=30)
        if t.is_alive():
            raise RuntimeError("Chatterbox generation timeout (30s)")

        if not resp_holder[0]:
            raise RuntimeError("Chatterbox worker closed stdout")
        resp = _json.loads(resp_holder[0].strip())
        if resp.get("status") != "ok":
            raise RuntimeError(f"Chatterbox error: {resp.get('message', 'unknown')}")

        if not os.path.exists(out_file) or os.path.getsize(out_file) < 100:
            raise RuntimeError("Chatterbox produced no audio")

        log.info("TTS: Chatterbox done, playing audio")
        subprocess.run(["aplay", "-D", "pulse", "-q", out_file], timeout=30, capture_output=True)
    except Exception as e:
        log.warning(f"TTS: Chatterbox failed ({e}) — resetting worker")
        with _chatterbox_lock:
            _chatterbox_proc = None
        return False
    finally:
        if out_file and os.path.exists(out_file):
            try:
                os.unlink(out_file)
            except Exception:
                pass
    return True


# ──────────────────────────────────────────────
# Sentence-streaming TTS queue (Phase 2)
# ──────────────────────────────────────────────
# FIX 9: Bounded queue to prevent stale sentence accumulation
_tts_queue: queue.Queue = queue.Queue(maxsize=20)


def _tts_worker():
    """Background thread: drains _tts_queue and speaks each sentence."""
    # H2: Crash recovery wrapper
    while True:
        try:
            sentence = _tts_queue.get()
            if sentence is None:  # poison pill — queue done
                _tts_queue.task_done()
                break
            try:
                _tts_active.set()
                speak_sentence(sentence)
            except Exception as e:
                log.error(f"TTS worker sentence error: {e}")
            finally:
                _tts_queue.task_done()
        except Exception as e:
            log.error(f"TTS worker crashed: {e} — restarting")
            _tts_active.clear()  # P1: don't leave mic muted if worker loop crashes
            config.IS_VOICE_ACTIVE = False
            time.sleep(0.5)
            continue

    config.IS_VOICE_ACTIVE = False
    _tts_active.clear()
    log.debug("TTS queue drained — mic unmuted")


def _add_emotion_tag(text: str) -> str:
    """Add Groq Orpheus paralinguistic tags based on sentence content."""
    if text.strip().endswith('?'):
        return text
    text_lower = text.lower()
    if any(w in text_lower for w in ['great', 'done', 'perfect', 'excellent', 'amazing', 'wonderful', 'sure', 'absolutely']):
        return f"<cheerful> {text}"
    if any(w in text_lower for w in ['sorry', 'unfortunately', 'cannot', "can't", 'unable', 'failed', 'error']):
        return f"<empathetic> {text}"
    if any(w in text_lower for w in ['let me', 'checking', 'looking', 'searching', 'analyzing', 'processing']):
        return f"<thoughtful> {text}"
    return text


def speak_sentence(text: str):
    """Speak one sentence using the active TTS engine. Priority controlled by PREFER_FAST_TTS."""
    text = text.strip()
    text = _add_emotion_tag(text)
    if not text:
        return
    
    # FIX 4: Use request lock to serialize TTS launches from concurrent requests
    if _tts_request_lock.acquire(timeout=15):
        _tts_request_active.set()
        try:
            # Priority chain unchanged — Groq/Chatterbox/Piper routing
            if config.PREFER_FAST_TTS:
                # Fast priority: Groq first (instant), then Chatterbox (slow but natural)
                if config.USE_GROQ_TTS:
                    try:
                        log.info("TTS: Groq Orpheus (FAST)")
                        speak_groq_orpheus(text)
                        return
                    except Exception as e:
                        log.warning(f"TTS: Groq failed ({e}) → Chatterbox fallback")

                if config.USE_CHATTERBOX and os.path.exists(FRIEND_WAV):
                    try:
                        log.info("TTS: Chatterbox")
                        result = speak_chatterbox(text)
                        if result is not False:
                            return
                    except Exception as e:
                        log.warning(f"TTS: Chatterbox failed ({e}) → Piper fallback")

                log.info("TTS: Piper local")
                speak_piper(text)
            else:
                # Normal priority: Chatterbox first (natural but slow), then Groq (instant)
                if config.USE_CHATTERBOX and os.path.exists(FRIEND_WAV):
                    try:
                        log.info("TTS: Chatterbox")
                        result = speak_chatterbox(text)
                        if result is not False:
                            return
                    except Exception as e:
                        log.warning(f"TTS: Chatterbox failed ({e}) → Groq fallback")

                if config.USE_GROQ_TTS:
                    try:
                        log.info("TTS: Groq Orpheus")
                        speak_groq_orpheus(text)
                        return
                    except Exception as e:
                        log.warning(f"TTS: Groq failed ({e}) → Piper fallback")

                log.info("TTS: Piper local")
                speak_piper(text)
        finally:
            _tts_request_active.clear()
            _tts_request_lock.release()
    else:
        log.warning("TTS lock timeout — skipping sentence to prevent deadlock")
        return


def _ensure_tts_worker():
    """Start TTS worker thread if not running."""
    global _tts_worker_thread
    if _tts_worker_thread is None or not _tts_worker_thread.is_alive():
        # H2: Log restart
        if _tts_worker_thread is not None:
            log.warning("TTS worker was dead — restarting")
        _tts_worker_thread = threading.Thread(target=_tts_worker, daemon=True)
        _tts_worker_thread.start()


def speak_stream(sentence_iter):
    """
    Feed an iterable of sentences into the TTS queue.
    Returns immediately — worker thread handles playback.
    IS_VOICE_ACTIVE stays True until queue drains.
    FIX 9: Non-blocking queue.put_nowait() with drop on overflow.
    """
    config.IS_VOICE_ACTIVE = True
    _tts_active.set()
    try:
        _ensure_tts_worker()
    except Exception as e:
        log.error(f"speak_stream: worker start failed ({e}) — aborting TTS")
        _tts_active.clear()
        config.IS_VOICE_ACTIVE = False
        return
    for sentence in sentence_iter:
        if sentence.strip():
            try:
                _tts_queue.put_nowait(sentence)
            except queue.Full:
                log.warning("TTS queue full — dropping sentence")
    _tts_queue.put(None)  # poison pill


def speak(text: str):
    """
    Speak a full text response, split into sentence-level chunks.
    Blocks until all speech finishes (for backward compatibility with orchestrator).
    """
    sentences = _split_sentences(text)

    config.IS_VOICE_ACTIVE = True
    _tts_active.set()
    log.debug("TTS active — mic muted")

    try:
        for sentence in sentences:
            speak_sentence(sentence)
    except Exception as e:
        log.error(f"TTS failed: {e}")
    finally:
        time.sleep(0.15)  # hardware settle
        config.IS_VOICE_ACTIVE = False
        _tts_active.clear()
        log.debug("TTS finished — mic unmuted")


def _split_sentences(text: str) -> list[str]:
    """Split text into sentences of ≥6 words at . ? ! boundaries."""
    parts = re.split(r'(?<=[.?!])\s+', text.strip())
    result = []
    buf = ""
    for part in parts:
        buf = (buf + " " + part).strip() if buf else part
        if len(buf.split()) >= 3:
            result.append(buf)
            buf = ""
    if buf:
        result.append(buf)
    return result if result else [text]


# ──────────────────────────────────────────────
# Public helpers
# ──────────────────────────────────────────────
def is_speaking() -> bool:
    return _tts_active.is_set()


def start_barge_in_monitor(on_interrupt_callback):
    """
    Run VAD in background while EDITH speaks via desktop audio.
    5 consecutive speech frames triggers TTS interrupt + callback.
    """
    def _monitor():
        try:
            import pyaudio
            import webrtcvad
            pa = pyaudio.PyAudio()
            vad = webrtcvad.Vad(3)
            stream = pa.open(rate=16000, channels=1, format=pyaudio.paInt16,
                             input=True, frames_per_buffer=320)
            consecutive_speech = 0
            SPEECH_FRAMES_NEEDED = 5
            while _tts_active.is_set() and _barge_in_active.is_set():
                try:
                    frame = stream.read(320, exception_on_overflow=False)
                    if vad.is_speech(frame, 16000):
                        consecutive_speech += 1
                        if consecutive_speech >= SPEECH_FRAMES_NEEDED:
                            log.info("Barge-in detected — interrupting TTS")
                            _tts_active.clear()
                            try:
                                _tts_queue.put_nowait(None)
                            except Exception:
                                pass
                            try:
                                import signal as _sig
                                with _aplay_pid_lock:
                                    _pid = _aplay_pid
                                if _pid:
                                    try:
                                        os.kill(_pid, _sig.SIGTERM)
                                    except (ProcessLookupError, OSError):
                                        pass
                                else:
                                    import subprocess as _sp
                                    _sp.run(["pkill", "-f", "aplay"], capture_output=True)
                            except Exception:
                                pass
                            try:
                                from agent import interrupt_agent
                                interrupt_agent()
                            except Exception:
                                pass
                            try:
                                on_interrupt_callback()
                            except Exception as e:
                                log.warning(f"Barge-in callback error: {e}")
                            break
                    else:
                        consecutive_speech = 0
                except Exception:
                    break
            try:
                stream.stop_stream()
                stream.close()
                pa.terminate()
            except Exception:
                pass
        except Exception as e:
            log.warning(f"Barge-in monitor error: {e}")
        finally:
            _barge_in_active.clear()

    _barge_in_active.set()
    t = threading.Thread(target=_monitor, daemon=True)
    t.start()
    return t


def stop_barge_in_monitor():
    """Stop the barge-in VAD thread."""
    _barge_in_active.clear()


# ──────────────────────────────────────────────
# STT listen loop
# ──────────────────────────────────────────────
def listen(timeout_seconds: int = 30) -> str:
    """
    Record until 2 seconds of silence, then transcribe.
    - Waits for TTS to finish before opening mic (VAD mute guard).
    - 200ms silence after wake word detection before recording starts.
    - Tries Groq STT; falls back to local on failure.
    """
    import webrtcvad
    import wave

    if _tts_active.is_set():
        log.info("Waiting for TTS to finish before listening...")
        _tts_active.wait()
        time.sleep(0.1)

    # 200ms wake-word bleed prevention
    time.sleep(0.2)

    MIC_IN_USE.set()
    config.IS_VOICE_ACTIVE = True

    print("🎤 Listening...")

    # H6: Use configurable VAD_AGGRESSIVENESS
    vad = webrtcvad.Vad(config.VAD_AGGRESSIVENESS)
    sample_rate = 16000
    frame_duration = 30
    frame_size = int(sample_rate * frame_duration / 1000)

    import pyaudio
    devnull = os.open(os.devnull, os.O_WRONLY)
    old_stderr = os.dup(2)
    os.dup2(devnull, 2)
    pa = pyaudio.PyAudio()
    stream = pa.open(format=pyaudio.paInt16, channels=1, rate=sample_rate,
                     input=True, frames_per_buffer=frame_size)
    os.dup2(old_stderr, 2)
    os.close(devnull)

    frames = []
    silent_frames = 0
    speaking = False
    max_silent_frames = int(800 / frame_duration)
    max_total_frames = int(timeout_seconds * 1000 / frame_duration)
    total_frames = 0
    speech_start_time = None

    while True:
        if _tts_active.is_set():
            log.info("TTS started during listen — aborting recording")
            # H5: Discard frames on TTS interrupt
            frames = []
            log.info("Frames discarded due to TTS interrupt")
            break
        frame = stream.read(frame_size, exception_on_overflow=False)
        is_speech = vad.is_speech(frame, sample_rate)
        total_frames += 1
        if is_speech:
            if not speaking:
                speech_start_time = time.time()
            speaking = True
            silent_frames = 0
            frames.append(frame)
        elif speaking:
            silent_frames += 1
            frames.append(frame)
            # M4: Dynamic silence timeout based on speech duration
            if speech_start_time:
                speech_duration_ms = (time.time() - speech_start_time) * 1000
                dynamic_timeout = 600 if speech_duration_ms < 2000 else 1500
                dynamic_silent_frames = int(dynamic_timeout / frame_duration)
                if silent_frames > dynamic_silent_frames:
                    log.debug(f"Dynamic silence timeout (speech={speech_duration_ms:.0f}ms, timeout={dynamic_timeout}ms)")
                    break
        if total_frames > max_total_frames:
            log.info("Listen timeout reached")
            break

    stream.stop_stream()
    stream.close()
    pa.terminate()

    config.IS_VOICE_ACTIVE = False  # recording done; TTS will set it again if speaking
    MIC_IN_USE.clear()

    if not frames:
        return ""

    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
        rec_file = f.name

    import wave as _wave
    with _wave.open(rec_file, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(b"".join(frames))

    import audioop
    rms = audioop.rms(b"".join(frames), 2)
    if rms < 300:
        log.info(f"Audio too quiet (RMS={rms}) — skipping STT")
        try:
            os.unlink(rec_file)
        except OSError:
            pass
        return ""

    print("🔄 Transcribing...")
    try:
        transcript = transcribe(rec_file)
    finally:
        try:
            os.unlink(rec_file)
        except OSError:
            pass

    transcript = re.sub(r'\bedith\b', 'EDITH', transcript, flags=re.IGNORECASE)
    print(f"📝 You said: {transcript}")
    return transcript
