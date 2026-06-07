"""
tests/test_followup_routing.py

Unit tests for Task 6 — contextual follow-up detection and response grounding.

6.1  _is_followup: contextual-follow-up branch added by Fix 3
6.2  _handle_followup: system prompt injection for contextual_followup type

Validates: Requirements 1.3, 2.3
Property 3: Follow-up grounding
"""

import sys
import os
from unittest.mock import patch, MagicMock
from collections import OrderedDict

# Ensure EDITH root is on path so imports resolve
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

# ──────────────────────────────────────────────────────────────────────────────
# Helpers to seed widget history
# ──────────────────────────────────────────────────────────────────────────────

def _seed_history(bot_content: str, bot_intent: str = "email"):
    """
    Seed shared_state._widget_history with one user turn and one bot turn so
    that _get_last_exchange() returns a realistic (last_user, last_bot) pair.
    """
    import shared_state
    with shared_state._widget_history_lock:
        shared_state._widget_history.clear()
        shared_state._widget_history[0] = {
            "role": "user",
            "content": "check my email",
            "intent": "email",
        }
        shared_state._widget_history[1] = {
            "role": "assistant",
            "content": bot_content,
            "intent": bot_intent,
        }


# ──────────────────────────────────────────────────────────────────────────────
# 6.1  _is_followup — contextual detection
# Validates: Requirements 1.3, 2.3
# Property 3: Follow-up grounding
# ──────────────────────────────────────────────────────────────────────────────

class TestIsFollowupContextual:
    """**Validates: Requirements 1.3, 2.3**"""

    def setup_method(self):
        # Seed history before each test so _get_last_exchange returns a bot msg
        _seed_history("You have 3 unread emails from Boss.", "email")

    def test_why_detected_as_contextual_followup(self):
        from routes.chat import _is_followup
        is_fu, fu_type = _is_followup("why")
        assert is_fu is True
        assert fu_type == "contextual_followup"

    def test_explain_that_detected_as_contextual_followup(self):
        from routes.chat import _is_followup
        is_fu, fu_type = _is_followup("explain that")
        assert is_fu is True
        assert fu_type == "contextual_followup"

    def test_tell_me_more_detected_as_contextual_followup(self):
        from routes.chat import _is_followup
        is_fu, fu_type = _is_followup("tell me more")
        assert is_fu is True
        assert fu_type == "contextual_followup"

    def test_check_calendar_is_not_a_followup(self):
        from routes.chat import _is_followup
        is_fu, fu_type = _is_followup("check my calendar")
        assert is_fu is False

    def test_yes_still_returns_confirmation(self):
        """Existing confirmation behaviour must be unaffected."""
        from routes.chat import _is_followup
        is_fu, fu_type = _is_followup("yes")
        assert is_fu is True
        assert fu_type == "confirmation"

    def test_elaborate_detected_as_contextual_followup(self):
        from routes.chat import _is_followup
        is_fu, fu_type = _is_followup("elaborate")
        assert is_fu is True
        assert fu_type == "contextual_followup"

    def test_explain_more_detected_as_contextual_followup(self):
        from routes.chat import _is_followup
        is_fu, fu_type = _is_followup("explain more")
        assert is_fu is True
        assert fu_type == "contextual_followup"

    def test_how_so_detected_as_contextual_followup(self):
        from routes.chat import _is_followup
        is_fu, fu_type = _is_followup("how so")
        assert is_fu is True
        assert fu_type == "contextual_followup"

    def test_go_on_detected_as_contextual_followup(self):
        from routes.chat import _is_followup
        is_fu, fu_type = _is_followup("go on")
        assert is_fu is True
        assert fu_type == "contextual_followup"

    def test_continue_detected_as_contextual_followup(self):
        from routes.chat import _is_followup
        is_fu, fu_type = _is_followup("continue")
        assert is_fu is True
        assert fu_type == "contextual_followup"


# ──────────────────────────────────────────────────────────────────────────────
# 6.2  _handle_followup — system prompt injection
# Validates: Requirements 1.3, 2.3
# Property 3: Follow-up grounding
# ──────────────────────────────────────────────────────────────────────────────

class TestHandleFollowupSystemPromptInjection:
    """**Validates: Requirements 1.3, 2.3**"""

    def setup_method(self):
        _seed_history("You have 5 emails", "email")

    def test_system_prompt_contains_prior_result(self):
        """
        When _handle_followup is called with fu_type='contextual_followup',
        smart_router.smart_call must receive a 'system' kwarg that contains
        the prior bot message content.
        """
        captured = {}

        def fake_smart_call(query, intent=None, system=None, **kwargs):
            captured["system"] = system
            captured["query"] = query
            return "Here is more context."

        with patch("smart_router.smart_call", side_effect=fake_smart_call):
            from routes.chat import _handle_followup
            reply, replied_intent = _handle_followup("why", "contextual_followup")

        assert "system" in captured, "smart_call was not called with a system kwarg"
        assert "You have 5 emails" in captured["system"], (
            f"Prior bot content not found in system prompt. Got:\n{captured['system']}"
        )

    def test_reply_returned_from_smart_call(self):
        """The return value of smart_call becomes the reply."""
        with patch("smart_router.smart_call", return_value="Extra context here."):
            from routes.chat import _handle_followup
            reply, _ = _handle_followup("explain that", "contextual_followup")
        assert reply == "Extra context here."

    def test_fallback_reply_when_smart_call_returns_none(self):
        """If smart_call returns None/empty, a safe fallback string is returned."""
        with patch("smart_router.smart_call", return_value=None):
            from routes.chat import _handle_followup
            reply, _ = _handle_followup("why", "contextual_followup")
        assert isinstance(reply, str)
        assert len(reply) > 0

    def test_returned_intent_is_prior_bot_intent(self):
        """The intent returned should reflect the prior bot message's intent."""
        with patch("smart_router.smart_call", return_value="Sure."):
            from routes.chat import _handle_followup
            _, returned_intent = _handle_followup("tell me more", "contextual_followup")
        assert returned_intent == "email"

    def test_query_passed_to_smart_call_contains_user_input(self):
        """The query forwarded to smart_call should include the user's follow-up text."""
        captured = {}

        def fake_smart_call(query, intent=None, system=None, **kwargs):
            captured["query"] = query
            return "ok"

        with patch("smart_router.smart_call", side_effect=fake_smart_call):
            from routes.chat import _handle_followup
            _handle_followup("why are there 5?", "contextual_followup")

        assert "why are there 5?" in captured.get("query", ""), (
            f"User input not found in query. Got: {captured.get('query')}"
        )
