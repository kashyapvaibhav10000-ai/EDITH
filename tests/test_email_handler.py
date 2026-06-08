"""
tests/test_email_handler.py

Unit tests for _parse_limit, _handle_email, and _handle_unread_email
in handlers/email.py.

Property 2: Context-aware email limit
Validates: Requirements 1.2, 2.2
"""

import sys
import os
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from handlers.email import _parse_limit, _handle_email, _handle_unread_email
from context import DispatchContext


# ── _parse_limit unit tests ───────────────────────────────────────────────────

def test_parse_limit_from_user_input():
    """Explicit integer in user_input is returned.

    **Property 2: Context-aware email limit**
    **Validates: Requirements 1.2, 2.2**
    """
    assert _parse_limit("show me 10 emails", "", 5) == 10


def test_parse_limit_falls_back_to_memory_context():
    """When user_input has no number, memory_context is scanned.

    **Property 2: Context-aware email limit**
    **Validates: Requirements 1.2, 2.2**
    """
    assert _parse_limit("check email", "user prefers 8 emails", 5) == 8


def test_parse_limit_returns_default_when_no_number():
    """Default is returned when neither source contains a number."""
    assert _parse_limit("check email", "", 5) == 5


def test_parse_limit_out_of_range_clamped_to_default():
    """Numbers outside 1–50 are rejected and the default is returned.

    **Property 2: Context-aware email limit**
    **Validates: Requirements 1.2, 2.2**
    """
    assert _parse_limit("200 emails please", "", 5) == 5


def test_parse_limit_no_numbers_anywhere():
    """No numeric content in either field returns the default."""
    assert _parse_limit("emails", "lots of context but no numbers", 5) == 5


def test_parse_limit_user_input_takes_priority_over_memory():
    """user_input is scanned before memory_context — user_input wins.

    **Property 2: Context-aware email limit**
    **Validates: Requirements 1.2, 2.2**
    """
    assert _parse_limit("show me 3 emails", "user normally wants 15", 5) == 3


def test_parse_limit_boundary_value_1():
    """Lowest valid value (1) is accepted."""
    assert _parse_limit("show 1 email", "", 5) == 1


def test_parse_limit_boundary_value_50():
    """Highest valid value (50) is accepted."""
    assert _parse_limit("get 50 emails", "", 5) == 50


def test_parse_limit_value_51_is_rejected():
    """51 is just outside the valid range and should fall back to default."""
    assert _parse_limit("51 emails", "", 5) == 5


# ── _handle_email with mocked check_inbox ────────────────────────────────────

def test_handle_email_passes_limit_from_user_input():
    """_handle_email extracts limit from user_input and passes it to check_inbox.

    **Property 2: Context-aware email limit**
    **Validates: Requirements 1.2, 2.2**
    """
    mock_result = MagicMock()
    mock_result.ok = True
    mock_result.value = "inbox results"

    ctx = DispatchContext(
        user_input="get 7 emails",
        intent="email",
        memory_context="",
    )

    with patch("email_reader.check_inbox", return_value=mock_result) as mock_inbox:
        _handle_email(ctx)

    mock_inbox.assert_called_once_with(limit=7, unread_only=False)


# ── _handle_unread_email with mocked check_inbox ─────────────────────────────

def test_handle_unread_email_passes_limit_from_memory_context():
    """_handle_unread_email extracts limit from memory_context when user_input has none.

    **Property 2: Context-aware email limit**
    **Validates: Requirements 1.2, 2.2**
    """
    mock_result = MagicMock()
    mock_result.ok = True
    mock_result.value = "unread results"

    ctx = DispatchContext(
        user_input="check email",
        intent="unread_email",
        memory_context="preferred count: 3",
    )

    with patch("email_reader.check_inbox", return_value=mock_result) as mock_inbox:
        _handle_unread_email(ctx)

    mock_inbox.assert_called_once_with(limit=3, unread_only=True)


def test_handle_email_uses_default_when_no_limit_specified():
    """_handle_email uses default limit of 5 when no number is found."""
    mock_result = MagicMock()
    mock_result.ok = True
    mock_result.value = "inbox results"

    ctx = DispatchContext(
        user_input="check my email",
        intent="email",
        memory_context="",
    )

    with patch("email_reader.check_inbox", return_value=mock_result) as mock_inbox:
        _handle_email(ctx)

    mock_inbox.assert_called_once_with(limit=5, unread_only=False)


def test_handle_unread_email_uses_default_when_no_limit_specified():
    """_handle_unread_email uses default limit of 5 when no number is found."""
    mock_result = MagicMock()
    mock_result.ok = True
    mock_result.value = "unread results"

    ctx = DispatchContext(
        user_input="show unread",
        intent="unread_email",
        memory_context="",
    )

    with patch("email_reader.check_inbox", return_value=mock_result) as mock_inbox:
        _handle_unread_email(ctx)

    mock_inbox.assert_called_once_with(limit=5, unread_only=True)
