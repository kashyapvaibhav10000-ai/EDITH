"""
handlers/helpers.py — Shared extraction and safety helpers used across handler modules.
"""

import re
import os
import datetime

from config import get_user_dir, USER_HOME

_SAFE_COMMANDS = {
    "ls", "ll", "dir", "cat", "head", "tail", "wc", "df", "du", "free",
    "uname", "whoami", "hostname", "date", "cal", "uptime", "which",
    "file", "stat", "pwd", "echo", "tree", "find", "locate",
    "neofetch", "lsb_release", "lscpu", "lsusb", "lspci",
}


def extract_date(text):
    lower = text.lower()
    today = datetime.date.today()
    if "tomorrow" in lower or "tommorrow" in lower:
        return (today + datetime.timedelta(days=1)).strftime("%Y-%m-%d")
    if "today" in lower:
        return today.strftime("%Y-%m-%d")
    if "day after tomorrow" in lower:
        return (today + datetime.timedelta(days=2)).strftime("%Y-%m-%d")
    m = re.search(r"(\d{4})-(\d{2})-(\d{2})", text)
    if m:
        return m.group(0)
    m = re.search(r"(\d{1,2})[/\-](\d{1,2})", text)
    if m:
        day, month = int(m.group(1)), int(m.group(2))
        return f"{today.year}-{month:02d}-{day:02d}"
    days_map = {"monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3,
                "friday": 4, "saturday": 5, "sunday": 6}
    for name, num in days_map.items():
        if name in lower:
            days_ahead = num - today.weekday()
            if days_ahead <= 0:
                days_ahead += 7
            return (today + datetime.timedelta(days=days_ahead)).strftime("%Y-%m-%d")
    return today.strftime("%Y-%m-%d")


def extract_time(text):
    m = re.search(r"(\d{1,2})(?::(\d{2}))?\s*(am|pm)", text.lower())
    if m:
        hour = int(m.group(1))
        minute = int(m.group(2) or 0)
        if m.group(3) == "pm" and hour != 12:
            hour += 12
        if m.group(3) == "am" and hour == 12:
            hour = 0
        return f"{hour:02d}:{minute:02d}"
    m = re.search(r"(\d{1,2}):(\d{2})", text)
    if m:
        return f"{int(m.group(1)):02d}:{int(m.group(2)):02d}"
    return None


def extract_event_title(text):
    cleaned = re.sub(
        r"(add|create|schedule|set|make|book|remind me|to|for|at|on|tomorrow|today|am|pm|\d{1,2}:\d{2}|\d{1,2}\s*(am|pm))",
        "", text, flags=re.IGNORECASE
    ).strip()
    cleaned = re.sub(r"^(a|an|the|about|for|to)\s+", "", cleaned, flags=re.IGNORECASE).strip()
    return cleaned.capitalize() if cleaned and len(cleaned) > 2 else "New Event"


def extract_filepath(text):
    m = re.search(r"(/[^\s]+\.\w+)", text)
    if m:
        return m.group(1)
    m = re.search(r"(~/[^\s]+)", text)
    if m:
        return os.path.expanduser(m.group(1))
    return None


def extract_phone_number(text):
    m = re.search(r"(\+?\d[\d\s\-]{8,14}\d)", text)
    return re.sub(r"[\s\-]", "", m.group(1)) if m else None


def extract_sms_body(text):
    m = re.search(
        r"(?:saying|message|text|that says|with)\s+[\"']?(.+?)[\"']?\s*$",
        text, re.IGNORECASE
    )
    return m.group(1).strip() if m else None


def is_safe_command(cmd):
    base_cmd = cmd.strip().split()[0] if cmd.strip() else ""
    base_cmd = os.path.basename(base_cmd)
    if any(c in cmd for c in ['>', '|', '&&', '||', ';', '`', '$(']):
        return False
    return base_cmd in _SAFE_COMMANDS
