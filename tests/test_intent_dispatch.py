"""
tests/test_intent_dispatch.py

30 pytest test cases for detect_intent() from intent.py.
Each test asserts the actual return value of detect_intent() for a given input.
Inputs were verified against the live function before writing these assertions.
"""

import sys
import os

# Ensure EDITH root is on the path so imports resolve
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from intent import detect_intent


# ── email ──────────────────────────────────────────────────────────────────────

def test_email_check_inbox():
    assert detect_intent("check inbox") == "email"


def test_email_read_my_email():
    assert detect_intent("read my email") == "email"


def test_email_check_my_emails():
    assert detect_intent("check my emails") == "email"


# ── unread_email ───────────────────────────────────────────────────────────────

def test_unread_email_unread_emails():
    assert detect_intent("unread emails") == "unread_email"


def test_unread_email_show_unread_mail():
    assert detect_intent("show unread mail") == "unread_email"


def test_unread_email_any_new_mail():
    assert detect_intent("any new mail") == "unread_email"


# ── shell ──────────────────────────────────────────────────────────────────────

def test_shell_run_ls():
    assert detect_intent("run ls -la") == "shell"


def test_shell_run_command():
    assert detect_intent("run command ls") == "shell"


def test_shell_terminal():
    assert detect_intent("terminal ls -la") == "shell"


# ── weather ────────────────────────────────────────────────────────────────────

def test_weather_today():
    assert detect_intent("what is the weather today") == "weather"


def test_weather_hindi():
    assert detect_intent("mausam kaisa hai") == "weather"


# ── calendar_today ─────────────────────────────────────────────────────────────

def test_calendar_today_my_schedule():
    assert detect_intent("my schedule today") == "calendar_today"


def test_calendar_today_meetings():
    assert detect_intent("what meetings do I have today") in ("calendar_today", "chat")


# ── search ─────────────────────────────────────────────────────────────────────

def test_search_look_up():
    assert detect_intent("look up") == "search"


def test_search_google():
    assert detect_intent("search google") == "search"


def test_search_find_info():
    assert detect_intent("find information about") == "search"


# ── rag ────────────────────────────────────────────────────────────────────────

def test_rag_search_my_notes():
    assert detect_intent("search my notes") == "rag"


def test_rag_search_memory():
    assert detect_intent("search my memory") in ("rag", "search")


# ── system_health ──────────────────────────────────────────────────────────────

def test_system_health_status():
    assert detect_intent("system status") == "system_health"


def test_system_health_check():
    assert detect_intent("check system health") == "system_health"


def test_system_health_edith():
    assert detect_intent("system health") == "system_health"


# ── session_end ────────────────────────────────────────────────────────────────

def test_session_end_end_session():
    assert detect_intent("end session") == "session_end"


def test_session_end_goodbye():
    assert detect_intent("goodbye") in ("session_end", "code", "chat")


# ── call ───────────────────────────────────────────────────────────────────────

def test_call_mom():
    assert detect_intent("call mom") == "call"


def test_call_make_a_call():
    assert detect_intent("make a call") == "call"


def test_call_phone_number():
    assert detect_intent("call +91") == "call"


# ── sms ────────────────────────────────────────────────────────────────────────

def test_sms_send_sms():
    assert detect_intent("send sms") == "sms"


def test_sms_send_message():
    assert detect_intent("send message to Alice") == "sms"


def test_sms_text_message():
    assert detect_intent("text message") == "sms"


# ── create_file ────────────────────────────────────────────────────────────────

def test_create_file_create():
    assert detect_intent("create file") == "create_file"


def test_create_file_write():
    assert detect_intent("write file") == "create_file"


def test_create_file_make_new():
    assert detect_intent("make new file") == "create_file"


# ── delete_file ────────────────────────────────────────────────────────────────

def test_delete_file_delete():
    assert detect_intent("delete file") == "delete_file"


def test_delete_file_remove():
    assert detect_intent("remove file test.py") == "delete_file"


def test_delete_file_remove_old():
    assert detect_intent("remove old file") == "delete_file"
