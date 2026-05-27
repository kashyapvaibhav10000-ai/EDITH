"""
Dashboard Backend - System Statistics & Status Collection

Provides functions for gathering system metrics, active models, and EDITH modules status.
Used by the legacy dashboard server for monitoring.
"""

import subprocess
import json
import os
import psutil
from config import EDITH_PATH, get_logger

log = get_logger("dashboard_backend")


def get_system_stats():
    """Collect current system memory, CPU, and disk statistics."""
    mem = psutil.virtual_memory()
    cpu = psutil.cpu_percent(interval=0.1)
    disk = psutil.disk_usage('/')
    return {
        "ram_used": round(mem.used / 1024**3, 1),
        "ram_total": round(mem.total / 1024**3, 1),
        "ram_percent": mem.percent,
        "cpu_percent": cpu,
        "disk_used": round(disk.used / 1024**3, 1),
        "disk_total": round(disk.total / 1024**3, 1),
        "disk_percent": disk.percent,
    }

def get_recent_logs():
    """Fetch last 8 lines from security audit log."""
    log_path = os.path.join(EDITH_PATH, "logs", "security_audit.log")
    try:
        with open(log_path) as f:
            lines = f.readlines()
        return [l.strip() for l in lines[-8:] if l.strip()]
    except:
        return ["No logs yet"]


def get_edith_modules():
    """Get list of EDITH key modules and their availability status."""
    edith_path = EDITH_PATH
    modules = []
    key_files = [
        ("orchestrator.py", "Orchestrator"),
        ("smart_memory.py", "Memory"),
        ("rag.py", "RAG"),
        ("agent.py", "Agent"),
        ("monitor.py", "Monitor"),
        ("vision.py", "Vision"),
        ("edith_email.py", "Email"),
        ("video_summarizer.py", "Video"),
        ("image_gen.py", "Image Gen"),
        ("code_rag.py", "Code RAG"),
        ("ml_router.py", "ML Router"),
        ("vault.py", "Vault"),
        ("security_audit.py", "Security"),
        ("voice.py", "Voice"),
        ("search.py", "Search"),
        ("calendar_reader.py", "Calendar"),
    ]
    for fname, label in key_files:
        exists = os.path.exists(os.path.join(edith_path, fname))
        modules.append({"name": label, "active": exists})
    return modules


def get_mcp_status():
    """Get MCP (Model Context Protocol) server status."""
    try:
        import mcp_bridge
        return mcp_bridge.get_mcp_status()
    except Exception:
        return {}
