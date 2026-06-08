"""
tests/test_validate_tool_output.py

Unit tests for _validate_tool_output in intent_dispatch.py.

Property 4: Empty-output logging
Validates: Requirements 1.4, 2.4
"""

import sys
import os
import logging

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from intent_dispatch import _validate_tool_output


# ── Helper ────────────────────────────────────────────────────────────────────

def capture_warnings(caplog, fn, *args, **kwargs):
    """Run fn and return (result, warning_records)."""
    with caplog.at_level(logging.WARNING, logger="intent_dispatch"):
        result = fn(*args, **kwargs)
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    return result, warnings


# ── Tests ─────────────────────────────────────────────────────────────────────

def test_empty_string_returns_fallback(caplog):
    """Empty output returns the fallback message."""
    result, _ = capture_warnings(caplog, _validate_tool_output, "", "email", "some_handler")
    assert "email" in result
    assert result == "I couldn't get a result for email right now, Boss."


def test_whitespace_only_returns_fallback(caplog):
    """Whitespace-only output is treated as empty."""
    result, _ = capture_warnings(caplog, _validate_tool_output, "   \n\t  ", "weather", "some_handler")
    assert result == "I couldn't get a result for weather right now, Boss."


def test_empty_output_emits_warning_with_handler_name(caplog):
    """Empty output triggers a WARNING log containing handler name and intent.

    **Property 4: Empty-output logging**
    **Validates: Requirements 1.4, 2.4**
    """
    _, warnings = capture_warnings(caplog, _validate_tool_output, "", "email", "some_handler")
    assert len(warnings) >= 1
    warning_text = warnings[0].getMessage()
    assert "some_handler" in warning_text
    assert "email" in warning_text


def test_empty_output_emits_warning_with_intent_when_no_handler(caplog):
    """When handler_name is empty, the intent name appears in the warning."""
    _, warnings = capture_warnings(caplog, _validate_tool_output, "", "calendar_today", "")
    assert len(warnings) >= 1
    warning_text = warnings[0].getMessage()
    assert "calendar_today" in warning_text


def test_nonempty_output_does_not_emit_warning(caplog):
    """Non-empty output passes through with no warning emitted.

    **Property 4: Empty-output logging**
    **Validates: Requirements 1.4, 2.4**
    """
    _, warnings = capture_warnings(caplog, _validate_tool_output, "You have 3 emails.", "email", "some_handler")
    assert warnings == []


def test_nonempty_output_returned_unchanged(caplog):
    """Output shorter than 4000 chars is returned as-is."""
    payload = "You have 3 unread emails."
    result, _ = capture_warnings(caplog, _validate_tool_output, payload, "email", "some_handler")
    assert result == payload


def test_long_output_truncated(caplog):
    """Output exceeding 4000 chars is truncated with a trailer."""
    long_payload = "x" * 5000
    result, _ = capture_warnings(caplog, _validate_tool_output, long_payload, "email", "some_handler")
    assert result.endswith("... [truncated]")
    assert len(result) < 5000


def test_output_exactly_4000_chars_not_truncated(caplog):
    """Output at exactly 4000 chars is NOT truncated."""
    payload = "y" * 4000
    result, _ = capture_warnings(caplog, _validate_tool_output, payload, "email", "some_handler")
    assert result == payload
    assert "truncated" not in result


def test_default_handler_name_is_empty_string(caplog):
    """handler_name defaults to empty string — backward-compatible call still works."""
    result, warnings = capture_warnings(caplog, _validate_tool_output, "", "search")
    # Should still return fallback and emit a warning
    assert "search" in result
    assert len(warnings) >= 1
