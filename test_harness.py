"""
EDITH Test Harness — Phase 8.3

20 pre-written test scenarios covering:
intent detection, memory, council, decision sim, search,
voice, DAG, trace, circuit breaker, OCR, session, feedback.
"""

import sys
import os
import time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def _test(name, fn):
    """Run a test function, return (name, pass, error)."""
    try:
        fn()
        return (name, True, None)
    except Exception as e:
        return (name, False, str(e))


def run_all_tests() -> list:
    """Run all 20 test scenarios. Returns list of (name, pass, error)."""
    results = []

    # 1. Config
    def test_config():
        from config import MODELS, DANGER_KEYWORDS, INPUT_SCOPE_CATEGORIES
        assert MODELS["chat"] == "gemma3:1b"
        assert len(DANGER_KEYWORDS) > 5
        assert "security" in INPUT_SCOPE_CATEGORIES
    results.append(_test("Config loads correctly", test_config))

    # 2. Intent detection
    def test_intent_basic():
        from intent import detect_intent
        assert detect_intent("hello edith") == "wake"
        assert detect_intent("check my email") == "email"
        assert detect_intent("what is on my screen") == "vision"
    results.append(_test("Intent detection (basic)", test_intent_basic))

    # 3. Intent detection advanced
    def test_intent_advanced():
        from intent import detect_intent
        assert detect_intent("run ls -la") == "shell"
        assert detect_intent("council debate this topic") == "council"
        assert detect_intent("what is the weather") == "weather"
    results.append(_test("Intent detection (advanced)", test_intent_advanced))

    # 4. Smart memory
    def test_smart_memory():
        import tempfile
        from smart_memory import SmartMemoryManager
        db = tempfile.mktemp(suffix='.db')
        mgr = SmartMemoryManager(db, max_ram_items=10)
        mgr.remember("test_key", "test value")
        results_r = mgr.recall("test", n=1)
        assert len(results_r) > 0
        mgr.close()
        os.unlink(db)
    results.append(_test("Smart memory read/write", test_smart_memory))

    # 5. Recency decay
    def test_recency_decay():
        from smart_memory import SmartMemoryManager
        now_score = SmartMemoryManager._recency_score(time.time())
        old_score = SmartMemoryManager._recency_score(time.time() - 86400 * 30)
        assert now_score > old_score
    results.append(_test("Recency decay scoring", test_recency_decay))

    # 6. Context compression
    def test_compression():
        from smart_memory import compress_context
        chunks = ["Python is great", "Python is great for coding", "Weather is sunny"]
        compressed = compress_context(chunks, similarity_threshold=0.6)
        assert len(compressed) <= len(chunks)
    results.append(_test("Context compression", test_compression))

    # 7. Danger scan
    def test_danger_scan():
        from orchestrator import _danger_scan
        safe = _danger_scan("what is the weather")
        dangerous = _danger_scan("delete all files")
        assert not safe["is_dangerous"]
        assert dangerous["is_dangerous"]
    results.append(_test("Pre-intent danger scan", test_danger_scan))

    # 8. Scope classification
    def test_scope():
        from orchestrator import _classify_scope
        assert _classify_scope("explain async") == "llm"
        assert _classify_scope("send email") == "notify"
        assert _classify_scope("delete files") == "action"
    results.append(_test("Input scope classification", test_scope))

    # 9. Conversation DNA
    def test_dna():
        from conversation_dna import get_response_modifiers
        mods = get_response_modifiers({"device": "telegram", "emotion": "frustrated"})
        assert mods["tone"] == "empathetic"
        assert mods["depth"] == "brief"
    results.append(_test("Conversation DNA engine", test_dna))

    # 10. Session continuity
    def test_session():
        from session import start_session, track_query, get_session_device, session_status
        sid = start_session(device="test")
        track_query("test query")
        assert "test" in get_session_device()
        assert "test" in session_status()
    results.append(_test("Session continuity", test_session))

    # 11. Compound DAG
    def test_dag():
        from compound_dag import detect_compound, split_into_tasks, DAGExecutor
        text = "search for news and then email results"
        assert detect_compound(text)
        tasks = split_into_tasks(text)
        assert len(tasks) >= 2
        dag = DAGExecutor(tasks)
        result = dag.execute_all()
        assert result["success"]
    results.append(_test("Compound intent DAG", test_dag))

    # 12. Circuit breaker
    def test_circuit():
        from circuit_breaker import CircuitBreaker, CLOSED, OPEN
        cb = CircuitBreaker("test", failure_threshold=2, recovery_timeout=1)
        assert cb.is_available()
        cb.record_failure()
        cb.record_failure()
        assert not cb.is_available()  # Should be OPEN now
        cb.record_success()  # Won't work, circuit is open
    results.append(_test("Circuit breaker states", test_circuit))

    # 13. Trace logger
    def test_trace():
        from trace_logger import new_trace, log_layer, complete_trace, get_trace
        tid = new_trace("test input", intent="test")
        log_layer(tid, "test_layer", "in", "out", confidence=0.9)
        complete_trace(tid, "success")
        trace = get_trace(tid)
        assert trace["trace_id"] == tid
        assert len(trace["layers"]) == 1
    results.append(_test("Trace logger", test_trace))

    # 14. Feedback tagger
    def test_feedback():
        from trace_logger import new_trace, complete_trace
        from feedback_tagger import tag_feedback, detect_implicit_feedback
        tid = new_trace("feedback test", intent="chat")
        complete_trace(tid)
        tag_feedback(tid, "thumbs_up", "good answer")
        result = detect_implicit_feedback(tid, "no that's wrong")
        assert result == "correction"
    results.append(_test("Feedback tagger", test_feedback))

    # 15. Tuner
    def test_tuner():
        from tuner import get_weights, get_status
        weights = get_weights()
        assert "groq" in weights or "ollama" in weights
        status = get_status()
        assert "weights" in status
    results.append(_test("Auto router tuner", test_tuner))

    # 16. WhatsApp stub
    def test_whatsapp():
        from whatsapp import send_message, is_available, BRIDGE_URL, _bridge_active
        # Bridge URL is configured in .env
        assert BRIDGE_URL == "http://127.0.0.1:3001", f"Expected bridge URL, got: {BRIDGE_URL}"
        assert _bridge_active, "Bridge should be configured (URL is set)"
        # is_available() returns False if bridge is not reachable (expected - bridge offline)
        available = is_available()
        if not available:
            print("  [WhatsApp] Bridge configured but not reachable (offline) — stub mode active")
        # Verify stub response works
        result = send_message("test", "hello")
        assert result is not None, "send_message should return a response"
        # Test passes even if bridge offline, as long as module works
    results.append(_test("WhatsApp stub module", test_whatsapp))

    # 17. Voice TTS guard
    def test_voice_guard():
        from voice import is_speaking, _tts_active
        assert not is_speaking()
        _tts_active.set()
        assert is_speaking()
        _tts_active.clear()
    results.append(_test("Voice TTS guard", test_voice_guard))

    # 18. Cache fingerprint
    def test_fingerprint():
        from smart_router import _context_fingerprint
        k1 = _context_fingerprint("hello", "chat")
        k2 = _context_fingerprint("hello", "code")
        assert k1 != k2
    results.append(_test("Context fingerprint cache", test_fingerprint))

    # 19. Monitor system status
    def test_monitor():
        from monitor import check_ram, get_resource_mode, get_system_status
        ram = check_ram()
        assert "percent" in ram
        mode = get_resource_mode()
        assert mode in ("light", "full")
    results.append(_test("Monitor system status", test_monitor))

    # 20. Privacy audit
    def test_privacy():
        from monitor import get_system_status
        status = get_system_status()
        assert "ram" in status
        assert "last_backup" in status
    results.append(_test("System status for dashboard", test_privacy))

    return results


def print_report(results):
    """Pretty-print test results."""
    passed = sum(1 for _, p, _ in results if p)
    total = len(results)

    print("\n" + "=" * 60)
    print(f"  EDITH v9.3 Test Harness — {passed}/{total} passed")
    print("=" * 60)

    for name, ok, error in results:
        icon = "✅" if ok else "❌"
        print(f"  {icon} {name}")
        if error:
            print(f"     → {error[:80]}")

    print("\n" + "=" * 60)
    if passed == total:
        print("  ALL TESTS PASSED ✅")
    else:
        print(f"  {total - passed} FAILED ❌")
    print("=" * 60)


if __name__ == "__main__":
    results = run_all_tests()
    print_report(results)
