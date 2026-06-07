"""
tests/test_streaming_memory.py

Integration tests for Task 5 — Inject memory_context into streaming action DispatchContext.

Validates:
- When recall/recall_episodes are mocked, the DispatchContext constructed for action intents
  has non-empty memory_context (requirement 1.1, 2.1)
- Graceful degradation: when recall raises RuntimeError, no exception propagates and
  memory_context defaults to "" (requirement 3.3)
"""

import asyncio
import sys
import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Ensure EDITH root is on the path so imports resolve
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _run(coro):
    """Run a coroutine in a fresh event loop."""
    return asyncio.get_event_loop().run_until_complete(coro)


async def _invoke_action_branch(user_input: str, recall_fn, recall_episodes_fn):
    """
    Simulate just the memory-injection portion of the streaming action branch,
    as written in event_generator after the fix.

    Returns the _action_memory_context string that would be passed to DispatchContext.
    """
    import importlib
    import asyncio as _asyncio

    # We test the exact pattern used in routes.chat event_generator
    _action_memory_context = ""
    try:
        _a_memories = await _asyncio.to_thread(recall_fn, user_input)
        _a_episodes = await _asyncio.to_thread(recall_episodes_fn, user_input, 1)
        _a_mem_list = (
            [m["value"] for m in _a_memories if isinstance(m, dict) and "value" in m]
            or _a_memories
        )
        _action_memory_context = "\n".join(str(m) for m in _a_mem_list) if _a_mem_list else ""
        if _a_episodes:
            _action_memory_context += f"\n\nPast Session: {_a_episodes[0]}"
    except Exception:
        pass  # graceful degradation — _action_memory_context stays ""

    return _action_memory_context


# ---------------------------------------------------------------------------
# Test 1 — Memory is injected when recall returns results
# ---------------------------------------------------------------------------

def test_action_memory_context_is_populated_when_recall_returns_data():
    """
    When recall returns [{"value": "user wants 7 emails"}] and recall_episodes
    returns [], the _action_memory_context must be non-empty.

    Validates: Requirements 1.1, 2.1
    """
    recall_mock = MagicMock(return_value=[{"value": "user wants 7 emails"}])
    recall_episodes_mock = MagicMock(return_value=[])

    result = _run(_invoke_action_branch(
        user_input="check my email",
        recall_fn=recall_mock,
        recall_episodes_fn=recall_episodes_mock,
    ))

    assert result != "", "memory_context should be non-empty when recall returns data"
    assert "user wants 7 emails" in result, (
        f"Expected memory value in context, got: {result!r}"
    )


# ---------------------------------------------------------------------------
# Test 2 — Episodes are appended when recall_episodes returns data
# ---------------------------------------------------------------------------

def test_action_memory_context_includes_episodes():
    """
    When recall_episodes returns a non-empty list, the episode is appended
    to _action_memory_context under 'Past Session:'.
    """
    recall_mock = MagicMock(return_value=[{"value": "user prefers inbox limit 10"}])
    recall_episodes_mock = MagicMock(return_value=["Last time user asked about unread emails"])

    result = _run(_invoke_action_branch(
        user_input="check inbox",
        recall_fn=recall_mock,
        recall_episodes_fn=recall_episodes_mock,
    ))

    assert "Past Session:" in result, "Episode should be appended under 'Past Session:'"
    assert "Last time user asked about unread emails" in result


# ---------------------------------------------------------------------------
# Test 3 — Graceful degradation: recall raises RuntimeError
# ---------------------------------------------------------------------------

def test_action_memory_context_defaults_to_empty_on_recall_error():
    """
    When recall raises RuntimeError, no exception propagates to the caller and
    _action_memory_context defaults to "".

    Validates: Requirement 3.3 (graceful degradation)
    """
    def _broken_recall(query):
        raise RuntimeError("ChromaDB unavailable")

    recall_episodes_mock = MagicMock(return_value=[])

    # Should not raise
    result = _run(_invoke_action_branch(
        user_input="check my email",
        recall_fn=_broken_recall,
        recall_episodes_fn=recall_episodes_mock,
    ))

    assert result == "", (
        f"memory_context should default to '' on recall error, got: {result!r}"
    )


# ---------------------------------------------------------------------------
# Test 4 — Validate the live routes.chat module patches correctly
# ---------------------------------------------------------------------------

def test_routes_chat_action_branch_patches_recall(monkeypatch):
    """
    Patch recall/recall_episodes into routes.chat and verify that invoking the
    action-intent path produces a DispatchContext with non-empty memory_context.

    This is a lightweight unit-level integration test that doesn't spin up FastAPI.
    """
    captured_contexts = []

    # Patch DispatchContext to capture constructor kwargs
    original_dispatch_context_init = None
    from context import DispatchContext as _RealDC

    class _CapturingDC(_RealDC):
        def __init__(self, **kwargs):
            captured_contexts.append(dict(kwargs))
            super().__init__(**kwargs)

    import routes.chat as _chat_module

    # Patch the DispatchContext used inside routes.chat
    monkeypatch.setattr(_chat_module, "DispatchContext", _CapturingDC)

    # Patch recall / recall_episodes inside routes.chat's orchestrator import
    recall_mock = MagicMock(return_value=[{"value": "user wants 7 emails"}])
    recall_episodes_mock = MagicMock(return_value=[])

    import orchestrator as _orch
    monkeypatch.setattr(_orch, "recall", recall_mock)
    monkeypatch.setattr(_orch, "recall_episodes", recall_episodes_mock)

    # Also patch dispatch to avoid actual handler execution
    import intent_dispatch as _id
    monkeypatch.setattr(_id, "dispatch", MagicMock(return_value="mock result"))

    # Build a minimal fake request object
    async def _fake_json():
        return {"message": "check my email", "session_id": None}

    fake_request = MagicMock()
    fake_request.json = _fake_json

    # Run the endpoint
    async def _call():
        from fastapi.responses import StreamingResponse
        response = await _chat_module.chat_stream_endpoint(fake_request)
        if hasattr(response, "body_iterator"):
            # Consume SSE stream to trigger generator
            async for _ in response.body_iterator:
                pass
        return response

    _run(_call())

    # Verify a DispatchContext was constructed (at least one capture)
    assert len(captured_contexts) >= 1, "DispatchContext was never constructed"

    # Find the context(s) with source="stream" (the action branch)
    stream_contexts = [c for c in captured_contexts if c.get("source") == "stream"]
    assert len(stream_contexts) >= 1, (
        f"No stream DispatchContext found. Captured: {captured_contexts}"
    )

    action_ctx = stream_contexts[0]
    assert action_ctx.get("memory_context") != "", (
        f"memory_context should be non-empty for action intent, got: {action_ctx!r}"
    )
    assert "user wants 7 emails" in action_ctx.get("memory_context", ""), (
        f"Expected memory value in action DispatchContext, got: {action_ctx!r}"
    )


# ---------------------------------------------------------------------------
# Test 5 — Graceful degradation in live routes.chat module
# ---------------------------------------------------------------------------

def test_routes_chat_action_branch_empty_memory_on_recall_error(monkeypatch):
    """
    When recall raises RuntimeError, the streaming endpoint should still respond
    (no exception propagates) and memory_context defaults to "".

    Validates: Requirement 3.3
    """
    captured_contexts = []

    from context import DispatchContext as _RealDC

    class _CapturingDC(_RealDC):
        def __init__(self, **kwargs):
            captured_contexts.append(dict(kwargs))
            super().__init__(**kwargs)

    import routes.chat as _chat_module

    monkeypatch.setattr(_chat_module, "DispatchContext", _CapturingDC)

    import orchestrator as _orch
    monkeypatch.setattr(_orch, "recall", MagicMock(side_effect=RuntimeError("ChromaDB down")))
    monkeypatch.setattr(_orch, "recall_episodes", MagicMock(return_value=[]))

    import intent_dispatch as _id
    monkeypatch.setattr(_id, "dispatch", MagicMock(return_value="mock result"))

    async def _fake_json():
        return {"message": "check my email", "session_id": None}

    fake_request = MagicMock()
    fake_request.json = _fake_json

    async def _call():
        from fastapi.responses import StreamingResponse
        response = await _chat_module.chat_stream_endpoint(fake_request)
        if hasattr(response, "body_iterator"):
            async for _ in response.body_iterator:
                pass
        return response

    # Should not raise
    _run(_call())

    stream_contexts = [c for c in captured_contexts if c.get("source") == "stream"]
    assert len(stream_contexts) >= 1, (
        f"No stream DispatchContext found. Captured: {captured_contexts}"
    )

    action_ctx = stream_contexts[0]
    assert action_ctx.get("memory_context") == "", (
        f"memory_context should be '' on recall error, got: {action_ctx!r}"
    )
