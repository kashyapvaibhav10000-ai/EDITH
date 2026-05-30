# Compatibility shim — real module is core/config.py
from core.config import *  # noqa: F401, F403
from core.config import (
    get_logger, get_user_dir, USER_HOME, EDITH_PATH,
    MEMORY_ARCHIVE_PATH, USE_CHATTERBOX, USE_GROQ_TTS,
    get_chroma_client,
)
