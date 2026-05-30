"""
handlers/shell.py — Shell/file intent handlers (shell, create_file, delete_file, file_query)
"""

import os
import re
import subprocess
import shlex

from config import get_logger, get_user_dir, USER_HOME
from errors import Result
from context import DispatchContext

log = get_logger("handlers.shell")


def _handle_shell(ctx: DispatchContext) -> Result:
    from handlers.local_exec import run_local_exec as _run_local_exec
    from handlers.helpers import is_safe_command as _is_safe_command
    from intent_dispatch import _friendly_error, set_pending_action

    # DISABLED on cloud: remote shell execution is an RCE vector
    if os.getenv("EDITH_NODE_TYPE", "local") == "cloud":
        return Result.success("Shell execution disabled on cloud node for security.")
    try:
        # Intercept descriptive/natural-language queries before treating as raw shell
        _local = _run_local_exec(ctx.user_input)
        if _local:
            return Result.success(_local)

        cmd = ctx.user_input
        for prefix in ["run ", "execute ", "terminal ", "shell ", "command "]:
            if cmd.lower().startswith(prefix):
                cmd = cmd[len(prefix):].strip()
                break
        cmd = cmd.strip("\"'`")
        if not cmd or cmd.lower() in ["run", "execute", "command", "shell"]:
            return Result.success(f"What command should I run, Boss? Something like 'run ls -la {USER_HOME}'.")

        if _is_safe_command(cmd):
            try:
                result = subprocess.run(
                    shlex.split(cmd), capture_output=True, text=True, timeout=15, cwd=USER_HOME
                )
                output = (result.stdout or result.stderr or "").strip()
                if not output:
                    return Result.success(f"Ran `{cmd}` — no output returned.")
                if len(output) < 500:
                    return Result.success(f"Here's what I got:\n\n{output}")
                return Result.success(ctx.chat_fn(
                    f"User asked: {ctx.user_input}\n\nCommand `{cmd}` returned:\n{output[:2000]}\n\nSummarize naturally. Be concise.",
                    intent="shell"
                ))
            except subprocess.TimeoutExpired:
                return Result.success("That command is taking too long. It might be stuck — want me to try with a longer timeout?")
            except Exception as e:
                return Result.success(_friendly_error("shell", e))
        # Dangerous: HITL confirmation
        set_pending_action({"type": "shell", "cmd": cmd})
        return Result.success(
            f"I've prepared this command:\n\n`{cmd}`\n\n"
            "⚠️ This could modify your system. Type **YES** to run or **NO** to cancel."
        )
    except Exception as e:
        return Result.from_exception(e)


def _handle_create_file(ctx: DispatchContext) -> Result:
    from handlers.helpers import extract_filepath
    from intent_dispatch import set_pending_action

    try:
        filepath = extract_filepath(ctx.user_input)
        if not filepath:
            return Result.success(f"📁 I need a file path. Try: 'create file {USER_HOME}/notes/todo.txt'")
        content_match = re.search(
            r"(?:with content|containing|with text|content)\s+(.+)",
            ctx.user_input, re.IGNORECASE | re.DOTALL
        )
        content = content_match.group(1).strip() if content_match else "(empty)"
        set_pending_action({"type": "create_file", "path": filepath, "content": content})
        return Result.success(
            f"📁 File Creation Request:\nPath: {filepath}\nContent length: {len(content)} chars\n\n"
            "⚠️ Proceed? Type YES or NO."
        )
    except Exception as e:
        return Result.from_exception(e)


def _handle_delete_file(ctx: DispatchContext) -> Result:
    from handlers.helpers import extract_filepath
    from intent_dispatch import set_pending_action

    try:
        filepath = extract_filepath(ctx.user_input)
        if not filepath:
            return Result.success(f"🗑️ I need a file path. Try: 'delete file {USER_HOME}/old_notes.txt'")
        set_pending_action({"type": "delete_file", "path": filepath})
        return Result.success(
            f"🗑️ Deletion Request:\nPath: {filepath}\n\n"
            "⚠️ Proceed with permanently deleting this file? Type YES or NO."
        )
    except Exception as e:
        return Result.from_exception(e)


def _handle_file_query(ctx: DispatchContext) -> Result:
    try:
        dir_map = {
            "download": get_user_dir("downloads"),
            "document": get_user_dir("documents"),
            "desktop":  get_user_dir("desktop"),
            "home":     USER_HOME,
            "picture":  get_user_dir("pictures"),
            "video":    os.path.join(USER_HOME, "Videos"),
            "music":    os.path.join(USER_HOME, "Music"),
        }
        target_dir = None
        lower = ctx.user_input.lower()
        for key, path in dir_map.items():
            if key in lower:
                target_dir = path
                break
        if not target_dir:
            path_match = re.search(r'(/[\w/.-]+)', ctx.user_input)
            target_dir = os.path.expanduser(path_match.group(1)) if path_match else USER_HOME

        if not os.path.isdir(target_dir):
            return Result.success(f"Can't find `{target_dir}`. Sure it exists?")

        items = os.listdir(target_dir)
        if not items:
            return Result.success(f"`{target_dir}` is empty.")

        folders = sorted([f for f in items if os.path.isdir(os.path.join(target_dir, f))])
        files   = sorted([f for f in items if os.path.isfile(os.path.join(target_dir, f))])

        ext_labels = {
            '.pdf': '📄 PDFs', '.docx': '📝 Documents', '.doc': '📝 Documents',
            '.xlsx': '📊 Spreadsheets', '.xls': '📊 Spreadsheets',
            '.png': '🖼️ Images', '.jpg': '🖼️ Images', '.jpeg': '🖼️ Images',
            '.gif': '🖼️ Images', '.webp': '🖼️ Images', '.svg': '🖼️ Images',
            '.mp4': '🎬 Videos', '.mkv': '🎬 Videos', '.avi': '🎬 Videos',
            '.mp3': '🎵 Audio', '.ogg': '🎵 Audio', '.wav': '🎵 Audio',
            '.flac': '🎵 Audio', '.m4a': '🎵 Audio',
            '.zip': '📦 Archives', '.tar': '📦 Archives', '.gz': '📦 Archives',
            '.py': '💻 Code', '.js': '💻 Code', '.ts': '💻 Code',
            '.html': '💻 Code', '.css': '💻 Code',
            '.json': '⚙️ Config', '.yaml': '⚙️ Config', '.yml': '⚙️ Config',
            '.txt': '📃 Text', '.md': '📃 Text',
        }
        file_groups = {}
        for f in files:
            ext = os.path.splitext(f)[1].lower()
            label = ext_labels.get(ext, '📎 Other')
            file_groups.setdefault(label, []).append(f)

        dir_name = os.path.basename(target_dir) or target_dir
        parts = [f"📂 **{dir_name}** — {len(items)} items\n"]
        if folders:
            parts.append(f"**📁 Folders ({len(folders)})**")
            for i, f in enumerate(folders, 1):
                parts.append(f"  {i}. {f}/")
            parts.append("")
        for label, group_files in sorted(file_groups.items(), key=lambda x: -len(x[1])):
            parts.append(f"**{label} ({len(group_files)})**")
            for i, f in enumerate(group_files, 1):
                try:
                    size = os.path.getsize(os.path.join(target_dir, f))
                    size_str = (
                        f"{size} B" if size < 1024
                        else (f"{size/1024:.0f} KB" if size < 1048576 else f"{size/1048576:.1f} MB")
                    )
                except Exception:
                    size_str = ""
                parts.append(f"  {i}. {f}  `{size_str}`" if size_str else f"  {i}. {f}")
            parts.append("")
        return Result.success("\n".join(parts))
    except PermissionError:
        return Result.failure("Don't have permission to access that directory.", error_type="permission")
    except Exception as e:
        return Result.from_exception(e)


def handle(intent: str, ctx: DispatchContext) -> str:
    handlers = {
        "shell":       _handle_shell,
        "create_file": _handle_create_file,
        "delete_file": _handle_delete_file,
        "file_query":  _handle_file_query,
    }
    fn = handlers.get(intent)
    if fn is None:
        return f"Unknown shell intent: {intent}"
    result = fn(ctx)
    if isinstance(result, Result):
        return str(result.value) if result.ok else str(result.error)
    return str(result)
