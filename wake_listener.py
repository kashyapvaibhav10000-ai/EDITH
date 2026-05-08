"""
EDITH Wake Listener — Always-On Background Daemon (Vosk Version)

Continuously listens to the microphone using Vosk (extremely low RAM/CPU).
When "hey edith" or variants are heard, triggers the greeting + opens a terminal.
"""

import os
import sys
import json
import time
import subprocess
import requests
from difflib import SequenceMatcher

# Add project to path
sys.path.insert(0, os.path.dirname(__file__))

from config import get_logger, VOSK_MODEL_PATH
from voice import MIC_IN_USE, _tts_active
import threading
import concurrent.futures

# ──────────────────────────────────────────────
# Cloud Bridge Configuration
# ──────────────────────────────────────────────
CLOUD_URL = os.getenv("CLOUD_URL", "http://localhost:8001")
LOCAL_BRIDGE_URL = os.getenv("LOCAL_BRIDGE_URL", "http://localhost:8002")
BRIDGE_SECRET = os.getenv("BRIDGE_SECRET", "")

log = get_logger("wake_listener")

_wake_executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)

# Hardware control events
PAUSE_EVENT = threading.Event()  # SET = stop listening, CLEAR = listen

# Cooldown: after a wake trigger, wait this many seconds before listening again
WAKE_COOLDOWN = 3

def is_fuzzy_match(recognized_text: str) -> bool:
    """Fuzzy matching to handle phonetic inaccuracies of Vosk."""
    text = recognized_text.lower().strip()
    if not text:
        return False
    
    # Exact or substring match of strong variants + phonetic mismatches from Vosk
    hard_matches = [
        "edith", "edit", "hey edith", "heyieth", "a edith",
        "aedith", "hey edit", "aye edith"
    ]
    for phrase in hard_matches:
        if phrase in text:
            return True
            
    # Fuzzy match threshold for "hey edith" (if string is garbled)
    ratio = SequenceMatcher(None, "hey edith", text).ratio()
    if ratio > 0.7:
        return True
        
    return False

def _trigger_wake_sequence():
    """
    New wake sequence (cloud-enabled):
    1. Speak greeting locally
    2. Enter transcription loop (Vosk local)
    3. POST transcribed text to cloud
    4. Receive response + speak via local_bridge
    """
    log.info("Wake word triggered — starting voice interaction")
    
    # Step 1: Speak greeting
    weather = ""
    try:
        from weather import get_weather_summary
        try:
            future = _wake_executor.submit(get_weather_summary)
            weather = future.result(timeout=2.0)
        except concurrent.futures.TimeoutError:
            log.warning("Weather fetch timeout — using empty string")
            weather = ""
    except Exception:
        weather = ""
    
    from datetime import datetime
    hour = datetime.now().hour
    if hour < 12:
        time_greeting = "Good morning"
    elif hour < 17:
        time_greeting = "Good afternoon"
    else:
        time_greeting = "Good evening"
    
    greeting = f"{time_greeting}, Boss. EDITH online."
    if weather:
        greeting += f" {weather}"
    
    # Speak greeting via local bridge
    try:
        requests.post(
            f"{LOCAL_BRIDGE_URL}/speak",
            json={"text": greeting},
            headers={"X-Bridge-Token": BRIDGE_SECRET},
            timeout=5
        )
        log.info(f"Greeting spoken via local bridge: {greeting[:60]}")
    except requests.RequestException as e:
        log.warning(f"Local bridge speak failed: {e}")
    
    # Step 2: Enter transcription listening mode
    log.info("Waiting for voice input...")
    transcribed = _listen_for_user_input(timeout=30)  # 30 second timeout for user to speak
    
    if not transcribed:
        log.warning("No voice input detected")
        return
    
    log.info(f"Transcribed: '{transcribed[:80]}'")
    
    # Step 3: POST transcribed text to cloud
    try:
        response = requests.post(
            f"{CLOUD_URL}/api/chat",
            json={"message": transcribed, "source": "voice"},
            timeout=10
        )
        response.raise_for_status()
        result = response.json()
        cloud_reply = result.get("reply", "I didn't understand that.")
    except requests.RequestException as e:
        log.error(f"Cloud request failed: {e}")
        cloud_reply = "Connection to server failed. Please try again."
    except Exception as e:
        log.error(f"Error processing cloud response: {e}")
        cloud_reply = "Error processing response."
    
    # Step 4: Speak response via local bridge
    log.info(f"Cloud reply: {cloud_reply[:80]}")
    try:
        requests.post(
            f"{LOCAL_BRIDGE_URL}/speak",
            json={"text": cloud_reply},
            headers={"X-Bridge-Token": BRIDGE_SECRET},
            timeout=5
        )
    except requests.RequestException as e:
        log.error(f"Failed to speak cloud reply: {e}")
        # Fallback: try Piper locally if bridge is down
        _speak_fallback("Server error speaking response.")


def _listen_for_user_input(timeout: int = 30) -> str:
    """
    Listen to microphone and transcribe user speech via Vosk.
    Returns transcribed text when speech ends (detected by silence).
    """
    from vosk import Model, KaldiRecognizer, SetLogLevel
    
    SetLogLevel(-1)
    
    if not os.path.exists(VOSK_MODEL_PATH):
        log.error(f"Vosk model not found at {VOSK_MODEL_PATH}")
        return ""
    
    try:
        model = Model(VOSK_MODEL_PATH)
        rec = KaldiRecognizer(model, 16000)
        
        import pyaudio
        # Suppress PyAudio debug output
        devnull = os.open(os.devnull, os.O_WRONLY)
        old_stderr = os.dup(2)
        os.dup2(devnull, 2)
        pa = pyaudio.PyAudio()
        stream = pa.open(format=pyaudio.paInt16, channels=1, rate=16000, input=True, frames_per_buffer=4000)
        os.dup2(old_stderr, 2)
        os.close(devnull)
        
        stream.start_stream()
        log.debug("Transcription listening started...")
        
        accumulated_text = ""
        silence_frames = 0
        max_silence_frames = 30  # ~1.2 seconds of silence to end recording
        start_time = time.time()
        
        try:
            while True:
                if time.time() - start_time > timeout:
                    log.warning("Transcription timeout — returning accumulated text")
                    break
                
                data = stream.read(4000, exception_on_overflow=False)
                if len(data) == 0:
                    continue
                
                if rec.AcceptWaveform(data):
                    res = json.loads(rec.Result())
                    text = res.get("text", "").strip()
                    if text:
                        accumulated_text = text
                        log.debug(f"Partial: {text}")
                        silence_frames = 0  # Reset silence counter on new speech
                else:
                    partial = json.loads(rec.PartialResult())
                    partial_text = partial.get("result", [])
                    if partial_text:
                        silence_frames = 0  # Speech detected
                    else:
                        silence_frames += 1
                        if accumulated_text and silence_frames >= max_silence_frames:
                            log.debug("Silence detected — ending transcription")
                            break
        finally:
            stream.stop_stream()
            stream.close()
            pa.terminate()
        
        return accumulated_text
    except Exception as e:
        log.error(f"Transcription loop error: {e}")
        return ""


def _speak_fallback(text: str):
    """
    Fallback TTS if local_bridge is unavailable.
    Uses piper-tts directly.
    """
    try:
        # Try espeak-ng if available
        result = subprocess.run(
            ["espeak-ng", text],
            capture_output=True,
            timeout=5
        )
        if result.returncode == 0:
            log.info("Fallback: spoke via espeak-ng")
            return
    except Exception:
        pass
    
    # Fallback fallback: log only
    log.warning(f"Could not speak: '{text}' — no TTS available")


def pause():
    """Stop the wake listener from reading mic frames."""
    log.info("Wake listener paused.")
    PAUSE_EVENT.set()

def resume():
    """Resumed the wake listener."""
    log.info("Wake listener resumed.")
    PAUSE_EVENT.clear()

# S2: openwakeword neural model — fewer false positives than Vosk fuzzy match.
# Falls back to Vosk if openwakeword not installed.
_OWW_AVAILABLE = False
try:
    from openwakeword.model import Model as OWWModel  # type: ignore
    _OWW_AVAILABLE = True
    log.info("openwakeword available — will use neural wake detection")
except ImportError:
    log.info("openwakeword not installed — using Vosk fuzzy fallback (pip install openwakeword to upgrade)")


def _listen_loop_openwakeword():
    """S2: openwakeword neural wake-word detection loop."""
    import pyaudio
    import numpy as np

    oww = OWWModel(
        wakeword_models=["hey_jarvis"],  # closest available model — responds to "hey" pattern
        inference_framework="tflite",
    )

    devnull = os.open(os.devnull, os.O_WRONLY)
    old_stderr = os.dup(2)
    os.dup2(devnull, 2)
    pa = pyaudio.PyAudio()
    stream = pa.open(format=pyaudio.paInt16, channels=1, rate=16000, input=True, frames_per_buffer=1280)
    os.dup2(old_stderr, 2)
    os.close(devnull)

    stream.start_stream()
    log.info("Wake listener started (openwakeword neural) — listening for 'Hey EDITH'...")

    _SCORE_THRESHOLD = 0.5

    try:
        while True:
            if PAUSE_EVENT.is_set() or MIC_IN_USE.is_set() or _tts_active.is_set():
                if stream.is_active():
                    stream.stop_stream()
                time.sleep(0.5)
                continue

            if not stream.is_active():
                try:
                    stream.start_stream()
                except Exception as e:
                    log.warning(f"Could not restart stream: {e}")
                    time.sleep(1)
                    continue

            data = stream.read(1280, exception_on_overflow=False)
            if not data:
                continue

            audio = np.frombuffer(data, dtype=np.int16)
            prediction = oww.predict(audio)

            triggered = any(score >= _SCORE_THRESHOLD for score in prediction.values())
            if triggered:
                score_str = ", ".join(f"{k}:{v:.2f}" for k, v in prediction.items())
                log.info(f"[WAKE] 🎯 Neural wake word detected! ({score_str})")
                threading.Thread(target=_trigger_wake_sequence, daemon=True).start()
                log.info(f"Cooldown {WAKE_COOLDOWN}s...")
                time.sleep(WAKE_COOLDOWN)
    except KeyboardInterrupt:
        log.info("Wake listener stopped by user")
    finally:
        stream.stop_stream()
        stream.close()
        pa.terminate()


def _listen_loop_vosk():
    """Vosk fuzzy-match fallback wake-word loop."""
    from vosk import Model, KaldiRecognizer, SetLogLevel

    SetLogLevel(-1)

    if not os.path.exists(VOSK_MODEL_PATH):
        log.error(f"Vosk model not found at {VOSK_MODEL_PATH}")
        sys.exit(1)

    log.info("Loading Vosk Model...")
    model = Model(VOSK_MODEL_PATH)
    rec = KaldiRecognizer(model, 16000)

    import pyaudio
    devnull = os.open(os.devnull, os.O_WRONLY)
    old_stderr = os.dup(2)
    os.dup2(devnull, 2)
    pa = pyaudio.PyAudio()
    stream = pa.open(format=pyaudio.paInt16, channels=1, rate=16000, input=True, frames_per_buffer=4000)
    os.dup2(old_stderr, 2)
    os.close(devnull)

    stream.start_stream()
    log.info("Wake listener started (Vosk) — listening for 'Hey EDITH'...")

    try:
        while True:
            if PAUSE_EVENT.is_set() or MIC_IN_USE.is_set() or _tts_active.is_set():
                if stream.is_active():
                    stream.stop_stream()
                time.sleep(0.5)
                continue

            if not stream.is_active():
                try:
                    stream.start_stream()
                except Exception as e:
                    log.warning(f"Could not restart stream: {e}")
                    time.sleep(1)
                    continue

            data = stream.read(4000, exception_on_overflow=False)
            if len(data) == 0:
                continue

            if rec.AcceptWaveform(data):
                res = json.loads(rec.Result())
                text = res.get("text", "")
                if text:
                    log.debug(f"Heard: {text}")
                    if is_fuzzy_match(text):
                        log.info(f"[WAKE] 🎯 WAKE WORD DETECTED! (matched: '{text}')")
                        threading.Thread(target=_trigger_wake_sequence, daemon=True).start()
                        log.info(f"Cooldown {WAKE_COOLDOWN}s...")
                        time.sleep(WAKE_COOLDOWN)
                        rec.Reset()
                        log.debug("Vosk buffer flushed after cooldown")
    except KeyboardInterrupt:
        log.info("Wake listener stopped by user")
    finally:
        stream.stop_stream()
        stream.close()
        pa.terminate()


def listen_loop():
    """S2: Use openwakeword neural model if available, else Vosk fuzzy fallback."""
    if _OWW_AVAILABLE:
        _listen_loop_openwakeword()
    else:
        _listen_loop_vosk()


if __name__ == "__main__":
    listen_loop()
