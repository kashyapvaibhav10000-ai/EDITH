"""
handlers/meta.py — Slash-command / meta intent handlers:
  compact, think_level, trace_toggle, agent_stop, list_skills, identity
"""

import re

from errors import Result
from context import DispatchContext


def _handle_identity(ctx: DispatchContext) -> Result:
    hint = (
        "You are EDITH (Even Dead, I'm The Hero), a personal AI OS built by Vaibhav Kashyap. "
        "Answer questions about yourself, your purpose, your creator naturally and conversationally."
    )
    return Result(ok=True, value=ctx.chat_fn(f"{hint}\n\nUser: {ctx.user_input}", intent="chat"))


def _handle_compact(ctx: DispatchContext) -> Result:
    try:
        import shared_state as _ss
        with _ss._widget_history_lock:
            hist = list(_ss._widget_history.items())
            keep = dict(hist[-5:]) if len(hist) > 5 else dict(hist)
            _ss._widget_history.clear()
            _ss._widget_history.update(keep)
        mem_count = 0
        try:
            from smart_memory import SmartMemory
            mem_count = len(SmartMemory()._hot)
        except Exception:
            pass
        try:
            import consolidation
            consolidation.consolidate_memories()
        except Exception:
            pass
        try:
            import orchestrator as _orch
            with _orch._history_lock:
                if len(_orch.conversation_history) > 3:
                    _orch.conversation_history = _orch.conversation_history[-3:]
        except Exception:
            pass
        return Result.success(
            f"Context compacted, Boss. Kept last 3 turns and consolidated memories ({mem_count} items)."
        )
    except Exception as e:
        return Result.failure(str(e))


def _handle_think_level(ctx: DispatchContext) -> Result:
    import config
    m = re.search(r'\b(high|deep|hard|max|low|fast|quick|shallow)\b', ctx.user_input.lower())
    if not m:
        return Result.success("Usage: /think high|deep|max|low|fast|quick")
    config.FORCE_DEEP_THINK = m.group(1) in ("high", "deep", "hard", "max")
    return Result.success(
        "Deep think ON, Boss. I'll reason step by step and prefer high-context providers."
        if config.FORCE_DEEP_THINK else "Deep think OFF, Boss. Back to fast routing."
    )


def _handle_trace_toggle(ctx: DispatchContext) -> Result:
    import config
    m = re.search(r'\b(on|off)\b', ctx.user_input.lower())
    if not m:
        return Result.success("Usage: /trace on|off")
    config.TRACE_ENABLED = (m.group(1) == "on")
    return Result.success(f"Trace logging turned {m.group(1)}, Boss.")


def _handle_agent_stop(ctx: DispatchContext) -> Result:
    try:
        from agent import interrupt_agent
        interrupt_agent()
        return Result.success("Stopping current task, Boss.")
    except Exception as e:
        return Result.failure(str(e))


def _handle_list_skills(ctx: DispatchContext) -> Result:
    try:
        from skills_loader import list_skills
        skills = list_skills()
        return Result.success(
            "Loaded skills: " + ", ".join(skills) if skills else "No skills loaded, Boss."
        )
    except Exception as e:
        return Result.failure(str(e))


def handle(intent: str, ctx: DispatchContext) -> str:
    handlers = {
        "identity":    _handle_identity,
        "greeting":    _handle_identity,
        "compact":     _handle_compact,
        "think_level": _handle_think_level,
        "trace_toggle": _handle_trace_toggle,
        "agent_stop":  _handle_agent_stop,
        "list_skills": _handle_list_skills,
    }
    fn = handlers.get(intent)
    if fn is None:
        return f"Unknown meta intent: {intent}"
    result = fn(ctx)
    if isinstance(result, Result):
        return str(result.value) if result.ok else str(result.error)
    return str(result)
