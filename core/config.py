"""
EDITH Configuration — Single source of truth for all paths, models, and constants.
"""

import os
import sys
import logging
import re
import traceback
import threading
from pathlib import Path
import subprocess

# Load .env early so os.getenv works even without systemd EnvironmentFile
try:
    from dotenv import load_dotenv as _load_dotenv
    _env_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
    _load_dotenv(_env_file)
    if not os.path.exists(_env_file):
        logging.getLogger("config").warning("No .env file found — running on vault-only mode")
except Exception:
    pass

# ──────────────────────────────────────────────
# X11 Session Authentication (Systemd Fix)
# ──────────────────────────────────────────────
def _ensure_x11_auth():
    """Dynamically find and inject XAUTHORITY to allow systemd services to use GUI tools (Spectacle, pynput)."""
    if "XAUTHORITY" not in os.environ:
        try:
            user = os.environ.get("USER", "")
            if not user or not all(c.isalnum() or c in "_-" for c in user):
                return
            result = subprocess.run(
                ["pgrep", "-u", user, "-x", "kwin_x11,plasmashell,gnome-shell,xfce4-session"],
                capture_output=True, timeout=3
            )
            pids = result.stdout.decode().strip().split("\n")
            pid = pids[0].strip() if pids else ""
            if pid and pid.isdigit():
                with open(f"/proc/{pid}/environ", "rb") as f:
                    env_vars = f.read().split(b'\0')
                for var in env_vars:
                    if var.startswith(b"XAUTHORITY="):
                        os.environ["XAUTHORITY"] = var.split(b"=", 1)[1].decode()
                        break
        except Exception:
            pass

_ensure_x11_auth()


# ──────────────────────────────────────────────
# Intent Classification
# ──────────────────────────────────────────────
PRIVATE_INTENTS = {"vault", "shell", "email"}

# ──────────────────────────────────────────────
# Base Paths — Configurable for portability
# ──────────────────────────────────────────────
EDITH_PATH = os.path.dirname(os.path.abspath(__file__))
USER_HOME = os.path.expanduser("~")
SERVICE_VENV = os.getenv("SERVICE_VENV", os.path.join(USER_HOME, "edith-env"))
VENV_PATH = os.getenv("VENV_PATH", SERVICE_VENV)
VENV_PYTHON = os.getenv("VENV_PYTHON", os.path.join(VENV_PATH, "bin/python"))

# External service URLs (configurable)
LOCAL_BRIDGE_URL = os.getenv("LOCAL_BRIDGE_URL", "http://localhost:5000")
CHAT_SERVER_URL = os.getenv("CHAT_SERVER_URL", "http://localhost:8001")

# External project paths (defaults can be overridden via env or .local.json)
PROJECTS_BASE = os.getenv("PROJECTS_BASE", os.path.join(USER_HOME, "Documents"))
AYURSTOCK_PATH = os.getenv("AYURSTOCK_PATH", os.path.join(PROJECTS_BASE, "Ayur-stock pro"))

# ──────────────────────────────────────────────
# Voice (STT + TTS)
# ──────────────────────────────────────────────
PIPER_PATH = os.path.join(VENV_PATH, "bin/piper")
PIPER_MODEL = os.path.join(EDITH_PATH, "voices/en_GB-cori-high.onnx")

WHISPER_BACKEND = "whisper.cpp"
WHISPER_MODEL = "small"
WHISPER_MODEL_PATH = os.path.join(EDITH_PATH, "models/ggml-small.bin")
VOSK_MODEL_PATH = os.getenv("VOSK_MODEL_PATH", os.path.join(EDITH_PATH, "models/vosk"))

# H6: Voice activity detection aggressiveness (0=least aggressive, 3=most)
VAD_AGGRESSIVENESS = 3

# ──────────────────────────────────────────────
# Data / Storage Paths
# ──────────────────────────────────────────────
MEMORY_DB_PATH = os.path.join(EDITH_PATH, "memory_db")
MEMORY_ARCHIVE_PATH = os.path.join(EDITH_PATH, "memory_archive.db")

# ──────────────────────────────────────────────
# Smart Memory Configuration (Hot RAM + Cold Disk)
# ──────────────────────────────────────────────
SMART_MEMORY_MAX_RAM_ITEMS = 50  # Keep 50 recent memories in RAM
SMART_MEMORY_MAX_RAM_MB = 100     # Trigger GC if > 100MB (not strict limit)

# ──────────────────────────────────────────────
# Phase 2: Input Pipeline Configuration
# ──────────────────────────────────────────────
SMART_COMPRESSION = True          # Deduplicate overlapping RAG chunks before LLM call
CONTEXT_FINGERPRINT_ENABLED = True  # Use context-aware cache keys instead of simple hash
RECENCY_DECAY_HALFLIFE_DAYS = 14  # Memories older than this get half the weight

# Pre-intent danger scan keywords (checked BEFORE any LLM call)
DANGER_KEYWORDS = [
    "delete", "remove", "destroy", "format", "wipe", "erase", "drop",
    "rm -rf", "shutdown", "reboot", "kill", "terminate", "uninstall",
    "send money", "transfer funds", "execute", "run command",
    "overwrite", "replace all",
]

# Input scope categories for pre-intent range scanner
INPUT_SCOPE_CATEGORIES = {
    "device":   ["volume", "brightness", "wifi", "bluetooth", "screenshot", "lock", "unlock"],
    "security": ["password", "vault", "encrypt", "decrypt", "login", "credential", "secret"],
    "notify":   ["remind", "alert", "notify", "send", "text", "email", "sms", "message"],
    "llm":      ["explain", "analyze", "compare", "write", "summarize", "translate", "debate"],
    "action":   ["create", "delete", "run", "execute", "install", "move", "copy", "download"],
}

# ──────────────────────────────────────────────
# Shared ChromaDB Client (singleton — saves RAM)
# ──────────────────────────────────────────────
_chroma_client = None
_chroma_lock = threading.Lock()

def get_chroma_client(path=None):
    """Get the shared ChromaDB PersistentClient singleton. Thread-safe via double-checked locking."""
    global _chroma_client
    if _chroma_client is None:
        with _chroma_lock:
            if _chroma_client is None:
                import chromadb
                db_path = path or MEMORY_DB_PATH
                _chroma_client = chromadb.PersistentClient(path=db_path)
    return _chroma_client
NOTES_DIR = os.path.join(EDITH_PATH, "notes")
LOG_DIR = os.path.join(EDITH_PATH, "logs")
CHARTS_DIR = os.path.join(EDITH_PATH, "charts")

# ──────────────────────────────────────────────
# MCP (Model Context Protocol)
# ──────────────────────────────────────────────
MCP_CONFIG_PATH = os.path.join(EDITH_PATH, "mcp_config.json")
MCP_LOG_PATH    = os.path.join(EDITH_PATH, "logs", "mcp.log")
MCP_TIMEOUT     = 30
IMAGES_DIR = os.path.join(EDITH_PATH, "images")
DOWNLOADS_DIR = os.path.join(EDITH_PATH, "downloads")

# ──────────────────────────────────────────────
# Vault
# ──────────────────────────────────────────────
VAULT_PATH = os.path.join(EDITH_PATH, "vault.enc")
VAULT_SALT_PATH = os.path.join(EDITH_PATH, "vault.salt")

# ──────────────────────────────────────────────
# Email / Calendar
# ──────────────────────────────────────────────
CREDENTIALS_FILE = os.path.join(EDITH_PATH, "credentials.json")
TOKEN_JSON_FILE = os.path.join(EDITH_PATH, "token.json")
TOKEN_PICKLE_FILE = os.path.join(EDITH_PATH, "token.pickle")
GMAIL_PROVIDER = "gmail"

SEARXNG_URL = "http://localhost:8080/search"
DEVLOG_PATH = os.path.join(EDITH_PATH, "devlog.md")


# ──────────────────────────────────────────────
# Phone (KDE Connect)
# ──────────────────────────────────────────────
KDE_DEVICE_ID = "73517393415c46c9919085918cdccfe4"
CITY = "Fatehpur"

# ──────────────────────────────────────────────
# Code RAG
# ──────────────────────────────────────────────
CODE_DIRS = [
    EDITH_PATH,
    AYURSTOCK_PATH,
]
SUPPORTED_CODE_EXTENSIONS = {".py", ".ts", ".tsx", ".js", ".jsx"}
SKIPPED_DIRS = {"node_modules", ".git", "__pycache__", ".next", "dist", "build", ".venv", "edith-env", "whisper.cpp"}

# ──────────────────────────────────────────────
# Coding Style Analysis
# ──────────────────────────────────────────────
CODING_PERSONALITY_JSON = os.path.join(EDITH_PATH, "coding_personality.json")
CODING_PERSONALITY_TXT = os.path.join(EDITH_PATH, "coding_personality.txt")
REPOS = [
    EDITH_PATH,
    AYURSTOCK_PATH,
]

# ──────────────────────────────────────────────
# Agent — Dangerous Command Blocklist
# ──────────────────────────────────────────────
DANGEROUS_PATTERNS = [
    "rm -rf /",
    "rm -rf ~",
    "rm -rf /*",
    "rm -rf .",
    "mkfs",
    "dd if=/dev",
    ":(){ :|:",       # fork bomb
    "> /dev/sda",
    "chmod -R 777 /",
    "mv /* ",
    "mv / ",
    "wget|sh",
    "curl|sh",
    "wget | sh",
    "curl | sh",
    "python -c \"import os; os.remove",
    "shred",
    "wipefs",
    "> /etc/passwd",
    "> /etc/shadow",
    "chmod 000 /",
    "chown -R",
    "format c:",
]

# ──────────────────────────────────────────────
# Logging Setup
# ──────────────────────────────────────────────
os.makedirs(LOG_DIR, exist_ok=True)

def get_logger(name):
    """Get a configured logger for an EDITH module."""
    logger = logging.getLogger(f"edith.{name}")
    if not logger.handlers:
        logger.setLevel(logging.DEBUG)

        # Console — INFO and above
        ch = logging.StreamHandler()
        ch.setLevel(logging.INFO)
        ch.setFormatter(logging.Formatter("[EDITH %(name)s] %(message)s"))
        logger.addHandler(ch)

        # File — DEBUG and above
        fh = logging.FileHandler(os.path.join(LOG_DIR, "edith.log"))
        fh.setLevel(logging.DEBUG)
        fh.setFormatter(logging.Formatter("%(asctime)s [%(name)s] %(levelname)s: %(message)s"))
        logger.addHandler(fh)

    return logger


from errors import Result

# ──────────────────────────────────────────────
# External Services (lazy loading to avoid circular imports)
# ──────────────────────────────────────────────
_vault_cache = {}

def _get_vault_secret(key, default=""):
    """Lazy-load vault secrets to avoid circular import."""
    if key not in _vault_cache:
        try:
            import vault as v
            _vault_cache[key] = v.get_secret(key, default) or os.getenv(key, default)
        except Exception:
            _vault_cache[key] = os.getenv(key, default)
    return _vault_cache[key]

# Define as properties that call lazy loader
GMAIL_ADDRESS      = None
GMAIL_APP_PASSWORD = None
SIMPLENOTE_EMAIL   = None
SIMPLENOTE_PASSWORD= None

def get_gmail_creds():
    """Get Gmail credentials with lazy vault loading."""
    return (
        _get_vault_secret("GMAIL_ADDRESS", "") or os.getenv("GMAIL_ADDRESS", ""),
        _get_vault_secret("GMAIL_APP_PASSWORD", "") or os.getenv("GMAIL_APP_PASSWORD", "")
    )

def get_simplenote_creds():
    """Get SimpleNote credentials with lazy vault loading."""
    return (
        _get_vault_secret("SIMPLENOTE_EMAIL", "") or os.getenv("SIMPLENOTE_EMAIL", ""),
        _get_vault_secret("SIMPLENOTE_PASSWORD", "") or os.getenv("SIMPLENOTE_PASSWORD", "")
    )

# ──────────────────────────────────────────────
# Search Router Limits
# ──────────────────────────────────────────────
SEARCH_DAILY_LIMITS = {
    "serper":  83,
    "exa":     33,
    "tavily":  33,
    "searxng": 9999,
    "duckduckgo": 9999
}

# ──────────────────────────────────────────────
# Voice Pipeline — Active Session Flag
# ──────────────────────────────────────────────
IS_VOICE_ACTIVE = False  # Set True when mic/recording starts, False after TTS finishes

# ──────────────────────────────────────────────
# STT — Groq Whisper
# ──────────────────────────────────────────────
GROQ_STT_MODEL = "whisper-large-v3-turbo"
GROQ_STT_URL   = "https://api.groq.com/openai/v1/audio/transcriptions"

# ──────────────────────────────────────────────
# TTS — Groq Orpheus + Chatterbox flags
# ──────────────────────────────────────────────
GROQ_TTS_MODEL  = "playai-tts"
GROQ_TTS_VOICE  = "Fritz-PlayAI"
USE_GROQ_TTS    = False  # playai-tts removed from Groq API — disabled until new model confirmed
USE_CHATTERBOX  = False  # CPU load >120s → always times out; re-enable if GPU available
PREFER_FAST_TTS = False  # False = Chatterbox first → Piper fallback
CHATTERBOX_VENV = os.getenv("CHATTERBOX_VENV", os.path.join(USER_HOME, "chatterbox-env"))
CHATTERBOX_VENV_PYTHON = os.getenv("CHATTERBOX_VENV_PYTHON", os.path.join(CHATTERBOX_VENV, "bin/python3"))

# Voice mode triggers (spoken phrases to switch TTS engine)
FRIEND_VOICE_TRIGGER = "edith friend mode"
NORMAL_VOICE_TRIGGER = "edith normal mode"

# ──────────────────────────────────────────────
# Think Level (J2) — deep reasoning toggle
# ──────────────────────────────────────────────
FORCE_DEEP_THINK = True  # CoT enabled by default; set False to disable

# ──────────────────────────────────────────────
# Trace Toggle (T5)
# ──────────────────────────────────────────────
TRACE_ENABLED = True  # Set False via /trace off to silence trace_logger writes

# ──────────────────────────────────────────────
# T7: Config-driven Provider Failover
# ──────────────────────────────────────────────
# Override routing order per task type via env vars:
#   PROVIDER_ORDER_CODING=nvidia,openrouter
#   PROVIDER_ORDER=groq,gemini,nvidia   (applies to all unset task types)
_VALID_PROVIDERS = {"groq", "gemini", "nvidia", "openrouter"}
_DEFAULT_CHAINS = {
    "system":       ["openrouter", "groq", "gemini", "nvidia"],
    "conversation": ["openrouter", "groq", "gemini", "nvidia"],
    "coding":       ["openrouter", "nvidia", "gemini", "groq"],
    "reasoning":    ["openrouter", "nvidia", "gemini", "groq"],
}

def _parse_provider_order(env_val: str) -> list[str]:
    providers = [p.strip().lower() for p in env_val.split(",") if p.strip()]
    return [p for p in providers if p in _VALID_PROVIDERS] or None

def get_routing_chains() -> dict:
    """Return routing chains, env overrides applied at runtime."""
    chains = {k: list(v) for k, v in _DEFAULT_CHAINS.items()}
    global_order = os.getenv("PROVIDER_ORDER", "")
    if global_order:
        parsed = _parse_provider_order(global_order)
        if parsed:
            for k in chains:
                chains[k] = parsed
    for task in list(chains.keys()):
        env_key = f"PROVIDER_ORDER_{task.upper()}"
        task_order = os.getenv(env_key, "")
        if task_order:
            parsed = _parse_provider_order(task_order)
            if parsed:
                chains[task] = parsed
    return chains

# ──────────────────────────────────────────────
# T6: Channel-specific personas
# ──────────────────────────────────────────────
# Optional tone modifier injected into system prompt per channel.
# Override via env: PERSONA_TELEGRAM="You are on Telegram. Be brief, use bullet points."
CHANNEL_PERSONAS: dict[str, str] = {
    "telegram": os.getenv(
        "PERSONA_TELEGRAM",
        "You are responding via Telegram. Keep replies concise (≤3 sentences). "
        "Use plain text — no markdown headers.",
    ),
    "voice": os.getenv(
        "PERSONA_VOICE",
        "You are speaking aloud via TTS. Use short sentences. No markdown, no lists, "
        "no code blocks. Speak naturally as if in conversation.",
    ),
    "widget": os.getenv("PERSONA_WIDGET", ""),
    "cli":    os.getenv("PERSONA_CLI", ""),
}

# ──────────────────────────────────────────────
# Path Validation & Startup Diagnostics
# ──────────────────────────────────────────────

def get_user_dir(name: str) -> str:
    """Get common user directories (Downloads, Documents, Desktop, Pictures, home)."""
    dirs = {
        "downloads": os.path.join(USER_HOME, "Downloads"),
        "documents": os.path.join(USER_HOME, "Documents"),
        "desktop": os.path.join(USER_HOME, "Desktop"),
        "pictures": os.path.join(USER_HOME, "Pictures"),
        "home": USER_HOME,
    }
    return dirs.get(name.lower(), USER_HOME)

def validate_paths() -> dict[str, any]:
    """
    Verify critical paths exist and are accessible.
    Returns dict of {path_name: (exists, is_accessible, path_value)}.
    Called on startup to catch configuration issues early.
    """
    paths_to_check = {
        "EDITH_PATH": EDITH_PATH,
        "VENV_PATH": VENV_PATH,
        "AYURSTOCK_PATH": AYURSTOCK_PATH,
        "CHATTERBOX_VENV": CHATTERBOX_VENV,
        "USER_HOME": USER_HOME,
    }
    
    validation_result = {}
    for name, path in paths_to_check.items():
        try:
            exists = os.path.exists(path)
            # Try to list for accessibility
            if exists and os.path.isdir(path):
                try:
                    os.listdir(path)
                    is_accessible = True
                except PermissionError:
                    is_accessible = False
            else:
                is_accessible = exists
            validation_result[name] = {
                "exists": exists,
                "accessible": is_accessible,
                "path": path,
            }
        except Exception as e:
            validation_result[name] = {
                "exists": False,
                "accessible": False,
                "path": path,
                "error": str(e),
            }
    
    return validation_result

def print_path_status():
    """Print startup path diagnostics to logger."""
    logger = get_logger("config")
    validation = validate_paths()
    logger.info("=== Path Validation at Startup ===")
    for name, info in validation.items():
        status = "✓" if info.get("accessible") else "✗"
        logger.info(f"{status} {name}: {info['path']}")
        if "error" in info:
            logger.warning(f"  Error: {info['error']}")
        if not info.get("exists"):
            logger.warning(f"  Path does not exist")
