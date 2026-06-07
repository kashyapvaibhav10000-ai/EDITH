"""
handlers/mcp.py — MCP (Model Context Protocol) intent handler
"""

import os
import re

from config import get_logger, get_user_dir, USER_HOME, EDITH_PATH
from errors import Result
from context import DispatchContext

log = get_logger("handlers.mcp")


def _safe_path(raw: str) -> tuple:
    expanded = os.path.expanduser(raw.strip())
    resolved = os.path.realpath(expanded)
    if not resolved.startswith(USER_HOME):
        return None, f"Access denied — path outside {USER_HOME}: `{resolved}`"
    return resolved, None


def _handle_mcp(ctx: DispatchContext) -> Result:
    from intent_dispatch import set_pending_action

    try:
        import mcp_bridge
        import secrets
        lower = ctx.user_input.lower()

        if re.search(r"\b(status|servers?|list servers?)\b", lower) and "mcp" in lower:
            status = mcp_bridge.get_mcp_status()
            if not status:
                return Result.success("No MCP servers configured.")
            lines = ["🔌 **MCP Server Status**\n"]
            for name, info in status.items():
                state = "✅ enabled" if info["enabled"] else "❌ disabled"
                lines.append(f"**{name}** — {state} | tools: {info['tool_count']} | last: {info['last_called']}")
                lines.append(f"  _{info['description']}_")
            return Result.success("\n".join(lines))

        m = re.search(r"(?:tools?|list tools?)\s+(?:for\s+)?(\w[\w-]*)", lower)
        if m:
            server = m.group(1)
            tools = mcp_bridge.list_mcp_tools(server)
            if not tools:
                return Result.success(f"No tools found for '{server}' (server may be disabled or unreachable).")
            lines = [f"🔧 **Tools on {server}**\n"]
            for t in tools:
                lines.append(f"• **{t.get('name', '?')}** — {t.get('description', '')}")
            return Result.success("\n".join(lines))

        _create_dir_pat = re.search(
            r"\b(create|make|mkdir)\b.{0,30}?(\d+)?.{0,20}?\b(folder|directory|dir)s?\b", lower
        )
        if _create_dir_pat or re.search(r"\bmkdir\b", lower):
            _naming_noise = {"random", "using", "hash", "bit", "names", "named", "called",
                             "unique", "generated", "auto", "temp", "tmp"}

            def _resolve_base(raw_base: str) -> tuple:
                if not raw_base.startswith("/") and not raw_base.startswith("~"):
                    candidate = os.path.join(USER_HOME, raw_base)
                else:
                    candidate = raw_base
                resolved, err = _safe_path(candidate)
                if err:
                    return None, err
                if os.path.isdir(resolved):
                    return resolved, None
                import difflib
                typed_leaf = os.path.basename(resolved)
                try:
                    actual_dirs = [d for d in os.listdir(USER_HOME)
                                   if os.path.isdir(os.path.join(USER_HOME, d))]
                except OSError:
                    actual_dirs = []
                lower_map = {d.lower(): d for d in actual_dirs}
                if typed_leaf.lower() in lower_map:
                    matched = lower_map[typed_leaf.lower()]
                    return os.path.join(USER_HOME, matched), f"__fuzzy__:{typed_leaf}:{matched}"
                sw = [d for d in actual_dirs if d.lower().startswith(typed_leaf.lower())]
                if len(sw) == 1:
                    return os.path.join(USER_HOME, sw[0]), f"__fuzzy__:{typed_leaf}:{sw[0]}"
                fuzzy = difflib.get_close_matches(typed_leaf, actual_dirs, n=1, cutoff=0.6)
                if fuzzy:
                    return os.path.join(USER_HOME, fuzzy[0]), f"__fuzzy__:{typed_leaf}:{fuzzy[0]}"
                top = ", ".join(sorted(actual_dirs)[:10])
                return None, f"__notfound__:{typed_leaf}:{top}"

            count_m = re.search(r"\b(\d+)\b", ctx.user_input)
            count = int(count_m.group(1)) if count_m else 1
            if count > 100:
                return Result.success("⚠️ Max 100 folders per request.")

            named_m = re.search(
                r"(?:named?|called|as)\s+([\w._-]+)|mkdir\s+([\w._-]+)",
                ctx.user_input, re.IGNORECASE
            )
            if named_m:
                _extracted = (named_m.group(1) or named_m.group(2) or "").strip().lower()
                if _extracted in _naming_noise:
                    named_m = None

            path_m = re.search(r"in\s+(/[^\s]+|~/[^\s]+|[\w]+)", ctx.user_input, re.IGNORECASE)
            raw_base = path_m.group(1) if path_m else USER_HOME
            base, base_err = _resolve_base(raw_base)

            if base_err and base_err.startswith("__fuzzy__:"):
                _, typed, matched = base_err.split(":", 2)
                if typed.lower() == matched.lower():
                    base_err = None
                else:
                    _named = (named_m.group(1) or named_m.group(2) or "").strip() if named_m else None
                    set_pending_action({"type": "fuzzy_confirm", "resolved_path": base, "count": count, "named": _named})
                    return Result.success(
                        f"⚠️ No folder named `{typed}` found in {USER_HOME}/.\n"
                        f"Did you mean `{matched}`? Reply YES to confirm or give the full path."
                    )
            elif base_err and base_err.startswith("__notfound__:"):
                parts = base_err.split(":", 2)
                typed = parts[1]
                available = parts[2] if len(parts) > 2 else ""
                msg = f"⚠️ No folder called `{typed}` found in {USER_HOME}/."
                if available:
                    msg += f"\nAvailable folders: {available}"
                msg += "\nProvide full path or correct name."
                return Result.success(msg)
            elif base_err:
                return Result.success(f"❌ {base_err}")

            def _create_one(full_path: str) -> tuple:
                safe, err = _safe_path(full_path)
                if err:
                    return False, f"path_error: {err}"
                result = mcp_bridge.call_mcp_server(
                    "filesystem", "create_directory", {"path": safe}, context_intent=ctx.intent
                )
                if "error" in result.lower() or "failed" in result.lower():
                    try:
                        os.makedirs(safe, exist_ok=True)
                    except Exception as fe:
                        return False, f"MCP error: {result.strip()} | fallback error: {fe}"
                if not os.path.isdir(safe):
                    return False, f"MCP reported success but `{safe}` not found on disk"
                return True, safe

            if named_m:
                name = (named_m.group(1) or named_m.group(2)).strip()
                ok, msg = _create_one(os.path.join(base, name))
                if not ok:
                    return Result.success(f"❌ Failed to create `{name}`: {msg}")
                return Result.success(f"📁 Created `{msg}`")
            else:
                created, failed = [], []
                for _ in range(count):
                    name = secrets.token_hex(4)
                    ok, msg = _create_one(os.path.join(base, name))
                    if ok:
                        created.append(name)
                    else:
                        failed.append(f"{name}: {msg}")
                if not created and failed:
                    return Result.success(
                        f"❌ All {count} folder(s) failed to create in `{base}`:\n"
                        + "\n".join(f"  • {f}" for f in failed[:5])
                    )
                summary = f"📁 Created {len(created)}/{count} folders in `{base}`:\n"
                summary += "\n".join(f"  • {n}" for n in created)
                if failed:
                    summary += f"\n\n❌ Failed ({len(failed)}): {', '.join(failed[:5])}"
                return Result.success(summary)

        if re.search(r"\b(delete|remove|rm)\b", lower) and re.search(r"(/[^\s]+|\S+\.\w+)", ctx.user_input):
            path_m = re.search(r"(/[^\s]+|\b[\w./~-]+\.\w+)", ctx.user_input)
            if not path_m:
                return Result.success("🗑️ I need a file path to delete.")
            safe, err = _safe_path(path_m.group(1))
            if err:
                return Result.success(f"❌ {err}")
            set_pending_action({"type": "delete_file", "path": safe})
            return Result.success(f"⚠️ **Delete `{safe}`?**\n\nThis cannot be undone. Type **YES** to confirm or **NO** to cancel.")

        if re.search(r"\b(move|rename|mv)\b", lower):
            paths = re.findall(r"(/[^\s]+|\b[\w./~-]+\.\w+)", ctx.user_input)
            if len(paths) < 2:
                return Result.success(f"📦 Need source and destination. Try: 'move {USER_HOME}/a.txt {USER_HOME}/b.txt'")
            src, err = _safe_path(paths[0])
            if err:
                return Result.success(f"❌ {err}")
            dst, err = _safe_path(paths[1])
            if err:
                return Result.success(f"❌ {err}")
            result = mcp_bridge.call_mcp_server("filesystem", "move_file", {"source": src, "destination": dst}, context_intent=ctx.intent)
            if "error" in result.lower() or "failed" in result.lower():
                try:
                    import shutil
                    shutil.move(src, dst)
                    result = f"Moved `{src}` → `{dst}` (fallback)"
                except Exception as fe:
                    return Result.success(f"❌ Failed: {fe}")
            return Result.success(f"📦 {result}")

        if re.search(r"\b(find|search for file|search file|locate)\b", lower):
            path_m = re.search(r"in\s+(/[^\s]+)", ctx.user_input)
            base = os.path.expanduser(path_m.group(1)) if path_m else USER_HOME
            safe_base, err = _safe_path(base)
            if err:
                return Result.success(f"❌ {err}")
            pattern_m = re.search(r"(?:find|search for?|locate)\s+(\S+)", ctx.user_input, re.IGNORECASE)
            pattern = pattern_m.group(1) if pattern_m else "*"
            result = mcp_bridge.call_mcp_server("filesystem", "search_files", {"path": safe_base, "pattern": pattern}, context_intent=ctx.intent)
            return Result.success(f"🔍 **Search `{pattern}` in `{safe_base}`**\n\n{result}")

        if re.search(r"\b(info|size|modified|stat)\b", lower) and re.search(r"(/[^\s]+|\S+\.\w+)", ctx.user_input):
            path_m = re.search(r"(/[^\s]+|\b[\w./~-]+\.\w+)", ctx.user_input)
            if not path_m:
                return Result.success("ℹ️ I need a file path.")
            safe, err = _safe_path(path_m.group(1))
            if err:
                return Result.success(f"❌ {err}")
            result = mcp_bridge.call_mcp_server("filesystem", "get_file_info", {"path": safe}, context_intent=ctx.intent)
            return Result.success(f"ℹ️ **{safe}**\n\n{result}")

        if re.search(r"\b(read|open|show|cat)\b", lower) and re.search(r"(/[^\s]+|\S+\.\w+)", ctx.user_input):
            path_m = re.search(r"(/[^\s]+|\b[\w./~-]+\.\w+)", ctx.user_input)
            if not path_m:
                return Result.success(f"📄 I need a file path. Try: 'read {USER_HOME}/notes/todo.txt'")
            safe, err = _safe_path(path_m.group(1))
            if err:
                return Result.success(f"❌ {err}")
            result = mcp_bridge.call_mcp_server("filesystem", "read_file", {"path": safe}, context_intent=ctx.intent)
            if "error" in result.lower() or "failed" in result.lower():
                try:
                    with open(safe) as f:
                        result = f.read()
                except Exception as fe:
                    return Result.success(f"❌ Failed: {fe}")
            return Result.success(f"📄 **{safe}**\n\n{result}")

        if re.search(r"\b(list|ls|dir|what.s in|show files)\b", lower):
            path_m = re.search(r"(/[^\s]+)", ctx.user_input)
            raw = path_m.group(1) if path_m else USER_HOME
            safe, err = _safe_path(raw)
            if err:
                return Result.success(f"❌ {err}")
            result = mcp_bridge.call_mcp_server("filesystem", "list_directory", {"path": safe}, context_intent=ctx.intent)
            if "error" in result.lower() or "failed" in result.lower():
                try:
                    entries = os.listdir(safe)
                    result = "\n".join(sorted(entries))
                except Exception as fe:
                    return Result.success(f"❌ Failed: {fe}")
            return Result.success(f"📂 **{safe}**\n\n{result}")

        if re.search(r"\b(write|save|create)\b", lower) and not re.search(r"\b(folder|directory|dir)\b", lower):
            path_m = re.search(r"(/[^\s]+|\b[\w./~-]+\.\w+)", ctx.user_input)
            if not path_m:
                return Result.success(f"📄 I need a file path. Try: 'write {USER_HOME}/notes/test.txt with content Hello'")
            safe, err = _safe_path(path_m.group(1))
            if err:
                return Result.success(f"❌ {err}")
            content_m = re.search(r"(?:with content|content|containing|text)\s+(.+)$", ctx.user_input, re.IGNORECASE | re.DOTALL)
            content = content_m.group(1).strip() if content_m else ""
            if not content:
                return Result.success(f"📄 What should I write to `{safe}`? Try: 'write {safe} with content Hello'")
            result = mcp_bridge.call_mcp_server("filesystem", "write_file", {"path": safe, "content": content}, context_intent=ctx.intent)
            if "error" in result.lower() or "failed" in result.lower():
                try:
                    with open(safe, "w") as f:
                        f.write(content)
                    result = f"Written to `{safe}` (fallback)"
                except Exception as fe:
                    return Result.success(f"❌ Failed: {fe}")
            return Result.success(f"📄 {result}")

        if re.search(r"\b(search|brave|web search)\b", lower):
            query_m = re.search(r"(?:search|brave search|web search)\s+(?:for\s+)?(.+)$", ctx.user_input, re.IGNORECASE)
            query = query_m.group(1).strip() if query_m else ctx.user_input
            result = mcp_bridge.call_mcp_server("brave-search", "search", {"query": query}, context_intent=ctx.intent)
            return Result.success(f"🔍 **MCP Brave Search**: {query}\n\n{result}")

        if re.search(r"\bgithub\b", lower):
            query_m = re.search(r"github\s+(.+)$", ctx.user_input, re.IGNORECASE)
            query = query_m.group(1).strip() if query_m else ctx.user_input
            result = mcp_bridge.call_mcp_server("github", "search_repositories", {"query": query}, context_intent=ctx.intent)
            return Result.success(f"🐙 **GitHub**: {query}\n\n{result}")

        if re.search(r"\b(drive|gdrive|google drive)\b", lower):
            query_m = re.search(r"(?:drive|gdrive|google drive)\s+(?:search\s+)?(.+)$", ctx.user_input, re.IGNORECASE)
            query = query_m.group(1).strip() if query_m else ""
            result = mcp_bridge.call_mcp_server("gdrive", "search_files", {"query": query}, context_intent=ctx.intent)
            return Result.success(f"📁 **Google Drive**: {query}\n\n{result}")

        if re.search(r"\b(obsidian|vault|note|notes)\b", lower):
            if re.search(r"\b(search|find|look for)\b", lower):
                query_m = re.search(r"(?:search|find|look for)\s+(?:in\s+(?:obsidian|vault|notes?)\s+)?(?:for\s+)?(.+)$", ctx.user_input, re.IGNORECASE)
                query = query_m.group(1).strip() if query_m else ctx.user_input
                result = mcp_bridge.call_mcp_server("obsidian", "search-vault", {"vault": "edith-brain", "query": query, "searchType": "both"}, context_intent=ctx.intent)
                return Result.success(f"📓 **Obsidian search**: {query}\n\n{result}")
            if re.search(r"\b(create|write|add|new note)\b", lower):
                title_m = re.search(r"(?:create|write|add|new)\s+(?:note\s+)?(?:called|named|titled|about)?\s+(.+?)(?:\s+with content\s+(.+))?$", ctx.user_input, re.IGNORECASE | re.DOTALL)
                title = (title_m.group(1).strip() if title_m else "New Note").rstrip()
                content = title_m.group(2).strip() if title_m and title_m.group(2) else ""
                filename = title if title.endswith(".md") else f"{title}.md"
                result = mcp_bridge.call_mcp_server("obsidian", "create-note", {"vault": "edith-brain", "filename": filename, "content": content or f"# {title}\n"}, context_intent=ctx.intent)
                return Result.success(f"📓 **Obsidian**: {result}")
            if re.search(r"\b(list|show|all notes)\b", lower):
                result = mcp_bridge.call_mcp_server("obsidian", "search-vault", {"vault": "edith-brain", "query": "", "searchType": "filename"}, context_intent=ctx.intent)
                return Result.success(f"📓 **Obsidian vault — all notes**\n\n{result}")
            # Default: read note by name
            note_m = re.search(r"(?:read\s+note|note|obsidian)\s+(.+)$", ctx.user_input, re.IGNORECASE)
            note = note_m.group(1).strip() if note_m else ""
            if note:
                filename = note if note.endswith(".md") else f"{note}.md"
                result = mcp_bridge.call_mcp_server("obsidian", "read-note", {"vault": "edith-brain", "filename": filename}, context_intent=ctx.intent)
                return Result.success(f"📓 **{note}**\n\n{result}")
            return Result.success("📓 Obsidian is connected (vault: edith-brain). Try: 'search notes for X', 'list notes', 'read note <title>', 'create note <title>'")

        if re.search(r"\b(spotify|music|song|playlist|track|album|artist|play|pause|skip|next track|previous track)\b", lower):
            if re.search(r"\b(play)\b", lower) and not re.search(r"\b(what.s playing|now playing|current)\b", lower):
                query_m = re.search(r"\bplay\s+(.+)$", ctx.user_input, re.IGNORECASE)
                query = query_m.group(1).strip() if query_m else ""
                if query:
                    result = mcp_bridge.call_mcp_server("spotify", "play", {"query": query}, context_intent=ctx.intent)
                else:
                    result = mcp_bridge.call_mcp_server("spotify", "resume", {}, context_intent=ctx.intent)
                return Result.success(f"🎵 {result}")
            if re.search(r"\b(pause|stop music)\b", lower):
                result = mcp_bridge.call_mcp_server("spotify", "pause", {}, context_intent=ctx.intent)
                return Result.success(f"⏸️ {result}")
            if re.search(r"\b(next|skip)\b", lower):
                result = mcp_bridge.call_mcp_server("spotify", "next", {}, context_intent=ctx.intent)
                return Result.success(f"⏭️ {result}")
            if re.search(r"\b(previous|prev|back)\b", lower):
                result = mcp_bridge.call_mcp_server("spotify", "previous", {}, context_intent=ctx.intent)
                return Result.success(f"⏮️ {result}")
            if re.search(r"\b(what.s playing|now playing|current track|current song)\b", lower):
                result = mcp_bridge.call_mcp_server("spotify", "get_current_track", {}, context_intent=ctx.intent)
                return Result.success(f"🎵 **Now playing**: {result}")
            if re.search(r"\b(search|find)\b", lower):
                query_m = re.search(r"(?:search|find)\s+(?:for\s+)?(?:on spotify\s+)?(.+)$", ctx.user_input, re.IGNORECASE)
                query = query_m.group(1).strip() if query_m else ctx.user_input
                result = mcp_bridge.call_mcp_server("spotify", "search", {"query": query}, context_intent=ctx.intent)
                return Result.success(f"🔍 **Spotify search**: {query}\n\n{result}")
            return Result.success(
                "🎵 Spotify is configured but needs setup first.\n"
                "1. Get a Client ID from https://developer.spotify.com/dashboard\n"
                "2. Run: `SPOTIFY_CLIENT_ID=<your_id> node /home/vaibhav/.nvm/versions/node/v20.20.2/lib/node_modules/spotify-mcp/dist/index.js auth`\n"
                "3. Add SPOTIFY_CLIENT_ID to vault: `vault set SPOTIFY_CLIENT_ID <your_id>`\n"
                "4. Enable in mcp_config.json: set `\"enabled\": true` for spotify"
            )

        # ── Google Workspace (Docs, Sheets, Drive, Gmail, Calendar, Slides, Forms) ──
        if re.search(r"\b(google\s+)?(docs?|sheets?|slides?|forms?|workspace)\b", lower) or \
           re.search(r"\b(spreadsheet|document|presentation)\b", lower):
            _GWS = "google-workspace"
            if re.search(r"\b(read|open|show|get)\b", lower) and re.search(r"\b(doc|document)\b", lower):
                doc_m = re.search(r"(?:doc(?:ument)?\s+(?:id\s+)?|read\s+)([a-zA-Z0-9_-]{25,}|https?://\S+)", ctx.user_input, re.IGNORECASE)
                doc_id = doc_m.group(1).strip() if doc_m else ""
                if not doc_id:
                    result = mcp_bridge.call_mcp_server(_GWS, "listGoogleDocs", {"account": "vaibhav"}, context_intent=ctx.intent)
                    return Result.success(f"📄 **Google Docs**\n\n{result}")
                result = mcp_bridge.call_mcp_server(_GWS, "readGoogleDoc", {"documentId": doc_id, "account": "vaibhav"}, context_intent=ctx.intent)
                return Result.success(f"📄 **Doc**\n\n{result}")
            if re.search(r"\b(list|show|all)\b", lower) and re.search(r"\b(doc|document)\b", lower):
                result = mcp_bridge.call_mcp_server(_GWS, "listGoogleDocs", {"account": "vaibhav"}, context_intent=ctx.intent)
                return Result.success(f"📄 **Google Docs**\n\n{result}")
            if re.search(r"\b(read|open|show|get)\b", lower) and re.search(r"\b(sheet|spreadsheet)\b", lower):
                sheet_m = re.search(r"(?:sheet\s+|spreadsheet\s+)([a-zA-Z0-9_-]{25,}|https?://\S+)", ctx.user_input, re.IGNORECASE)
                sheet_id = sheet_m.group(1).strip() if sheet_m else ""
                if not sheet_id:
                    result = mcp_bridge.call_mcp_server(_GWS, "listGoogleSheets", {"account": "vaibhav"}, context_intent=ctx.intent)
                    return Result.success(f"📊 **Google Sheets**\n\n{result}")
                result = mcp_bridge.call_mcp_server(_GWS, "readSpreadsheet", {"spreadsheetId": sheet_id, "account": "vaibhav"}, context_intent=ctx.intent)
                return Result.success(f"📊 **Sheet**\n\n{result}")
            if re.search(r"\b(list|show|all)\b", lower) and re.search(r"\b(sheet|spreadsheet)\b", lower):
                result = mcp_bridge.call_mcp_server(_GWS, "listGoogleSheets", {"account": "vaibhav"}, context_intent=ctx.intent)
                return Result.success(f"📊 **Google Sheets**\n\n{result}")
            if re.search(r"\b(list|show|all)\b", lower) and re.search(r"\b(slides?|presentation)\b", lower):
                result = mcp_bridge.call_mcp_server(_GWS, "listPresentations", {"account": "vaibhav"}, context_intent=ctx.intent)
                return Result.success(f"📊 **Google Slides**\n\n{result}")
            if re.search(r"\b(list|show)\b", lower) and re.search(r"\bform\b", lower):
                result = mcp_bridge.call_mcp_server(_GWS, "listForms", {"account": "vaibhav"}, context_intent=ctx.intent)
                return Result.success(f"📋 **Google Forms**\n\n{result}")
            # Default: show available workspace tools
            return Result.success(
                "📁 Google Workspace is connected (after auth). Available:\n"
                "• `list docs` / `read doc <id>` — Google Docs\n"
                "• `list sheets` / `read sheet <id>` — Google Sheets\n"
                "• `list presentations` — Google Slides\n"
                "• `list forms` — Google Forms\n"
                "• Use `drive` for file management\n\n"
                "⚠️ Run auth first: see `mcp status` for instructions."
            )

        enabled = mcp_bridge.get_enabled_servers()
        if not enabled:
            return Result.success(
                "🔌 No MCP servers currently enabled.\n"
                f"Enable servers in `{os.path.join(EDITH_PATH, 'mcp_config.json')}` and restart EDITH."
            )
        return Result.success(
            f"🔌 MCP active servers: {', '.join(enabled)}\n\n"
            "Filesystem commands:\n"
            "• `create 5 folders in Downloads` — create N folders with random names\n"
            "• `create folder named test in Downloads` — named folder\n"
            f"• `list {get_user_dir('downloads')}` — list directory\n"
            "• `read /path/to/file` — read file contents\n"
            "• `write /path/to/file with content ...` — write file\n"
            "• `move /src /dst` — move or rename\n"
            f"• `find *.py in {EDITH_PATH}` — search files\n"
            "• `info /path/to/file` — file metadata\n"
            "• `delete /path/to/file` — delete (requires confirmation)\n\n"
            "Obsidian vault:\n"
            "• `search notes for <query>` — search vault\n"
            "• `list notes` — show all notes\n"
            "• `read note <title>` — read a note\n"
            "• `create note <title> with content ...` — new note\n\n"
            "Spotify:\n"
            "• `play <song/artist/album>` — play music\n"
            "• `pause` / `next` / `previous` — playback control\n"
            "• `what's playing` — current track\n"
            "• `search spotify <query>` — search catalog\n\n"
            "Google Workspace:\n"
            "• `list docs` / `read doc <id>` — Google Docs\n"
            "• `list sheets` / `read sheet <id>` — Google Sheets\n"
            "• `list presentations` — Google Slides\n"
            "• `list forms` — Google Forms\n\n"
            "Other:\n"
            "• `search <query>` — Brave web search\n"
            "• `github <query>` — GitHub search\n"
            "• `drive <query>` — Google Drive search\n"
            "• `mcp status` — server status"
        )
    except Exception as e:
        return Result.from_exception(e)


def handle(intent: str, ctx: DispatchContext) -> str:
    result = _handle_mcp(ctx)
    if isinstance(result, Result):
        return str(result.value) if result.ok else str(result.error)
    return str(result)
