"""
EDITH Conversation DNA Engine — Phase 2.6

Reads contextual signals (device, time-of-day, recent emotion, session length)
and shapes EDITH's response style: tone, depth, length, formality.

Example:
  - Late night + tired signals → shorter, calmer, empathetic replies
  - Morning + coding context → detailed, technical, proactive suggestions
  - Quick successive queries → brief, punchy, no preamble
  - First query of day → warm greeting, status update
"""

import time
from datetime import datetime
from config import get_logger

log = get_logger("conversation_dna")


def get_response_modifiers(context: dict = None) -> dict:
    """Analyze context and return response style modifiers.

    Args:
        context: dict with optional keys:
            - device: str (voice/widget/telegram/chat_server)
            - emotion: str (from ml_router)
            - urgency: str (LOW/MEDIUM/HIGH)
            - session_queries: int (queries so far this session)
            - recent_intents: list[str] (last few intents)
            - input_source: str (USER/PROACTIVE)

    Returns:
        dict with keys:
            - tone: str (professional/casual/empathetic/energetic/calm)
            - depth: str (brief/standard/detailed)
            - max_length: int (suggested max tokens)
            - preamble: bool (whether to include greeting/context)
            - style_instruction: str (full instruction for LLM system prompt)
    """
    ctx = context or {}
    now = datetime.now()
    hour = now.hour

    device = ctx.get("device", "unknown")
    emotion = ctx.get("emotion", "neutral")
    urgency = ctx.get("urgency", "LOW")
    query_count = ctx.get("session_queries", 0)
    input_source = ctx.get("input_source", "USER")
    recent_intents = ctx.get("recent_intents", [])

    # ── Time-of-day signals ──
    if 5 <= hour < 9:
        time_tone = "energetic"
        time_depth = "standard"
        time_note = "It's morning — be proactive and positive."
    elif 9 <= hour < 17:
        time_tone = "professional"
        time_depth = "detailed"
        time_note = "Work hours — be precise and technical."
    elif 17 <= hour < 21:
        time_tone = "casual"
        time_depth = "standard"
        time_note = "Evening — be relaxed and conversational."
    else:  # 21-5
        time_tone = "calm"
        time_depth = "brief"
        time_note = "Late night — be concise and gentle."

    # ── Device signals ──
    if device == "telegram":
        max_length = 300  # Telegram messages should be shorter
        depth = "brief"
    elif device == "voice":
        max_length = 200  # Spoken responses need to be short
        depth = "brief"
    elif device == "widget":
        max_length = 600
        depth = time_depth
    else:
        max_length = 500
        depth = time_depth

    # ── Emotion override ──
    tone = time_tone
    if emotion == "frustrated":
        tone = "empathetic"
        time_note = "User seems frustrated — be patient and solution-focused."
    elif emotion == "stressed":
        tone = "calm"
        max_length = min(max_length, 300)
        time_note = "User seems stressed — be efficient, no fluff."
    elif emotion == "happy":
        tone = "energetic"
    elif emotion == "confused":
        depth = "detailed"
        max_length = max(max_length, 500)
        time_note = "User seems confused — explain step by step."

    # ── Urgency override ──
    if urgency == "HIGH":
        depth = "brief"
        max_length = min(max_length, 250)
        time_note = "URGENT — get to the answer immediately."

    # ── Session length signals ──
    preamble = True
    if query_count == 0:
        # First query of session
        preamble = True
    elif query_count > 10:
        # Deep into session — skip pleasantries
        preamble = False
        max_length = min(max_length, 400)

    # ── Rapid-fire detection ──
    if query_count > 3 and depth != "detailed":
        preamble = False
        depth = "brief"

    # ── Coding context ──
    coding_intents = {"code", "agent", "shell", "create_file"}
    if recent_intents and set(recent_intents[-3:]) & coding_intents:
        tone = "professional"
        depth = "detailed"
        time_note += " User is coding — be technical and precise."

    # ── Build style instruction ──
    style_instruction = _build_style_instruction(tone, depth, max_length, time_note, preamble)

    modifiers = {
        "tone": tone,
        "depth": depth,
        "max_length": max_length,
        "preamble": preamble,
        "style_instruction": style_instruction,
        "time_note": time_note,
    }

    log.debug(f"DNA modifiers: tone={tone}, depth={depth}, max_len={max_length}")
    return modifiers


def _build_style_instruction(tone: str, depth: str, max_length: int,
                              context_note: str, preamble: bool) -> str:
    """Build a concise LLM instruction from DNA modifiers."""
    parts = []

    tone_map = {
        "professional": "Be precise, technical, and efficient.",
        "casual": "Be relaxed, friendly, and conversational.",
        "empathetic": "Be patient, understanding, and solution-focused.",
        "energetic": "Be enthusiastic, proactive, and positive.",
        "calm": "Be gentle, concise, and measured.",
    }
    parts.append(tone_map.get(tone, tone_map["professional"]))

    depth_map = {
        "brief": f"Keep your response under {max_length} characters. Be punchy — no preamble.",
        "standard": f"Aim for {max_length} characters. Balance detail with brevity.",
        "detailed": f"Provide thorough detail up to {max_length} characters. Include examples when useful.",
    }
    parts.append(depth_map.get(depth, depth_map["standard"]))

    if not preamble:
        parts.append("Skip greetings and pleasantries — go straight to the answer.")

    if context_note:
        parts.append(context_note)

    return " ".join(parts)


def get_greeting_context() -> str:
    """Generate a time-appropriate greeting context for first query of day."""
    hour = datetime.now().hour
    if 5 <= hour < 12:
        return "Good morning, Boss."
    elif 12 <= hour < 17:
        return "Good afternoon, Boss."
    elif 17 <= hour < 21:
        return "Good evening, Boss."
    else:
        return "Working late, Boss."


if __name__ == "__main__":
    # Test different contexts
    print("=== Conversation DNA Engine Test ===\n")

    test_cases = [
        {"device": "voice", "emotion": "neutral", "session_queries": 0},
        {"device": "telegram", "emotion": "frustrated", "session_queries": 5},
        {"device": "widget", "emotion": "neutral", "urgency": "HIGH", "session_queries": 2},
        {"device": "widget", "emotion": "confused", "session_queries": 15, "recent_intents": ["code", "code", "shell"]},
    ]

    for i, ctx in enumerate(test_cases, 1):
        mods = get_response_modifiers(ctx)
        print(f"Test {i}: {ctx}")
        print(f"  Tone: {mods['tone']}, Depth: {mods['depth']}, Max: {mods['max_length']}")
        print(f"  Preamble: {mods['preamble']}")
        print(f"  Style: {mods['style_instruction'][:100]}...")
        print()
