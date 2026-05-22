"""
EDITH Integration Tests — Item 11

Covers:
  - All FastAPI endpoints (health, chat, status, feedback, validator)
  - Intent routing correctness
  - DAG compound dispatch
  - Result contract for all modified modules
  - Event bus pub/sub
  - DB pool connectivity

Run:
    cd /home/vaibhav/EDITH
    source ../edith-env/bin/activate
    python -m pytest test/test_integration.py -v
"""

import os
import sys
import json
import time
import threading
import pytest
from unittest.mock import patch, MagicMock, Mock

pytestmark = pytest.mark.integration

# ── path setup ──
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# ──────────────────────────────────────────────
# Fixtures
# ──────────────────────────────────────────────
@pytest.fixture(scope="session")
def client():
    """FastAPI TestClient — starts app in-process, mocks external I/O."""
    from fastapi.testclient import TestClient

    os.environ["EDITH_API_KEY"] = "test-api-key"

    # Patch vault/Telegram/Ollama so tests don't need real credentials
    with patch("vault.get_secret", return_value=""), \
         patch("vault.set_secret", return_value=True), \
         patch("telegram_bot.send_telegram", return_value=True):
        from chat_server import app
        with TestClient(app, raise_server_exceptions=False) as c:
            c.headers.update({"X-API-Key": "test-api-key"})
            yield c


@pytest.fixture(scope="session")
def mock_chat_fn():
    return lambda prompt, intent=None: f"[mock] {prompt[:40]}"


# ──────────────────────────────────────────────
# 1. FastAPI Endpoints
# ──────────────────────────────────────────────
class TestAPIEndpoints:
    def test_root_returns_html(self, client):
        r = client.get("/")
        assert r.status_code == 200
        assert "html" in r.headers.get("content-type", "").lower()

    def test_system_status_200(self, client):
        r = client.get("/api/system-status")
        assert r.status_code == 200

    def test_api_status_200(self, client):
        r = client.get("/api/status")
        assert r.status_code in (200, 500)  # 500 OK if Ollama offline in CI

    def test_chat_endpoint_requires_body(self, client):
        r = client.post("/api/chat", json={})
        # Missing 'message' field — should 422 or handle gracefully
        assert r.status_code in (200, 422)

    def test_chat_endpoint_with_message(self, client):
        with patch("chat_server.dispatch", return_value="test response"):
            r = client.post("/api/chat", json={"message": "hello"})
        assert r.status_code == 200
        data = r.json()
        assert "response" in data or "message" in data or "reply" in data

    def test_feedback_endpoint(self, client):
        r = client.post("/api/feedback", json={
            "message": "test",
            "response": "test response",
            "rating": "good"
        })
        assert r.status_code in (200, 201, 422)

    def test_validator_via_health_intent(self, client):
        with patch("chat_server.dispatch") as mock:
            mock.return_value = "7/7 systems operational"
            r = client.post("/api/chat", json={"message": "system health check"})
        assert r.status_code == 200


# ──────────────────────────────────────────────
# 2. Intent Routing
# ──────────────────────────────────────────────
class TestIntentRouting:
    def setup_method(self):
        from intent import detect_intent
        self.detect = detect_intent

    def test_weather_intent(self):
        assert self.detect("what's the weather like") == "weather"

    def test_search_intent(self):
        assert self.detect("search for latest AI news") == "search"

    def test_email_intent(self):
        assert self.detect("check my email") == "email"

    def test_calendar_today_intent(self):
        assert self.detect("what's my schedule today") == "calendar_today"

    def test_call_intent(self):
        assert self.detect("call +919876543210") == "call"

    def test_phone_ring_intent(self):
        assert self.detect("ring my phone") == "phone"

    def test_vision_intent(self):
        assert self.detect("what is on my screen") == "vision"

    def test_system_health_intent(self):
        assert self.detect("system health check") == "system_health"

    def test_agent_intent(self):
        assert self.detect("agent do this task for me") == "agent"

    def test_chat_fallback(self):
        # Mock LLM fallback — test that non-keyword query stays in chat family
        with patch("intent.classify_intent_via_llm", return_value="chat"):
            intent = self.detect("recommend a book for me to read this weekend")
        assert intent in ("chat", "search", "lookup", "reason")

    def test_wake_intent(self):
        assert self.detect("wake up edith") == "wake"


# ──────────────────────────────────────────────
# 3. DAG Compound Dispatch
# ──────────────────────────────────────────────
class TestDAGDispatch:
    def test_detect_compound_true(self):
        from compound_dag import detect_compound
        assert detect_compound("check weather and then check email") is True

    def test_detect_compound_false(self):
        from compound_dag import detect_compound
        assert detect_compound("what is the weather today") is False

    def test_split_into_tasks(self):
        from compound_dag import split_into_tasks
        parts = split_into_tasks("search AI news then check my calendar")
        assert len(parts) >= 2

    def test_dag_executor_returns_result(self):
        from compound_dag import DAGExecutor
        from errors import Result

        dag = DAGExecutor(["task1", "task2"])
        r = dag.execute_all()
        assert isinstance(r, Result)
        assert r.ok  # dry-run always succeeds

    def test_compound_dispatch_routes_to_dag(self, mock_chat_fn):
        from intent_dispatch import dispatch
        from context import DispatchContext

        with patch("weather.get_current_weather") as mock_w:
            from errors import Result
            mock_w.return_value = Result.success({
                "city": "Test", "region": "TR", "temp": 25,
                "feels_like": 26, "humidity": 50, "wind_speed": 10,
                "description": "Clear", "emoji": "☀️", "weather_code": 0
            })
            ctx = DispatchContext(
                user_input="check weather and tell me a joke",
                intent="chat",
                chat_fn=mock_chat_fn,
                source="test"
            )
            result = dispatch(ctx)

        assert "step" in result.lower() or "clear" in result.lower() or len(result) > 10


# ──────────────────────────────────────────────
# 4. Result Contract
# ──────────────────────────────────────────────
class TestResultContract:
    def test_result_success(self):
        from errors import Result
        r = Result.success("hello")
        assert r.ok
        assert r.value == "hello"
        assert r.error == ""

    def test_result_failure(self):
        from errors import Result
        r = Result.failure("broken", error_type="connection")
        assert not r.ok
        assert r.error == "broken"
        assert r.error_type == "connection"

    def test_result_from_exception(self):
        from errors import Result
        r = Result.from_exception(ValueError("bad value"))
        assert not r.ok
        assert "bad value" in r.error

    def test_weather_returns_result(self):
        from errors import Result
        with patch("requests.get") as mock_get:
            mock_resp = MagicMock()
            mock_resp.raise_for_status = lambda: None
            mock_resp.json.return_value = {
                "current": {
                    "temperature_2m": 25.0, "apparent_temperature": 26.0,
                    "relative_humidity_2m": 50, "wind_speed_10m": 10.0,
                    "weather_code": 0
                }
            }
            mock_get.return_value = mock_resp
            from weather import get_current_weather
            r = get_current_weather()
        assert isinstance(r, Result)
        assert r.ok
        assert "temp" in r.value

    def test_search_returns_result(self):
        from errors import Result
        with patch("search._search_searxng", return_value=None), \
             patch("search._search_duckduckgo", return_value=None), \
             patch("search._check_quota", return_value=False):
            from search import web_search
            r = web_search("test query")
        assert isinstance(r, Result)
        # Either success with results or failure — both are valid Results
        assert hasattr(r, "ok")

    def test_rag_build_index_returns_result(self):
        from errors import Result
        import tempfile, os
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch("rag.NOTES_DIR", tmpdir):
                from rag import build_index
                r = build_index()
        assert isinstance(r, Result)

    def test_data_analyst_returns_result(self):
        from errors import Result
        from data_analyst import analyze_file
        r = analyze_file("/nonexistent/file.csv")
        assert isinstance(r, Result)
        assert not r.ok


# ──────────────────────────────────────────────
# 5. Event Bus
# ──────────────────────────────────────────────
class TestEventBus:
    def test_pub_sub_sync(self):
        from event_bus import EventBus, Topic

        sync_bus = EventBus(async_dispatch=False)
        received = []

        @sync_bus.subscribe(Topic.SYSTEM_ALERT)
        def handler(payload):
            received.append(payload["message"])

        r = sync_bus.publish(Topic.SYSTEM_ALERT, {"message": "test-alert"})
        assert r.ok
        assert received == ["test-alert"]

    def test_rate_and_history(self):
        from event_bus import EventBus, Topic

        bus = EventBus(async_dispatch=False)
        bus.publish(Topic.AGENT_DONE, {"task": "t1", "state": "done"})
        bus.publish(Topic.AGENT_DONE, {"task": "t2", "state": "failed"})
        history = bus.get_history(topic=Topic.AGENT_DONE, limit=5)
        assert len(history) == 2

    def test_unsubscribe(self):
        from event_bus import EventBus, Topic

        bus = EventBus(async_dispatch=False)
        hits = []

        def handler(p): hits.append(1)
        bus.subscribe_fn(Topic.WAKE, handler)
        bus.publish(Topic.WAKE, {})
        bus.unsubscribe(Topic.WAKE, handler)
        bus.publish(Topic.WAKE, {})
        assert hits == [1]  # Only fired once


# ──────────────────────────────────────────────
# 6. DB Pool
# ──────────────────────────────────────────────
class TestDBPool:
    def test_connection_context_manager(self, tmp_path):
        import db_pool
        db_path = str(tmp_path / "test.db")
        with db_pool.connection(db_path) as conn:
            conn.execute("CREATE TABLE t (x TEXT)")
            conn.execute("INSERT INTO t VALUES ('hello')")
            conn.commit()
            row = conn.execute("SELECT x FROM t").fetchone()
        assert row["x"] == "hello"

    def test_pool_reuse(self, tmp_path):
        import db_pool
        db_path = str(tmp_path / "reuse.db")
        conn1 = db_pool.get(db_path)
        db_pool.put(db_path, conn1)
        conn2 = db_pool.get(db_path)
        assert conn1 is conn2  # Same object returned from pool
        db_pool.put(db_path, conn2)

    def test_concurrent_writes(self, tmp_path):
        import db_pool
        db_path = str(tmp_path / "concurrent.db")
        with db_pool.connection(db_path) as conn:
            conn.execute("CREATE TABLE t (id INTEGER PRIMARY KEY, val TEXT)")
            conn.commit()

        errors = []
        def worker(n):
            try:
                with db_pool.connection(db_path) as c:
                    c.execute("INSERT INTO t (val) VALUES (?)", (f"w{n}",))
                    c.commit()
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(10)]
        for t in threads: t.start()
        for t in threads: t.join()

        assert len(errors) == 0
        with db_pool.connection(db_path) as conn:
            count = conn.execute("SELECT COUNT(*) FROM t").fetchone()[0]
        assert count == 10


# ──────────────────────────────────────────────
# 7. Validator
# ──────────────────────────────────────────────
class TestValidator:
    def test_validate_all_returns_dict_of_results(self):
        from validator import validate_all
        from errors import Result
        results = validate_all()
        assert isinstance(results, dict)
        assert len(results) > 0
        for name, r in results.items():
            assert isinstance(r, Result), f"{name} should return Result"

    def test_format_health_report(self):
        from validator import validate_all, format_health_report
        results = validate_all()
        report = format_health_report(results)
        assert "EDITH System Health" in report
        assert "operational" in report

    def test_validate_disk_ok(self):
        from validator import validate_disk
        r = validate_disk()
        assert r.ok  # Should be OK in dev environment (44GB free)

    def test_validate_memory_ok(self):
        from validator import validate_memory
        r = validate_memory()
        assert r.ok


# ──────────────────────────────────────────────
# 8. Agent State Machine
# ──────────────────────────────────────────────
class TestAgentStateMachine:
    def test_agent_state_transitions(self):
        from agent import AgentRunner, AgentState
        runner = AgentRunner("test task", task_id="test_sm_01")
        assert runner.run.state == AgentState.PLANNING

    def test_agent_db_persistence(self):
        from agent import AgentRunner, _load_run, AgentState
        runner = AgentRunner("persist test", task_id="test_persist_01")
        loaded = _load_run("test_persist_01")
        assert loaded is not None
        assert loaded.task == "persist test"
        assert loaded.state == AgentState.PLANNING

    def test_is_dangerous(self):
        from agent import is_dangerous
        assert is_dangerous("rm -rf /")
        assert is_dangerous("dd if=/dev/zero of=/dev/sda")
        assert not is_dangerous("ls /home/vaibhav")
        assert not is_dangerous("cat /etc/hostname")

    def test_compute_confidence(self):
        from agent import compute_confidence
        # Safe known command → high confidence
        score = compute_confidence("ls /home/vaibhav/files", "list the files")
        assert 0.0 <= score <= 1.0
        # Dangerous → low confidence
        score_dangerous = compute_confidence("rm -rf /", "delete everything")
        assert score_dangerous < 0.5
