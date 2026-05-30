"""
handlers/misc.py — Miscellaneous intent handlers:
  vision, open_app, data_analysis, agent, council, decision,
  morning_briefing, self_improve, image_gen, video_summarize,
  repo_analyze, chat_fallback
"""

import os
import re
import subprocess
import datetime

from config import get_logger, USER_HOME
from errors import Result
from context import DispatchContext

log = get_logger("handlers.misc")


def _handle_vision(ctx: DispatchContext) -> Result:
    try:
        from vision import analyze_screenshot
        question = ctx.user_input if len(ctx.user_input.split()) > 3 else "What is on my screen right now?"
        r = analyze_screenshot(question)
        return Result.success(f"👁️ {r.value}") if r.ok else r
    except Exception as e:
        return Result.from_exception(e)


def _handle_open_app(ctx: DispatchContext) -> Result:
    try:
        text = ctx.user_input.lower().strip()
        m = re.match(r"^(?:open|launch|start)\s+(.+)$", text)
        app_name = m.group(1).strip() if m else text
        APP_MAP = {
            "chrome": ["chromium", "google-chrome", "google-chrome-stable"],
            "chromium": ["chromium"], "firefox": ["firefox"],
            "brave": ["brave", "brave-browser"], "opera": ["opera"],
            "browser": ["chromium", "firefox", "brave"],
            "terminal": ["konsole", "xterm", "gnome-terminal", "alacritty", "kitty"],
            "konsole": ["konsole"], "spotify": ["spotify"], "vlc": ["vlc"],
            "code": ["code"], "vscode": ["code"],
            "files": ["dolphin", "nautilus", "thunar"], "dolphin": ["dolphin"],
            "nautilus": ["nautilus"], "calculator": ["kcalc", "gnome-calculator"],
            "kcalc": ["kcalc"], "steam": ["steam"], "discord": ["discord"],
            "slack": ["slack"], "telegram": ["telegram-desktop", "telegram"],
            "notion": ["notion-app", "notion"], "obsidian": ["obsidian"],
            "gimp": ["gimp"], "inkscape": ["inkscape"], "blender": ["blender"],
            "thunderbird": ["thunderbird"], "libreoffice": ["libreoffice"],
            "okular": ["okular"], "mpv": ["mpv"], "celluloid": ["celluloid"],
            "audacity": ["audacity"], "kdenlive": ["kdenlive"],
            "handbrake": ["ghb"], "virtualbox": ["virtualbox"],
            "postman": ["postman"], "insomnia": ["insomnia"], "dbeaver": ["dbeaver"],
        }
        import shutil as _shutil
        candidates = APP_MAP.get(app_name, [app_name])
        binary = next((c for c in candidates if _shutil.which(c)), None)
        if binary:
            subprocess.Popen([binary], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                             start_new_session=True)
            return Result.success(f"Launched {app_name}.")
        try:
            subprocess.Popen(["xdg-open", app_name], stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL, start_new_session=True)
            return Result.success(f"Tried to open {app_name} — let me know if it didn't launch.")
        except Exception:
            return Result.success(f"Can't find '{app_name}' on your system. Is it installed?")
    except Exception as e:
        return Result.from_exception(e)


def _handle_data_analysis(ctx: DispatchContext) -> Result:
    from intent_dispatch import _extract_filepath
    try:
        filepath = _extract_filepath(ctx.user_input)
        if not filepath:
            return Result.success(f"📊 I need a file path. Try: 'analyze {USER_HOME}/data.csv what month had highest sales'")
        question = ctx.user_input.replace(filepath, "").strip()
        for word in ["analyze", "analyse", "read", "load", "open", "chart", "graph", "plot"]:
            question = re.sub(rf"\b{word}\b", "", question, flags=re.IGNORECASE).strip()
        from data_analyst import analyze_file
        r = analyze_file(filepath, question if question else None, "bar")
        return Result.success(f"📊 {r.value}") if r.ok else r
    except Exception as e:
        return Result.from_exception(e)


def _handle_agent(ctx: DispatchContext) -> Result:
    from intent_dispatch import set_pending_action
    try:
        from agent import plan_task
        task = ctx.user_input
        for prefix in ["agent ", "automate ", "plan "]:
            if task.lower().startswith(prefix):
                task = task[len(prefix):].strip()
        plan = plan_task(task)
        steps = [
            line.split(".", 1)[-1].strip()
            for line in plan.split("\n")
            if line.strip() and line.strip()[0].isdigit() and "." in line
        ]
        set_pending_action({"type": "agent", "task": task, "steps": steps})
        return Result.success(f"🤖 Agent Plan for '{task}':\n\n{plan}\n\n⚠️ Proceed with executing Phase 1? Type YES or NO.")
    except Exception as e:
        return Result.failure(f"🤖 Agent planning failed: {e}")


def _handle_council(ctx: DispatchContext) -> Result:
    try:
        from council import run_council
        return Result.success(f"🏛️ Council of Minds:\n\n{run_council(ctx.user_input)}")
    except Exception as e:
        return Result.from_exception(e)


def _handle_decision(ctx: DispatchContext) -> Result:
    try:
        from life_os import simulate_decision
        return Result.success(f"🔮 Decision Simulation:\n\n{simulate_decision(ctx.user_input)}")
    except Exception as e:
        return Result.from_exception(e)


def _handle_morning_briefing(ctx: DispatchContext) -> Result:
    parts = []
    try:
        from weather import get_current_weather, format_weather
        r = get_current_weather()
        parts.append(f"🌤️ Weather: {format_weather(r.value) if r.ok else 'Unavailable'}")
    except Exception:
        parts.append("🌤️ Weather: Unavailable")
    try:
        from email_reader import check_inbox
        r = check_inbox(limit=3, unread_only=True)
        parts.append(f"📧 Email: {r.value if r.ok else 'Unavailable'}")
    except Exception:
        parts.append("📧 Email: Unavailable")
    try:
        from calendar_reader import get_today_briefing
        r = get_today_briefing()
        parts.append(f"📅 Calendar: {r.value if r.ok else 'Unavailable'}")
    except Exception:
        parts.append("📅 Calendar: Unavailable")
    try:
        from life_os import format_open_loops
        loops = format_open_loops()
        if loops and loops.strip():
            parts.append(f"🔄 Open loops: {loops}")
    except Exception:
        pass
    return Result.success("Good morning, Boss. 🌅\n\n" + "\n\n".join(parts))


def _handle_self_improve(ctx: DispatchContext) -> Result:
    try:
        from self_improve import run_self_improvement
        from life_os import add_open_loop
        proposal = run_self_improvement()
        if proposal:
            add_open_loop(f"Review upgrade: {proposal[:100]}")
            return Result.success(f"🧬 Self-Improvement Proposal:\n\n{proposal}\n\n✅ Added to open loops for review.")
        return Result.success("🧬 No upgrade proposals generated (check internet).")
    except Exception as e:
        return Result.from_exception(e)


def _handle_image_gen(ctx: DispatchContext) -> Result:
    try:
        import subprocess as _sp
        from image_gen import generate_image
        prompt = ctx.user_input
        for kw in ["generate image", "create image", "draw", "visualize", "make image", "generate a", "create a"]:
            prompt = re.sub(rf"\b{re.escape(kw)}\b", "", prompt, flags=re.IGNORECASE).strip()
        prompt = prompt.strip(" of ")
        if len(prompt) < 3:
            return Result.success("🎨 What should I generate? Example: 'create image of a sunset over mountains'")
        path = generate_image(prompt)
        if not path:
            return Result.success("🎨 Image generation failed. Check internet connection.")
        path = os.path.abspath(path)
        if not os.path.isfile(path):
            return Result.success("File not found")
        try:
            _sp.Popen(["xdg-open", path], stdout=_sp.DEVNULL, stderr=_sp.DEVNULL)
        except Exception:
            pass
        return Result.success(f"🎨 Saved to: {path}\n(Opening viewer...)")
    except Exception as e:
        return Result.from_exception(e)


def _handle_video_summarize(ctx: DispatchContext) -> Result:
    try:
        import shutil as _sh
        url_match = re.search(r'https?://\S+', ctx.user_input)
        if not url_match:
            return Result.success("📹 Provide a YouTube URL. Example: 'summarize https://youtu.be/XXXXX'")
        if not _sh.which("yt-dlp"):
            return Result.success("📹 yt-dlp not installed. Run: pip install yt-dlp")
        url = url_match.group(0)
        from video_summarizer import download_audio, transcribe_audio, summarize_with_qwen
        audio = download_audio(url)
        if not audio:
            return Result.success("📹 Download failed. Check URL and yt-dlp.")
        transcript = transcribe_audio(audio)
        summary = summarize_with_qwen(transcript)
        try:
            os.remove(audio)
        except Exception:
            pass
        return Result.success(f"📹 Summary:\n\n{summary}")
    except Exception as e:
        return Result.from_exception(e)


def _handle_repo_analyze(ctx: DispatchContext) -> Result:
    match = re.search(r"https://github\.com/[\w\-]+/[\w\-]+", ctx.user_input)
    if not match:
        return Result.success("No GitHub URL found. Say: 'analyze repo https://github.com/owner/repo'")
    url = match.group(0)
    try:
        from repo_dna import analyze_repo, RepoFetchError, RepoAnalysisError
        analysis = analyze_repo(url)
        steal = "\n".join(f"  • [{i['effort'].upper()}] {i['title']}" for i in analysis.get("steal_this", [])) or "  none identified"
        wins  = "\n".join(f"  • {i['title']}" for i in analysis.get("quick_wins", [])) or "  none identified"
        return Result.success(
            f"**Repo DNA: {analysis.get('repo_name', url)}**\n\n"
            f"**Steal This:**\n{steal}\n\n**Quick Wins:**\n{wins}\n\n"
            f"**Summary:** {analysis.get('summary', '')}"
        )
    except Exception as exc:
        return Result.from_exception(exc)


def _handle_chat_fallback(ctx: DispatchContext) -> Result:
    from intent_dispatch import _run_local_exec
    try:
        _local = _run_local_exec(ctx.user_input)
        if _local:
            return Result.success(_local)
        from search import web_search, format_results
        feat_query = ctx.user_input.lower()
        if any(p in feat_query for p in ["what can you do", "your features", "what are your capabilities"]):
            return Result.success(
                "I'm your full-stack AI assistant, Boss. Here's what I've got:\n\n"
                "**Chat & Knowledge** — conversation, reasoning, coding help\n"
                "**Web Search** — real-time info, news, scores, prices\n"
                "**Email & Calendar** — read inbox, schedule events\n"
                "**Phone Control** — ring, SMS, battery, notifications\n"
                "**File & System** — browse files, run commands (with safety checks)\n"
                "**Vision** — analyze your screen or any image\n"
                "**Agent Mode** — multi-step task automation\n"
                "**Data Analysis** — CSV/Excel analysis with charts\n"
                "**Cognitive Suite** — Council of Minds, decision simulation, weekly briefings, drift detection, self-improvement\n\n"
                "Just ask naturally — I'll figure out what you need."
            )
        if re.search(r"\b(who won|score|result|ipl|cricket|football|election|stock|price|match|latest|today|today.s|current|news|recent|now|happening|update)\b", ctx.user_input.lower()):
            search_query = ctx.user_input
            try:
                from smart_router import smart_call
                rewrite_prompt = (
                    f"User asked: {ctx.user_input}\n"
                    "Write a short, highly specific web search query for DuckDuckGo to find the exact answer. "
                    "Reply ONLY with the search phrase."
                )
                rewritten = smart_call(rewrite_prompt, intent="reason").strip(' "\'\n')
                if rewritten and len(rewritten.split()) < 10:
                    search_query = rewritten
                    log.info(f"AI Query Rewriter: '{ctx.user_input}' -> '{search_query}'")
            except Exception as e:
                log.warning(f"Query rewrite failed: {e}")
            log.info(f"Auto-search triggered: {search_query[:80]}")
            results_r = web_search(search_query, num_results=3)
            search_text = format_results(results_r.value if results_r.ok else [])
            if search_text and "error" not in search_text.lower():
                today_str = datetime.datetime.now().strftime('%A, %d %B %Y')
                prompt = (
                    f"Current Date: {today_str}\n\nUser Query: {ctx.user_input}\n\n"
                    f"Search results:\n{search_text}\n\n"
                    "IMPORTANT: Verify dates against Current Date! Answer with EXACT facts. No fluff. Just the answer."
                )
                return Result.success(ctx.chat_fn(prompt, intent="search"))
        reply = ctx.chat_fn(ctx.user_input, intent=ctx.intent, source=getattr(ctx, "source", "widget"))
        if re.search(r"(i can search|search the web|don.t have.*real.time|real.time.*access|knowledge cutoff|can.t access|let me check|want me to.*search|up.to.date)", reply.lower()):
            log.info(f"LLM admitted need for search: {ctx.user_input[:50]}")
            results_r = web_search(ctx.user_input, num_results=3)
            search_text = format_results(results_r.value if results_r.ok else [])
            if search_text and "error" not in search_text.lower():
                today_str = datetime.datetime.now().strftime('%A, %d %B %Y')
                prompt = (
                    f"Current Date: {today_str}\n\nUser Query: {ctx.user_input}\n\n"
                    f"Search results:\n{search_text}\n\n"
                    "Extract the exact answer. Check against Current Date. Answer directly."
                )
                return Result.success(ctx.chat_fn(prompt, intent="search"))
        return Result.success(reply)
    except Exception as e:
        return Result.from_exception(e)


def handle(intent: str, ctx: DispatchContext) -> str:
    handlers = {
        "vision":          _handle_vision,
        "open_app":        _handle_open_app,
        "data_analysis":   _handle_data_analysis,
        "agent":           _handle_agent,
        "council":         _handle_council,
        "decision":        _handle_decision,
        "morning_briefing": _handle_morning_briefing,
        "self_improve":    _handle_self_improve,
        "image_gen":       _handle_image_gen,
        "video_summarize": _handle_video_summarize,
        "repo_analyze":    _handle_repo_analyze,
        "chat_fallback":   _handle_chat_fallback,
    }
    fn = handlers.get(intent, _handle_chat_fallback)
    result = fn(ctx)
    if isinstance(result, Result):
        return str(result.value) if result.ok else str(result.error)
    return str(result)
