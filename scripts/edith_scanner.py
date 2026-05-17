#!/usr/bin/env python3
"""
EDITH Flow Scanner — drop in ~/EDITH, run: python edith_scanner.py
Auto-scans all .py files. Re-run anytime to refresh.
"""
import ast, os, json, sys, webbrowser, logging
from pathlib import Path
from datetime import datetime

logger = logging.getLogger("edith_scanner")

LAYER_MAP = {
    "background_daemon":"entry","chat_server":"entry","edith_widget":"entry",
    "telegram_bot":"entry","wake_listener":"entry","edith":"entry",
    "orchestrator":"brain","intent":"brain","intent_dispatch":"brain",
    "smart_router":"brain","context":"brain","config":"brain",
    "smart_memory":"memory","cognitive_profile":"memory","session":"memory",
    "graph_memory":"memory","episodic_memory":"memory","consolidation":"memory",
    "voice":"io","search":"io","weather":"io","email_reader":"io",
    "calendar_reader":"io","phone":"io","whatsapp":"io","vision":"io",
    "ocr":"io","image_gen":"io","video_summarizer":"io","data_analyst":"io",
    "circuit_breaker":"infra","trace_logger":"infra","feedback_tagger":"infra",
    "tuner":"infra","monitor":"infra","errors":"infra","mcp_bridge":"infra",
    "compound_dag":"infra","conversation_dna":"infra","ml_router":"infra",
    "agent":"infra","devlog":"infra","tools":"infra","dashboard":"infra",
    "model_manager":"infra","edith_arch_updater":"infra",
    "vault":"security","security_audit":"security","sandbox":"security",
    "rag":"code","code_rag":"code","coding_style":"code",
    "council":"vision","life_os":"vision","self_improve":"vision",
}

LAYER_META = {
    "entry":    {"label":"Entry points","desc":"Where you talk to EDITH","color":"#7F77DD"},
    "brain":    {"label":"Brain","desc":"Core thinking and routing","color":"#1D9E75"},
    "memory":   {"label":"Memory","desc":"What EDITH remembers","color":"#D85A30"},
    "io":       {"label":"Eyes & hands","desc":"External world integration","color":"#378ADD"},
    "infra":    {"label":"Infrastructure","desc":"Plumbing that keeps it alive","color":"#888780"},
    "security": {"label":"Security","desc":"Locks, guards, encryption","color":"#D4537E"},
    "code":     {"label":"Code brain","desc":"Understands your codebase","color":"#BA7517"},
    "vision":   {"label":"Big-picture AI","desc":"Council, life OS, self-improve","color":"#639922"},
}

HUMAN_PURPOSE = {
    "background_daemon":"Runs everything in the background. It boots up chat_server and wake_listener as child processes, schedules all the daily jobs (memory consolidation at 2:30am, backups at 3am, weather pre-fetch at 7am), and auto-restarts anything that crashes.",
    "chat_server":"The front door of EDITH. Every message you send — from the widget, browser, or API — lands here first. FastAPI server that hands things off to the orchestrator and streams responses back to you in real time.",
    "edith_widget":"The always-on-top PyQt6 desktop window. Press Ctrl+Space to summon or dismiss it. Has two panels: a chat view and a live dashboard. Talks to chat_server over HTTP.",
    "telegram_bot":"Lets you talk to EDITH from your phone. Runs a long-polling Telegram bot, routes your messages to the orchestrator, and fires scheduled briefings. Only your chat ID can use it.",
    "wake_listener":"Always listening in the background using Vosk. When it hears the wake word 'EDITH', it starts recording and hands audio off to the voice pipeline.",
    "edith":"The CLI entry point. Run this for an interactive menu, smoke tests, and system health checks. Good for debugging when the daemon isn't running.",
    "orchestrator":"The brain of EDITH. Every single message passes through here. It scans for dangerous inputs, recalls relevant memories, assembles context, detects compound queries, and hands off to intent detection. The conductor of the whole orchestra.",
    "intent":"Figures out what you actually want. Tries regex patterns first (fast), then a trained ML classifier, then asks an LLM if still unsure. Covers 21+ intents from weather to shell commands to council debates.",
    "intent_dispatch":"The switchboard. Once intent is known, this maps it to the right handler function via a dispatch table. Also handles HITL — it'll ask 'are you sure?' before doing anything destructive.",
    "smart_router":"Picks which AI model answers your query. Privacy gate first (vault/shell/email always go local). Then tries Groq → Gemini → NVIDIA → OpenRouter → local Ollama, checking circuit breakers and daily rate limits at each step.",
    "context":"A tiny dataclass called DispatchContext. It's just a bag that carries all the shared objects (orchestrator, session, memory, router) through the dispatch pipeline without circular imports.",
    "config":"Single source of truth for all constants, model names, paths, and danger keywords. Also has safe wrappers for Ollama calls. If you need to change a setting, this is where you go.",
    "smart_memory":"Two-layer memory system. Hot layer: LRU RAM cache of 200 items for sub-millisecond recall. Cold layer: SQLite with full-text search for older memories. Every remember() call writes to both simultaneously.",
    "cognitive_profile":"Tracks who you are over time. Logs observations about your behaviour, maintains a prime directive about your goals, and runs drift detection to notice when your patterns change.",
    "session":"Manages conversation state in SQLite so you can pick up where you left off — even across devices. Tracks the current session, query log, and events.",
    "graph_memory":"Builds a knowledge graph from your conversations. Extracts subject-verb-object triples and stores them in a NetworkX graph. Lets EDITH answer questions like 'what do I know about X?'",
    "episodic_memory":"Logs conversation episodes like a diary — what was discussed, when, and what the outcome was. Used during memory recall to give context about past interactions.",
    "consolidation":"Runs at 2:30am every night. Merges similar memories, deduplicates overlapping facts, prunes noise, and compacts old episodes. Memory spring-cleaning.",
    "voice":"All the audio plumbing. Speaks via Piper TTS (fast, local). Listens via Whisper.cpp (accurate, local). WebRTC VAD guards the mic so EDITH doesn't hear her own voice and loop.",
    "search":"Searches the web. Tries DuckDuckGo first. Falls back to your self-hosted SearXNG instance. Returns cleaned results ready for the LLM.",
    "weather":"Fetches current weather and forecasts from Open-Meteo. No API key needed. Returns formatted strings ready to speak or display.",
    "email_reader":"Reads your Gmail inbox over IMAP. Fetches unread messages, parses them, and returns summaries. Marked as local-only — never goes to cloud LLMs.",
    "calendar_reader":"Reads and creates Google Calendar events via OAuth2. Handles token refresh automatically. Returns events in human-readable format.",
    "phone":"Talks to your Android phone via KDE Connect CLI. Can ring it, send SMS, read notifications, check battery level, and more.",
    "whatsapp":"Sends WhatsApp messages through a local bridge server (whatsapp-web.js). HTTP API wrapper — send message, that's it.",
    "vision":"Takes a screenshot of your screen, runs OCR on it, then passes it to an Ollama vision model for analysis. Lets EDITH literally see what you're looking at.",
    "ocr":"Extracts text from images using Tesseract. Called by vision.py and directly when you point EDITH at an image file.",
    "image_gen":"Generates images by calling an external image generation API. Saves results to the images/ folder.",
    "video_summarizer":"Downloads a video with yt-dlp, transcribes it with Whisper, then summarises the transcript with an LLM. Handles YouTube links and direct video URLs.",
    "data_analyst":"Loads CSV and Excel files into pandas, runs analysis, and generates matplotlib charts. Saves charts to the charts/ folder.",
    "circuit_breaker":"Stops EDITH from hammering a broken service. Each provider gets its own breaker with three states: CLOSED (working), OPEN (broken, skip it), HALF_OPEN (testing recovery). Uses exponential backoff.",
    "trace_logger":"Gives every request a unique TRACE_ID and logs each processing step with timing. Stores everything in trace_log.db. Lets you debug exactly where something went slow or wrong.",
    "feedback_tagger":"Collects your thumbs up/down signals after responses. Also detects implicit feedback (you rephrasing = implicit thumbs down). Feeds into the auto-tuner.",
    "tuner":"Adjusts the routing weights based on your feedback history. Runs weekly. If Groq keeps getting thumbs down, it gets lower priority. Slow self-optimisation.",
    "monitor":"Watches system resources every 10 minutes. Alerts if RAM, CPU, or disk cross thresholds. Also checks your phone battery via KDE Connect and nudges you to take breaks.",
    "errors":"A tiny Result dataclass with four fields: ok, value, error, error_type. Intended to standardise error handling across all 50+ modules — currently only used in a few places.",
    "mcp_bridge":"Connects MCP (Model Context Protocol) servers into EDITH's brain. Drop a server config into mcp_config.json and it becomes available as a tool automatically. Currently has Filesystem MCP. GitHub, Brave Search, Notion queued.",
    "compound_dag":"Handles multi-part queries. Detects when you say 'do X and then Y and also Z', splits it into a task graph, and executes steps in dependency order. Like a mini workflow engine.",
    "conversation_dna":"Adapts EDITH's tone and response depth based on context. More casual in the evening, more technical when you're in a coding session, more concise when you're clearly in a hurry.",
    "ml_router":"A trained scikit-learn classifier that helps intent.py when regex patterns aren't confident enough. Gets retrained automatically as feedback data accumulates.",
    "agent":"Autonomous multi-step task executor. Given a goal, it plans steps, calls tools, observes results, and loops until done. Has a dry-run mode so you can preview what it'll do before it does it.",
    "devlog":"Your persistent development journal. Append entries via EDITH, syncs to Simplenote automatically. Searchable, queryable, and summarisable.",
    "tools":"Simple file utilities: write_file and delete_file. Thin wrappers that handle path safety. Being phased out as Filesystem MCP takes over.",
    "dashboard":"Legacy dashboard backend. Most of its functionality has been moved into chat_server.py endpoints. Still running but a candidate for removal.",
    "model_manager":"Manages local Ollama models. Checks what's installed, pulls missing models, pre-warms them into RAM before they're needed so first responses aren't slow.",
    "edith_arch_updater":"Scans the entire codebase and generates an architecture report using an LLM. What produced the doc you uploaded. Run manually when you want a fresh audit.",
    "vault":"Encrypted secret store using Fernet encryption and Argon2 key derivation. The secure alternative to the .env file. Stores API keys, passwords, tokens. Key file lives at chmod 400.",
    "security_audit":"Runs automated security checks. Looks for common vulnerabilities, exposed secrets, unsafe subprocess calls. Run manually or scheduled.",
    "sandbox":"Isolates dangerous shell commands before execution. Checks against an allowlist of safe commands. Everything else needs explicit HITL confirmation.",
    "rag":"Indexes your notes/ folder into ChromaDB vector embeddings. When you ask EDITH something, it checks your notes first before going to an LLM. Your personal knowledge base.",
    "code_rag":"Indexes your repos/ folder into ChromaDB. Lets EDITH answer questions about your own codebase — 'where is the auth logic?', 'what does function X do?'",
    "coding_style":"Enforces your personal coding preferences stored in coding_personality.json. When EDITH writes code for you, it follows your style — naming conventions, comment style, patterns you prefer.",
    "council":"Runs four AI personas in parallel: Strategist (big picture), Critic (finds flaws), Builder (practical steps), Wildcard (unexpected angles). Each debates the question, then a fifth call synthesises their outputs. Expensive but powerful.",
    "life_os":"Simulates decisions across five life branches. Generates weekly briefings every Sunday at 9pm. Tracks open loops — things you said you'd do but haven't. A personal life operating system.",
    "self_improve":"Scans ArXiv for AI papers relevant to EDITH's architecture. Summarises findings and proposes concrete upgrades. Runs weekly. EDITH improving herself.",
}

INTENTS = [
    {"id":"chat","label":"General chat","desc":"Just having a conversation. No special action needed — goes straight to the LLM with your full context and memory."},
    {"id":"weather","label":"Weather","desc":"Fetches current conditions and forecast from Open-Meteo. Formats it nicely and optionally speaks it aloud."},
    {"id":"email","label":"Email","desc":"Reads your Gmail inbox over IMAP. Local-only intent — never sent to cloud LLMs for privacy."},
    {"id":"calendar","label":"Calendar","desc":"Reads or creates Google Calendar events. OAuth2 auth handled automatically including token refresh."},
    {"id":"search","label":"Web search","desc":"Searches DuckDuckGo or your self-hosted SearXNG. Returns cleaned results fed back into the LLM for a synthesised answer."},
    {"id":"shell","label":"Shell command","desc":"Runs a terminal command. Goes through the sandbox first. Safe commands auto-execute; anything risky needs your confirmation."},
    {"id":"vision","label":"Screen vision","desc":"Takes a screenshot, OCRs it, then asks a vision model to analyse what it sees. Lets EDITH see your screen."},
    {"id":"phone","label":"Phone control","desc":"Talks to your Android via KDE Connect. Ring it, read notifications, check battery, send SMS."},
    {"id":"whatsapp","label":"WhatsApp","desc":"Sends a WhatsApp message through the local bridge server."},
    {"id":"notes","label":"Notes / RAG","desc":"Queries your notes/ folder via ChromaDB embeddings. Searches your personal knowledge base before going to an LLM."},
    {"id":"code","label":"Code help","desc":"Queries your code repos via ChromaDB. Can answer questions about your own codebase. Applies your coding style preferences."},
    {"id":"council","label":"Council of Minds","desc":"Fires four AI personas in parallel (Strategist, Critic, Builder, Wildcard) then synthesises their debate. Use for hard decisions."},
    {"id":"lifeos","label":"Life OS","desc":"Runs a five-branch decision simulation or generates your weekly briefing. Tracks open loops."},
    {"id":"memory","label":"Memory query","desc":"Directly queries smart_memory, ChromaDB, or the knowledge graph. 'What do you know about X?'"},
    {"id":"agent","label":"Agent task","desc":"Hands off to the autonomous agent for multi-step execution. Plans, acts, observes, loops until done. Has dry-run preview mode."},
    {"id":"image","label":"Image generation","desc":"Generates an image via an external API. Saves to images/ folder."},
    {"id":"video","label":"Video summary","desc":"Downloads a video, transcribes with Whisper, summarises with an LLM."},
    {"id":"data","label":"Data analysis","desc":"Loads a CSV or Excel file, runs pandas analysis, draws matplotlib charts. Saves to charts/ folder."},
    {"id":"voice","label":"Voice toggle","desc":"Enables or disables voice output (Piper TTS). Also handles direct speak requests."},
    {"id":"vault","label":"Vault / secrets","desc":"Reads or writes to the encrypted vault. Local-only — never touches cloud LLMs."},
    {"id":"wake","label":"Wake / greeting","desc":"Simple acknowledgement when you greet EDITH or just want to check she's alive."},
]

FLOW_STEPS = [
    {"label":"You say something","desc":"Via Telegram, voice, widget, or browser — any input surface works","layer":"entry","modules":["telegram_bot","wake_listener","edith_widget","chat_server","edith"]},
    {"label":"chat_server.py receives it","desc":"FastAPI endpoint catches the request and starts a response stream","layer":"entry","modules":["chat_server"]},
    {"label":"orchestrator.py takes over","desc":"Danger scan → memory recall → context assembly → compound detection","layer":"brain","modules":["orchestrator","smart_memory","cognitive_profile","session","compound_dag","conversation_dna"]},
    {"label":"intent.py classifies it","desc":"Regex first → ML classifier → LLM fallback. One of 21+ intents assigned","layer":"brain","modules":["intent","ml_router"]},
    {"label":"intent_dispatch.py routes it","desc":"Dispatch table maps intent to handler. HITL confirmation if destructive","layer":"brain","modules":["intent_dispatch","context","sandbox"]},
    {"label":"Handler does the work","desc":"LLM call via smart_router, or email/calendar/search/shell/tools","layer":"io","modules":["smart_router","circuit_breaker","search","weather","email_reader","calendar_reader","phone","whatsapp","vision","voice","image_gen","video_summarizer","data_analyst","agent","council","life_os","rag","code_rag","tools","mcp_bridge"]},
    {"label":"Response comes back","desc":"Text, voice output, Telegram message, or SSE stream to the widget","layer":"entry","modules":["chat_server","voice","telegram_bot","edith_widget"]},
    {"label":"Memory is saved","desc":"RAM cache + SQLite FTS + ChromaDB vector store all updated","layer":"memory","modules":["smart_memory","graph_memory","episodic_memory","session","trace_logger","feedback_tagger"]},
]

def count_lines(path):
    try: return len(path.read_text(errors="replace").splitlines())
    except: return 0

def extract_docstring(path):
    try:
        tree = ast.parse(path.read_text(errors="replace"))
        return ast.get_docstring(tree) or ""
    except: return ""

def extract_first_comment(path):
    try:
        for line in path.read_text(errors="replace").splitlines()[:8]:
            l = line.strip()
            if l.startswith("#") and len(l) > 5:
                return l.lstrip("#").strip()
    except (ValueError, KeyError, AttributeError, OSError) as e:
        logger.debug(f"Scanner skip: {e}")
    return ""

def extract_imports(path, all_stems):
    local = set()
    try:
        tree = ast.parse(path.read_text(errors="replace"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    s = alias.name.split(".")[0]
                    if s in all_stems: local.add(s)
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    s = node.module.split(".")[0]
                    if s in all_stems: local.add(s)
    except (ValueError, KeyError, AttributeError, SyntaxError) as e:
        logger.debug(f"Scanner skip: {e}")
    return list(local)

def extract_functions(path):
    funcs = []
    try:
        tree = ast.parse(path.read_text(errors="replace"))
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if not node.name.startswith("__"):
                    doc = ast.get_docstring(node) or ""
                    funcs.append({"name": node.name, "doc": doc[:120]})
    except (ValueError, KeyError, AttributeError, SyntaxError) as e:
        logger.debug(f"Scanner skip: {e}")
    return funcs[:20]

def scan(edith_dir="."):
    edith_path = Path(edith_dir)
    py_files = sorted(edith_path.glob("*.py"))
    all_stems = {p.stem for p in py_files}
    modules = []
    skip = {"edith_scanner"}
    for p in py_files:
        stem = p.stem
        if stem.startswith("_") or stem in skip: continue
        doc = extract_docstring(p) or extract_first_comment(p)
        purpose = HUMAN_PURPOSE.get(stem, (doc[:200]+"…") if len(doc)>200 else doc or f"{stem}.py — no docstring yet.")
        calls = extract_imports(p, all_stems - {stem})
        funcs = extract_functions(p)
        modules.append({
            "id": stem,
            "name": p.name,
            "layer": LAYER_MAP.get(stem, "infra"),
            "lines": count_lines(p),
            "purpose": purpose,
            "calls": calls,
            "functions": funcs,
        })
    return modules

def build_html(modules, scanned_at, edith_dir):
    mod_json    = json.dumps(modules, ensure_ascii=False)
    flow_json   = json.dumps(FLOW_STEPS, ensure_ascii=False)
    intent_json = json.dumps(INTENTS, ensure_ascii=False)
    lmeta_json  = json.dumps(LAYER_META, ensure_ascii=False)
    total       = len(modules)
    total_lines = sum(m["lines"] for m in modules)

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>EDITH — How Things Work</title>
<style>
*{{box-sizing:border-box;margin:0;padding:0}}
body{{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;background:#0e0e0f;color:#e0dfda;min-height:100vh}}
a{{color:inherit;text-decoration:none}}
::-webkit-scrollbar{{width:6px;height:6px}}
::-webkit-scrollbar-track{{background:#1a1a18}}
::-webkit-scrollbar-thumb{{background:#3a3a38;border-radius:3px}}

/* LAYOUT */
#app{{display:flex;height:100vh;overflow:hidden}}
#sidebar{{width:280px;flex-shrink:0;border-right:1px solid #2a2a28;display:flex;flex-direction:column;overflow:hidden}}
#main{{flex:1;overflow-y:auto;display:flex;flex-direction:column}}

/* SIDEBAR */
#sb-head{{padding:16px;border-bottom:1px solid #2a2a28}}
#sb-head h1{{font-size:16px;font-weight:500;margin-bottom:2px}}
#sb-head .sub{{font-size:11px;color:#5a5a58}}
#search-wrap{{padding:10px 12px;border-bottom:1px solid #2a2a28}}
#search{{width:100%;background:#1a1a18;border:1px solid #2a2a28;border-radius:6px;padding:6px 10px;font-size:12px;color:#e0dfda;outline:none}}
#search:focus{{border-color:#4a4a48}}
#layer-filters{{padding:8px 12px;border-bottom:1px solid #2a2a28;display:flex;flex-wrap:wrap;gap:4px}}
.lf{{font-size:10px;padding:3px 8px;border-radius:20px;border:1px solid #2a2a28;color:#9b9a94;cursor:pointer;transition:all .12s;white-space:nowrap}}
.lf:hover{{border-color:#5a5a58;color:#e0dfda}}
.lf.on{{color:#e0dfda}}
#mod-list{{flex:1;overflow-y:auto;padding:6px 0}}
.mod-item{{padding:8px 14px;cursor:pointer;border-left:3px solid transparent;transition:all .12s}}
.mod-item:hover{{background:#1a1a18}}
.mod-item.sel{{background:#1a1a18}}
.mod-item .mi-name{{font-size:12px;font-weight:500}}
.mod-item .mi-lines{{font-size:10px;color:#5a5a58;margin-top:1px}}
.mod-item.hidden{{display:none}}

/* MAIN TABS */
#tabs{{display:flex;gap:0;border-bottom:1px solid #2a2a28;flex-shrink:0;background:#0e0e0f;position:sticky;top:0;z-index:10}}
.tab{{font-size:13px;padding:12px 18px;cursor:pointer;color:#6b6a65;border-bottom:2px solid transparent;transition:all .12s;white-space:nowrap}}
.tab:hover{{color:#c0bfba}}
.tab.on{{color:#e0dfda;border-bottom-color:#e0dfda}}
#tab-content{{padding:24px;flex:1}}
.view{{display:none}}
.view.on{{display:block}}

/* STATS BAR */
.stats{{display:flex;gap:12px;flex-wrap:wrap;margin-bottom:24px}}
.stat{{background:#1a1a18;border:1px solid #2a2a28;border-radius:8px;padding:10px 16px;min-width:100px}}
.stat .val{{font-size:20px;font-weight:500}}
.stat .lbl{{font-size:11px;color:#6b6a65;margin-top:2px}}

/* FLOW */
#flow-wrap{{display:flex;flex-direction:column;align-items:center;gap:0;max-width:560px;margin:0 auto}}
.fstep{{width:100%;border-radius:10px;padding:14px 18px;cursor:pointer;transition:all .15s;border:1px solid transparent;margin-bottom:0}}
.fstep:hover{{filter:brightness(1.12)}}
.fstep.active{{box-shadow:0 0 0 2px #fff2}}
.fstep .fs-label{{font-size:14px;font-weight:500}}
.fstep .fs-desc{{font-size:12px;margin-top:3px;opacity:.75}}
.farrow{{width:2px;height:28px;margin:0 auto;opacity:.35}}
.fstep-mods{{width:100%;background:#141413;border:1px solid #2a2a28;border-radius:10px;padding:12px 14px;margin-top:-1px;display:none}}
.fstep-mods.open{{display:block}}
.fstep-mods .fmtitle{{font-size:11px;color:#6b6a65;margin-bottom:8px;text-transform:uppercase;letter-spacing:.06em}}
.fmod-pills{{display:flex;flex-wrap:wrap;gap:5px}}
.fpill{{font-size:11px;padding:3px 9px;border-radius:20px;cursor:pointer;transition:all .12s;border:1px solid #2a2a28;color:#9b9a94}}
.fpill:hover{{color:#e0dfda;border-color:#5a5a58}}

/* MODULE DETAIL */
#detail{{background:#141413;border:1px solid #2a2a28;border-radius:12px;padding:20px;margin-top:0;display:none;position:sticky;top:60px}}
#detail h2{{font-size:16px;font-weight:500;margin-bottom:4px}}
#detail .dmeta{{font-size:11px;color:#6b6a65;margin-bottom:14px}}
#detail .dsec{{margin-bottom:14px}}
#detail .dsec b{{font-size:11px;font-weight:500;color:#6b6a65;text-transform:uppercase;letter-spacing:.06em;display:block;margin-bottom:6px}}
#detail .dsec p{{font-size:13px;color:#c0bfba;line-height:1.65}}
.pill-list{{display:flex;flex-wrap:wrap;gap:5px}}
.dp{{font-size:11px;padding:3px 9px;border-radius:20px;border:1px solid #2a2a28;color:#9b9a94;cursor:pointer;transition:all .12s}}
.dp:hover{{color:#e0dfda;border-color:#5a5a58}}
.fntag{{font-size:11px;padding:3px 9px;border-radius:6px;background:#1e1e1c;color:#7b7a74;font-family:monospace;cursor:default}}
.fntag:hover{{color:#c0bfba}}

/* INTENTS */
.intent-grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(280px,1fr));gap:10px}}
.intent-card{{background:#141413;border:1px solid #2a2a28;border-radius:10px;padding:12px 14px;cursor:pointer;transition:all .12s}}
.intent-card:hover{{border-color:#4a4a48;background:#1a1a18}}
.intent-card .ic-label{{font-size:13px;font-weight:500;color:#e0dfda;margin-bottom:4px}}
.intent-card .ic-desc{{font-size:12px;color:#6b6a65;line-height:1.5}}

/* LAYERS */
.layer-section{{margin-bottom:28px}}
.layer-head{{display:flex;align-items:center;gap:10px;margin-bottom:12px;cursor:pointer}}
.layer-dot{{width:9px;height:9px;border-radius:50%;flex-shrink:0}}
.layer-head .lh-title{{font-size:14px;font-weight:500}}
.layer-head .lh-desc{{font-size:12px;color:#6b6a65}}
.layer-head .lh-ct{{font-size:11px;color:#5a5a58;border:1px solid #2a2a28;border-radius:20px;padding:2px 7px;margin-left:auto}}
.layer-mods{{display:grid;grid-template-columns:repeat(auto-fill,minmax(220px,1fr));gap:8px}}
.mc{{background:#141413;border:1px solid #2a2a28;border-radius:8px;padding:10px 12px;cursor:pointer;transition:all .12s}}
.mc:hover{{background:#1a1a18;border-color:#4a4a48}}
.mc.sel{{border-width:1.5px}}
.mc .mc-name{{font-size:12px;font-weight:500}}
.mc .mc-lines{{font-size:10px;color:#5a5a58;margin-top:2px}}
.mc .mc-pur{{font-size:11px;color:#6b6a65;margin-top:4px;line-height:1.4}}
</style>
</head>
<body>
<div id="app">

<div id="sidebar">
  <div id="sb-head">
    <h1>EDITH</h1>
    <div class="sub">How Things Work &middot; {scanned_at}</div>
  </div>
  <div id="search-wrap">
    <input id="search" placeholder="Search modules..." oninput="filterMods(this.value)">
  </div>
  <div id="layer-filters">
    <div class="lf on" style="border-color:#4a4a48;color:#e0dfda" onclick="filterLayer('all',this)">All</div>
  </div>
  <div id="mod-list"></div>
</div>

<div id="main">
  <div id="tabs">
    <div class="tab on" onclick="showTab('flow',this)">Message flow</div>
    <div class="tab" onclick="showTab('modules',this)">All modules</div>
    <div class="tab" onclick="showTab('intents',this)">Intent types</div>
  </div>

  <div id="tab-content">

    <div class="view on" id="view-flow">
      <div class="stats">
        <div class="stat"><div class="val">{total}</div><div class="lbl">Modules</div></div>
        <div class="stat"><div class="val">{total_lines:,}</div><div class="lbl">Lines of code</div></div>
        <div class="stat"><div class="val">5</div><div class="lbl">LLM providers</div></div>
        <div class="stat"><div class="val">21+</div><div class="lbl">Intent types</div></div>
      </div>
      <div style="display:flex;gap:24px;align-items:flex-start">
        <div id="flow-wrap"></div>
        <div id="detail" style="width:340px;flex-shrink:0"></div>
      </div>
    </div>

    <div class="view" id="view-modules">
      <div id="modules-wrap"></div>
    </div>

    <div class="view" id="view-intents">
      <p style="font-size:13px;color:#6b6a65;margin-bottom:16px">Every intent EDITH can recognise. Click one to see how it works.</p>
      <div class="intent-grid" id="intent-grid"></div>
      <div id="intent-detail" style="display:none;margin-top:16px;background:#141413;border:1px solid #2a2a28;border-radius:10px;padding:16px 18px"></div>
    </div>

  </div>
</div>
</div>

<script>
const MODS  = {mod_json};
const FLOW  = {flow_json};
const INTENTS = {intent_json};
const LMETA = {lmeta_json};

let selMod = null;
let activeLayer = 'all';
let activeStep = null;

/* ── SIDEBAR ── */
function buildSidebar() {{
  const lf = document.getElementById('layer-filters');
  Object.entries(LMETA).forEach(([id,lm])=>{{
    const b=document.createElement('div');
    b.className='lf';
    b.textContent=lm.label;
    b.style.borderColor=lm.color+'44';
    b.style.color=lm.color;
    b.onclick=()=>filterLayer(id,b);
    lf.appendChild(b);
  }});
  renderSidebar();
}}

function renderSidebar() {{
  const list = document.getElementById('mod-list');
  list.innerHTML='';
  const q = document.getElementById('search').value.toLowerCase().trim();
  MODS.forEach(m=>{{
    const layerOk = activeLayer==='all' || m.layer===activeLayer;
    const searchOk = !q || m.name.toLowerCase().includes(q) || m.purpose.toLowerCase().includes(q);
    const div=document.createElement('div');
    div.className='mod-item'+((!layerOk||!searchOk)?' hidden':'')+(selMod===m.id?' sel':'');
    const lm=LMETA[m.layer]||{{color:'#888'}};
    div.style.borderLeftColor=selMod===m.id?lm.color:'transparent';
    div.innerHTML=`<div class="mi-name" style="color:${{lm.color}}">${{m.name}}</div><div class="mi-lines">${{m.lines}} lines &middot; ${{m.layer}}</div>`;
    div.onclick=()=>selectMod(m.id);
    list.appendChild(div);
  }});
}}

function filterMods(v) {{ renderSidebar(); }}

function filterLayer(id,btn) {{
  activeLayer=id;
  document.querySelectorAll('.lf').forEach(b=>{{b.classList.remove('on');b.style.fontWeight='';b.style.opacity='.7'}});
  btn.classList.add('on');btn.style.fontWeight='500';btn.style.opacity='1';
  renderSidebar();
}}

/* ── MODULE DETAIL ── */
function selectMod(id) {{
  selMod=id;
  renderSidebar();
  const m=MODS.find(x=>x.id===id);
  if(!m) return;
  const lm=LMETA[m.layer]||{{color:'#888'}};
  const calledBy=MODS.filter(x=>x.calls&&x.calls.includes(id)).map(x=>x.name);
  const d=document.getElementById('detail');
  d.style.display='block';
  d.innerHTML=`
    <h2 style="color:${{lm.color}}">${{m.name}}</h2>
    <div class="dmeta">${{m.layer.toUpperCase()}} &middot; ${{m.lines}} lines</div>
    <div class="dsec"><b>What it does</b><p>${{m.purpose}}</p></div>
    ${{m.calls&&m.calls.length?`<div class="dsec"><b>Talks to &rarr;</b><div class="pill-list">${{m.calls.map(c=>`<span class="dp" onclick="selectMod('${{c}}')">${{c}}.py</span>`).join('')}}</div></div>`:''}}
    ${{calledBy.length?`<div class="dsec"><b>&larr; Used by</b><div class="pill-list">${{calledBy.map(c=>`<span class="dp" onclick="selectMod('${{c.replace('.py','')}}')">${{c}}</span>`).join('')}}</div></div>`:''}}
    ${{m.functions&&m.functions.length?`<div class="dsec"><b>Functions inside</b><div class="pill-list">${{m.functions.map(f=>`<span class="fntag" title="${{f.doc||'no docstring'}}">${{f.name}}()</span>`).join('')}}</div></div>`:''}}
  `;
  document.querySelectorAll('.mc').forEach(el=>el.classList.remove('sel'));
  const mc=document.getElementById('mc-'+id);
  if(mc){{mc.classList.add('sel');mc.style.borderColor=lm.color;}}
}}

/* ── FLOW TAB ── */
function buildFlow() {{
  const wrap=document.getElementById('flow-wrap');
  FLOW.forEach((step,i)=>{{
    const lm=LMETA[step.layer]||{{color:'#888'}};
    const stepDiv=document.createElement('div');
    stepDiv.innerHTML=`
      <div class="fstep" id="fstep-${{i}}" style="background:${{lm.color}}1a;border-color:${{lm.color}}44" onclick="toggleStep(${{i}})">
        <div class="fs-label" style="color:${{lm.color}}">${{step.label}}</div>
        <div class="fs-desc" style="color:${{lm.color}}">${{step.desc}}</div>
      </div>
      <div class="fstep-mods" id="fstep-mods-${{i}}">
        <div class="fmtitle">Modules involved</div>
        <div class="fmod-pills">${{step.modules.map(mid=>{{
          const mod=MODS.find(x=>x.id===mid);
          const c=LMETA[LMETA[mid]?mid:(mod?mod.layer:'infra')]?.color||lm.color;
          return `<span class="fpill" style="border-color:${{lm.color}}44;color:${{lm.color}}" onclick="selectMod('${{mid}}')">${{mid}}.py</span>`;
        }}).join('')}}</div>
      </div>
      ${{i<FLOW.length-1?`<div class="farrow" style="background:${{lm.color}}"></div>`:''}}
    `;
    wrap.appendChild(stepDiv);
  }});
}}

function toggleStep(i) {{
  const mods=document.getElementById('fstep-mods-'+i);
  const step=document.getElementById('fstep-'+i);
  const isOpen=mods.classList.contains('open');
  document.querySelectorAll('.fstep-mods').forEach(el=>el.classList.remove('open'));
  document.querySelectorAll('.fstep').forEach(el=>el.classList.remove('active'));
  if(!isOpen){{mods.classList.add('open');step.classList.add('active');}}
}}

/* ── MODULES TAB ── */
function buildModulesTab() {{
  const wrap=document.getElementById('modules-wrap');
  const layers=['entry','brain','memory','io','infra','security','code','vision'];
  layers.forEach(layer=>{{
    const mods=MODS.filter(m=>m.layer===layer);
    if(!mods.length) return;
    const lm=LMETA[layer]||{{color:'#888',label:layer,desc:''}};
    const sec=document.createElement('div');
    sec.className='layer-section';
    sec.innerHTML=`
      <div class="layer-head">
        <div class="layer-dot" style="background:${{lm.color}}"></div>
        <div>
          <div class="lh-title" style="color:${{lm.color}}">${{lm.label}}</div>
          <div class="lh-desc">${{lm.desc}}</div>
        </div>
        <div class="lh-ct">${{mods.length}}</div>
      </div>
      <div class="layer-mods">${{mods.map(m=>`
        <div class="mc" id="mc-${{m.id}}" onclick="selectMod('${{m.id}}')">
          <div class="mc-name" style="color:${{lm.color}}">${{m.name}}</div>
          <div class="mc-lines">${{m.lines}} lines</div>
          <div class="mc-pur">${{m.purpose.split('.')[0]}}.</div>
        </div>
      `).join('')}}</div>
    `;
    wrap.appendChild(sec);
  }});
}}

/* ── INTENTS TAB ── */
function buildIntents() {{
  const grid=document.getElementById('intent-grid');
  INTENTS.forEach(intent=>{{
    const card=document.createElement('div');
    card.className='intent-card';
    card.innerHTML=`<div class="ic-label">${{intent.label}}</div><div class="ic-desc">${{intent.desc}}</div>`;
    card.onclick=()=>showIntentDetail(intent);
    grid.appendChild(card);
  }});
}}

function showIntentDetail(intent) {{
  const d=document.getElementById('intent-detail');
  d.style.display='block';
  d.innerHTML=`
    <div style="font-size:15px;font-weight:500;margin-bottom:6px">${{intent.label}}</div>
    <div style="font-size:13px;color:#9b9a94;line-height:1.65;margin-bottom:12px">${{intent.desc}}</div>
    <div style="font-size:11px;color:#5a5a58">Detected by intent.py → dispatched by intent_dispatch.py</div>
  `;
  d.scrollIntoView({{behavior:'smooth',block:'nearest'}});
}}

/* ── TABS ── */
function showTab(id,btn) {{
  document.querySelectorAll('.view').forEach(v=>v.classList.remove('on'));
  document.querySelectorAll('.tab').forEach(t=>t.classList.remove('on'));
  document.getElementById('view-'+id).classList.add('on');
  btn.classList.add('on');
  if(id!=='flow') document.getElementById('detail').style.display='none';
}}

buildSidebar();
buildFlow();
buildModulesTab();
buildIntents();
</script>
</body>
</html>"""

if __name__ == "__main__":
    target = sys.argv[1] if len(sys.argv) > 1 else "."
    print(f"Scanning {Path(target).resolve()} ...")
    mods = scan(target)
    print(f"Found {len(mods)} modules, {sum(m['lines'] for m in mods):,} lines")
    ts = datetime.now().strftime("%Y-%m-%d %H:%M")
    html = build_html(mods, ts, str(Path(target).resolve()))
    out = Path(target) / "edith_flow.html"
    out.write_text(html, encoding="utf-8")
    print(f"Wrote → {out}")
    webbrowser.open(f"file://{out.resolve()}")
    print("Done.")
