"""
EDITH Intent Dispatch — thin dispatcher.
All handler logic lives in handlers/ (see handlers/__init__.py).
"""

import re
import threading

from config import get_logger, USER_HOME
from context import DispatchContext
from errors import Result

# Re-export helpers so existing callers keep working without changes
from handlers.helpers import (
    extract_date        as _extract_date,
    extract_time        as _extract_time,
    extract_event_title as _extract_event_title,
    extract_filepath    as _extract_filepath,
    extract_phone_number as _extract_phone_number,
    extract_sms_body    as _extract_sms_body,
    is_safe_command     as _is_safe_command,
)

log = get_logger("intent_dispatch")
# ── HITL Pending Action state ──────────────────
_pending_action = None
_action_lock = threading.Lock()

def get_pending_action():
    with _action_lock: return _pending_action
def set_pending_action(action):
    global _pending_action
    with _action_lock: _pending_action = action
def clear_pending_action():
    global _pending_action
    with _action_lock: _pending_action = None

def _friendly_error(intent, error):
    err = str(error).lower()
    if "timeout" in err or "timed out" in err:
        return "That's taking too long right now. The service might be busy — try again in a moment, Boss."
    if "connection" in err or "refused" in err or "unreachable" in err:
        return "I'm having trouble connecting to that service. It might be offline or your internet could be down."
    if "not found" in err or "no such file" in err:
        return "I couldn't find what I was looking for. Double-check the path or name and try again."
    if "permission" in err or "denied" in err:
        return "I don't have permission to do that. You might need to run it with elevated privileges."
    log.error(f"Intent handler [{intent}] error: {error}")
    return "Something went wrong on my end, Boss. Want me to try a different approach?"
def _run_local_exec(user_input: str):
    from handlers.local_exec import run_local_exec
    return run_local_exec(user_input)
# ── Handler shims ──────────────────────────────
def _handle_email(ctx):
    from handlers.email import _handle_email as _f; return _f(ctx)
def _handle_unread_email(ctx):
    from handlers.email import _handle_unread_email as _f; return _f(ctx)
def _handle_shell(ctx):
    from handlers.shell import _handle_shell as _f; return _f(ctx)
def _handle_create_file(ctx):
    from handlers.shell import _handle_create_file as _f; return _f(ctx)
def _handle_delete_file(ctx):
    from handlers.shell import _handle_delete_file as _f; return _f(ctx)
def _handle_file_query(ctx):
    from handlers.shell import _handle_file_query as _f; return _f(ctx)
def _handle_calendar_today(ctx):
    from handlers.calendar import _handle_calendar_today as _f; return _f(ctx)
def _handle_calendar_week(ctx):
    from handlers.calendar import _handle_calendar_week as _f; return _f(ctx)
def _handle_calendar_create(ctx):
    from handlers.calendar import _handle_calendar_create as _f; return _f(ctx)
def _handle_weather(ctx):
    from handlers.search import _handle_weather as _f; return _f(ctx)
def _handle_search(ctx):
    from handlers.search import _handle_search as _f; return _f(ctx)
def _handle_call(ctx):
    from handlers.phone import _handle_call as _f; return _f(ctx)
def _handle_sms(ctx):
    from handlers.phone import _handle_sms as _f; return _f(ctx)
def _handle_phone(ctx):
    from handlers.phone import _handle_phone as _f; return _f(ctx)
def _handle_whatsapp(ctx):
    from handlers.phone import _handle_whatsapp as _f; return _f(ctx)
def _handle_rag(ctx):
    from handlers.memory_handler import _handle_rag as _f; return _f(ctx)
def _handle_profile(ctx):
    from handlers.memory_handler import _handle_profile as _f; return _f(ctx)
def _handle_briefing(ctx):
    from handlers.memory_handler import _handle_briefing as _f; return _f(ctx)
def _handle_wake(ctx):
    from handlers.system import _handle_wake as _f; return _f(ctx)
def _handle_session_end(ctx):
    from handlers.system import _handle_session_end as _f; return _f(ctx)
def _handle_system_health(ctx):
    from handlers.system import _handle_system_health as _f; return _f(ctx)
def _handle_mcp(ctx):
    from handlers.mcp import _handle_mcp as _f; return _f(ctx)
def _handle_vision(ctx):
    from handlers.misc import _handle_vision as _f; return _f(ctx)
def _handle_open_app(ctx):
    from handlers.misc import _handle_open_app as _f; return _f(ctx)
def _handle_data_analysis(ctx):
    from handlers.misc import _handle_data_analysis as _f; return _f(ctx)
def _handle_agent(ctx):
    from handlers.misc import _handle_agent as _f; return _f(ctx)
def _handle_council(ctx):
    from handlers.misc import _handle_council as _f; return _f(ctx)
def _handle_decision(ctx):
    from handlers.misc import _handle_decision as _f; return _f(ctx)
def _handle_morning_briefing(ctx):
    from handlers.misc import _handle_morning_briefing as _f; return _f(ctx)
def _handle_self_improve(ctx):
    from handlers.misc import _handle_self_improve as _f; return _f(ctx)
def _handle_image_gen(ctx):
    from handlers.misc import _handle_image_gen as _f; return _f(ctx)
def _handle_video_summarize(ctx):
    from handlers.misc import _handle_video_summarize as _f; return _f(ctx)
def _handle_repo_analyze(ctx):
    from handlers.misc import _handle_repo_analyze as _f; return _f(ctx)
def _handle_chat_fallback(ctx):
    from handlers.misc import _handle_chat_fallback as _f; return _f(ctx)
def _handle_identity(ctx):
    from handlers.meta import _handle_identity as _f; return _f(ctx)
def _handle_compact(ctx):
    from handlers.meta import _handle_compact as _f; return _f(ctx)
def _handle_think_level(ctx):
    from handlers.meta import _handle_think_level as _f; return _f(ctx)
def _handle_trace_toggle(ctx):
    from handlers.meta import _handle_trace_toggle as _f; return _f(ctx)
def _handle_agent_stop(ctx):
    from handlers.meta import _handle_agent_stop as _f; return _f(ctx)
def _handle_list_skills(ctx):
    from handlers.meta import _handle_list_skills as _f; return _f(ctx)
# ── Dispatch Table ─────────────────────────────
INTENT_HANDLERS = {
    "identity": _handle_identity, "greeting": _handle_identity,
    "weather": _handle_weather,
    "calendar_today": _handle_calendar_today, "calendar_week": _handle_calendar_week,
    "calendar_create": _handle_calendar_create,
    "email": _handle_email, "unread_email": _handle_unread_email,
    "search": _handle_search,
    "call": _handle_call, "sms": _handle_sms, "phone": _handle_phone,
    "vision": _handle_vision, "open_app": _handle_open_app,
    "shell": _handle_shell, "file_query": _handle_file_query,
    "create_file": _handle_create_file, "delete_file": _handle_delete_file,
    "rag": _handle_rag, "data_analysis": _handle_data_analysis,
    "agent": _handle_agent, "council": _handle_council, "decision": _handle_decision,
    "morning_briefing": _handle_morning_briefing, "briefing": _handle_briefing,
    "profile": _handle_profile, "self_improve": _handle_self_improve,
    "session_end": _handle_session_end, "wake": _handle_wake,
    "whatsapp": _handle_whatsapp, "mcp": _handle_mcp,
    "image_gen": _handle_image_gen, "video_summarize": _handle_video_summarize,
    "system_health": _handle_system_health, "repo_analyze": _handle_repo_analyze,
    "compact": _handle_compact, "think_level": _handle_think_level,
    "trace_toggle": _handle_trace_toggle, "agent_stop": _handle_agent_stop,
    "list_skills": _handle_list_skills,
}


def _validate_tool_output(output: str, intent: str) -> str:
    if not output or not output.strip(): return f"I couldn't get a result for {intent} right now, Boss."
    return output[:4000] + "... [truncated]" if len(output) > 4000 else output

def _dispatch_single(ctx: DispatchContext) -> str:
    handler = INTENT_HANDLERS.get(ctx.intent, _handle_chat_fallback)
    try:
        result = handler(ctx)
        if isinstance(result, Result):
            if result.ok: return _validate_tool_output(str(result.value), ctx.intent)
            log.error(f"Handler [{ctx.intent}] failure: {result.error} ({result.error_type})")
            return _friendly_error(ctx.intent, result.error)
        output = str(result) if result else ""
        return _validate_tool_output(output, ctx.intent) if output else _friendly_error(ctx.intent, "No response generated")
    except Exception as e:
        log.error(f"Dispatch exception [{ctx.intent}]: {e}")
        return _friendly_error(ctx.intent, e)

def dispatch(ctx: DispatchContext) -> str:
    """Route an intent to its handler via DispatchContext. Returns response string."""
    try:
        from compound_dag import detect_compound, split_into_tasks, DAGExecutor
        from intent import detect_intent
        if detect_compound(ctx.user_input):
            tasks = split_into_tasks(ctx.user_input)
            if len(tasks) >= 2:
                log.info(f"Compound intent detected — routing {len(tasks)} tasks through DAG")
                def _dag_execute(task_str):
                    sub_ctx = DispatchContext(user_input=task_str, intent=detect_intent(task_str),
                                             chat_fn=ctx.chat_fn, source=ctx.source)
                    r = _dispatch_single(sub_ctx)
                    return r, not r.startswith("Something went wrong") and bool(r)
                dag = DAGExecutor(tasks, _dag_execute)
                dag_result = dag.execute_all()
                return dag_result.value if dag_result.ok else dag_result.error
    except Exception as e:
        log.warning(f"DAG routing failed, falling back to direct dispatch: {e}")
    return _dispatch_single(ctx)
def execute_pending_action(action) -> str:
    from handlers.pending_action import execute_pending_action as _exec
    return _exec(action)
