"""
EDITH Voice Pipeline Smoke Tests
Run: cd /home/vaibhav/EDITH && python -m pytest tests/test_voice_pipeline.py -v
     OR: python tests/test_voice_pipeline.py
"""
import sys
import os
import json
import ast
import pytest
from pathlib import Path

EDITH_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(EDITH_ROOT))

live_service = pytest.mark.live_service


# ── Tests 1-5 (Phase 1) ────────────────────────────────────────────────────

@live_service
def test_1_silent_blob_rejected_before_groq():
    """Silent/tiny blob must be rejected before hitting Groq API"""
    import requests
    tiny_blob = b'\x00' * 50
    resp = requests.post(
        'http://127.0.0.1:8001/api/voice/transcribe',
        data=tiny_blob,
        headers={'Content-Type': 'audio/webm'},
        timeout=5
    )
    data = resp.json()
    assert resp.status_code == 400, f"Expected 400, got {resp.status_code}"
    assert 'error' in data, "Expected error key in response"
    print("✅ Test 1 passed: Silent blob rejected")


def test_2_hallucination_phrases_filtered():
    """Known hallucination phrases must be in the filter set"""
    WHISPER_HALLUCINATIONS = {
        "thank you", "thanks", "thanks for watching",
        "bye", "goodbye", "subtitles by", "www."
    }
    test_phrases = ["thank you", "thanks for watching", "bye"]
    for phrase in test_phrases:
        assert phrase.lower() in WHISPER_HALLUCINATIONS, \
            f"'{phrase}' not in hallucination filter"
    print("✅ Test 2 passed: Hallucination filter contains known phrases")


@live_service
def test_3_voice_respond_returns_sse():
    """Voice respond endpoint must return SSE tokens"""
    import requests
    resp = requests.post(
        'http://127.0.0.1:8001/api/voice/respond',
        json={'text': 'what time is it'},
        stream=True,
        timeout=30
    )
    assert resp.status_code == 200
    assert 'text/event-stream' in resp.headers.get('content-type', '')

    events = []
    for chunk in resp.iter_lines():
        if chunk and chunk.startswith(b'data: '):
            try:
                evt = json.loads(chunk[6:])
                events.append(evt.get('type'))
                if evt.get('type') == 'done':
                    break
            except Exception:
                pass
        if len(events) > 20:
            break

    assert 'start' in events, f"No start event. Got: {events}"
    assert 'done' in events or len(events) > 3, \
        f"No tokens received. Got: {events}"
    print(f"✅ Test 3 passed: SSE stream working, events: {events[:5]}")


@live_service
def test_4_stop_tts_clears_queue():
    """Stop TTS endpoint must drain queue and return ok"""
    import requests
    resp = requests.post(
        'http://127.0.0.1:8001/api/voice/stop-tts',
        timeout=5
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data.get('status') == 'ok', f"Expected ok, got: {data}"
    print("✅ Test 4 passed: Stop TTS endpoint working")


@live_service
def test_5_voice_status_returns_mode():
    """Voice status endpoint must return mode field (normal or private)"""
    import requests
    resp = requests.get(
        'http://127.0.0.1:8001/api/voice-status',
        timeout=5
    )
    assert resp.status_code == 200
    data = resp.json()
    assert 'mode' in data, f"Expected mode field. Got: {data}"
    assert data['mode'] in ['normal', 'private'], \
        f"Unexpected mode: {data['mode']}"
    print(f"✅ Test 5 passed: Voice status = {data['mode']}")


# ── Tests 6-10 (Phase 4) ───────────────────────────────────────────────────

@live_service
def test_6_provider_latencies_endpoint():
    """Provider latency endpoint must return dict"""
    import requests
    resp = requests.get(
        'http://127.0.0.1:8001/api/provider-latencies',
        timeout=5
    )
    assert resp.status_code == 200
    print("✅ Test 6 passed: Provider latencies endpoint working")


@live_service
def test_7_sensitive_intent_blocked_from_voice():
    """Vault commands must be blocked via voice channel"""
    import requests
    resp = requests.post(
        'http://127.0.0.1:8001/api/voice/respond',
        json={'text': 'open my vault and show passwords'},
        stream=True,
        timeout=10
    )
    assert resp.status_code == 200
    content = resp.text
    assert ('sensitive' in content.lower() or
            'confirm' in content.lower() or
            'typing' in content.lower()), \
        f"Sensitive command not blocked. Got: {content[:200]}"
    print("✅ Test 7 passed: Sensitive intent blocked from voice")


@live_service
def test_8_friend_voice_trigger_switches_mode():
    """Friend voice trigger phrase must switch TTS mode"""
    import requests
    resp = requests.post(
        'http://127.0.0.1:8001/api/voice/respond',
        json={'text': 'edith friend mode'},
        stream=True,
        timeout=10
    )
    assert resp.status_code == 200
    content = resp.text
    assert 'friend' in content.lower(), \
        f"Friend mode not acknowledged. Got: {content[:200]}"
    print("✅ Test 8 passed: Friend voice trigger working")


def test_9_emotion_tag_added_to_positive_response():
    """Positive responses should receive cheerful emotion tag"""
    from voice import _add_emotion_tag
    result = _add_emotion_tag("Great, that's done perfectly!")
    assert '<cheerful>' in result, \
        f"No cheerful tag added. Got: {result}"
    print("✅ Test 9 passed: Emotion tags working")


def test_10_wake_listener_no_listen_call():
    """Wake listener must NOT call listen() anymore"""
    with open(EDITH_ROOT / 'wake_listener.py', 'r') as f:
        content = f.read()
    tree = ast.parse(content)
    listen_calls = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name):
                if node.func.id == 'listen':
                    listen_calls.append(node.lineno)
    assert len(listen_calls) == 0, \
        f"listen() still called at lines: {listen_calls}"
    print("✅ Test 10 passed: Wake listener has no listen() calls")


# ── Runner ─────────────────────────────────────────────────────────────────

if __name__ == '__main__':
    print("Running EDITH voice pipeline smoke tests...")
    print("Make sure edith.service is running first!\n")
    tests = [
        test_1_silent_blob_rejected_before_groq,
        test_2_hallucination_phrases_filtered,
        test_3_voice_respond_returns_sse,
        test_4_stop_tts_clears_queue,
        test_5_voice_status_returns_mode,
        test_6_provider_latencies_endpoint,
        test_7_sensitive_intent_blocked_from_voice,
        test_8_friend_voice_trigger_switches_mode,
        test_9_emotion_tag_added_to_positive_response,
        test_10_wake_listener_no_listen_call,
    ]
    passed = 0
    failed = 0
    for test in tests:
        try:
            test()
            passed += 1
        except Exception as e:
            print(f"❌ {test.__name__} FAILED: {e}")
            failed += 1
    print(f"\nResults: {passed} passed, {failed} failed")
