"""
handlers/pending_action.py — HITL (Human-in-the-Loop) pending action executor.
"""

import os
import subprocess
import shlex

from config import USER_HOME


def execute_pending_action(action) -> str:
    """Execute a HITL-confirmed action. Returns str for backward compatibility."""
    from tools import write_file, delete_file
    atype = action.get("type")

    if atype == "whatsapp":
        from whatsapp import send_message
        return f"📱 {send_message(action['contact'], action['message'])}"

    elif atype == "shell":
        cmd = action.get("cmd")
        try:
            result = subprocess.run(
                shlex.split(cmd), capture_output=True, text=True, timeout=30, cwd=USER_HOME
            )
            output = result.stdout or result.stderr
            return f"💻 Execution Complete:\n\n{output.strip() or 'No output returned.'}"
        except Exception as e:
            return f"❌ Shell Error: {e}"

    elif atype == "create_file":
        return f"📁 {write_file(action['path'], action['content'], interactive=False)}"

    elif atype == "delete_file":
        return f"🗑️ {delete_file(action['path'], interactive=False)}"

    elif atype == "agent":
        steps = action.get("steps", [])
        if not steps:
            return "No valid steps found in the plan to execute."
        from agent import is_dangerous, get_command
        results = []
        for i, step in enumerate(steps, 1):
            cmd = get_command(step)
            if is_dangerous(cmd):
                results.append(f"⛔ Step {i} Blocked (Dangerous): `{cmd}`")
                continue
            try:
                subprocess.run(
                    shlex.split(cmd), capture_output=True, text=True, timeout=30, cwd=USER_HOME
                )
                results.append(f"✅ Step {i}: `{cmd}` -> OK")
            except Exception as e:
                results.append(f"❌ Step {i}: `{cmd}` -> ERROR ({e})")
        return "🤖 Agent Execution Summary:\n\n" + "\n".join(results)

    elif atype == "fuzzy_confirm":
        import secrets as _sec
        base = action["resolved_path"]
        count = action.get("count", 1)
        named = action.get("named")
        created, failed = [], []
        for name in ([named] if named else [_sec.token_hex(4) for _ in range(count)]):
            full = os.path.join(base, name)
            try:
                os.makedirs(full, exist_ok=True)
                if os.path.isdir(full):
                    created.append(name)
                else:
                    failed.append(f"{name}: created but not found on disk")
            except Exception as e:
                failed.append(f"{name}: {e}")
        if not created and failed:
            return (
                f"❌ All {count} folder(s) failed in `{base}`:\n"
                + "\n".join(f"  • {f}" for f in failed[:5])
            )
        summary = f"📁 Created {len(created)}/{count} folder(s) in `{base}`:\n"
        summary += "\n".join(f"  • {n}" for n in created)
        if failed:
            summary += f"\n\n❌ Failed ({len(failed)}): {', '.join(failed[:5])}"
        return summary

    return "Unknown action type."
