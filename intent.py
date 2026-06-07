import re
import threading

CODING_PATTERNS = [
    r"(write|create|fix|debug|code|program|script|function|class|implement)",
    r"\b(python|javascript|bash|html|css|sql|java|rust|typescript)\b",
    r"(error|bug|exception|traceback|syntax error)",
]

REASON_PATTERNS = [
    r"(why|explain|analyze|compare|evaluate|think|reason|should i|what if)",
    r"(pros and cons|advantages|disadvantages|difference between)",
]

LOOKUP_PATTERNS = [
    r"(what is|who is|when is|where is|define|meaning of|tell me about)",
    r"(how many|how much|how long|how far|how old)",
]

SEARCH_PATTERNS = [
    r"(search|look up|find|google|browse|current|latest|news|today's|price of)",
    r"(what happened|recent|update on|status of)",
    r"(who won|who lost|score|result|match|ipl|cricket|football|election)",
    r"(search.*(web|internet|online)|search for)",
]

SHELL_PATTERNS = [
    r"\brun\s+(echo|ls|cat|grep|find|chmod|chown|ps|kill|df|du|top|htop|curl|wget|git|python|python3|node|npm|pip|apt|pacman|yay|systemctl|journalctl|dmesg|neofetch|uname|whoami|pwd|mkdir|rm|cp|mv|touch|nano|vim|ssh|scp|rsync|docker|kubectl)\b",
    r"\b(execute|exec)\s+.{0,60}\.(?:sh|py|js|rb|bash)\b",
    r"\b(?:sudo|bash|sh|zsh|fish)\s+\S+",
    r"\b(install|uninstall|apt|pip|npm|pacman|yay)\s+\w+",
    r"(start|stop|restart|kill)\s+(service|process|server|daemon)",
    r"\b(htop|neofetch|systemctl|journalctl|dmesg)\b",
    r"\brun\s+the\s+(bash|shell|python|script)\b",
    r"\brun\s+command\b",
    r"\bterminal\s+command\b",
]

OPEN_APP_PATTERNS = [
    r"(open|launch|start)\s+(chrome|chromium|firefox|brave|opera|browser|terminal|konsole|spotify|vlc|code|vscode|files|dolphin|nautilus|calculator|kcalc|steam|discord|slack|telegram|notion|obsidian|gimp|inkscape|blender|thunderbird|libreoffice|okular|mpv|celluloid|audacity|kdenlive|handbrake|virtualbox|postman|insomnia|dbeaver|file.?manager|file.?browser|file.?explorer|thunar|nemo|pcmanfm)\b",
    r"^(open|launch|start)\s+\w+\s*$",
    r"\b(open|launch|start)\s+(up\s+)?(my\s+)?(file\s*(manager|browser|explorer)|the\s+files?|folder\s*browser)\b",
]

FILE_QUERY_PATTERNS = [
    r"(list|show|what).*(files?|folder|directory|content).*(in|of|inside|from)\s",
    r"(what's in|what is in|open|browse)\s+(my\s+)?(downloads?|documents?|desktop|home|folder)",
    r"(how many|count).*(files?|folder|items?)\s+(in|of)",
]

FILE_PATTERNS = [
    r"(create|make|write|save).*(file|document|note|txt|py|json|csv)",
    r"(delete|remove).*(file|folder|directory)",
]

EMAIL_PATTERNS = [
    r"(check|read|show|look at|pull up).*(email|mail|inbox|mailbox)",
    r"what.*(email|mail|inbox)",
    r"\b(inbox|mailbox)\b",
    r"(any|got|have).*(email|mail|message).*(today|waiting|for me|yet)?",
    r"(cooking|waiting|sitting|in).*(inbox|mail|mailbox)",
    r"\bmy\s+(email|mail|inbox|gmail)\b",
    r"(emails?|mails?)\s+(waiting|for me|today|yet|new)",
]

UNREAD_EMAIL_PATTERNS = [
    r"(unread|unseen).*(email|mail|message)",
    r"(any).*(new|unread).*(email|mail)",
]

CALENDAR_TODAY_PATTERNS = [
    r"(what's|what is|show|tell).*(today|schedule|plan|day)",
    r"(today's|my).*(schedule|plan|events|calendar)",
    r"what do i have today",
    r"what.?s on my calendar",
    r"(check|show|view|see)\s+my\s+calendar",
    r"my\s+(schedule|agenda|appointments?)\s+(today|tomorrow|this week)",
    r"(any|what)\s+(meetings?|events?|appointments?)\s+(today|tomorrow|on my calendar)",
    r"calendar\s+(today|for today)",
    r"how does my day look",
    r"how.?s my day",
    r"what.?s on (my|the) agenda",
    r"\bmy day\b.*(look|ahead|like|plan)",
    r"what meetings (do i have|are (there|scheduled))",
]

CALL_PATTERNS = [
    r"\b(call|dial|phone call)\b",
    r"(call|dial)\s+(\+?\d[\d\s\-]{6,14})",
    r"(call|dial)\s+(my|the|his|her)\s+(phone|number|mobile)",
    r"(make|place|initiate)\s+(a\s+)?(call|phone call)",
    r"i\s+want\s+(you\s+)?to\s+call",
]

SMS_PATTERNS = [
    r"(send|text).*(sms|message)",
    r"\b(sms|text message)\b",
    r"(send|write).*text.*to",
    r"message\s+(\+?\d[\d\s\-]{6,14})",
]

PHONE_PATTERNS = [
    r"(ring|find|where is).*(phone|mobile)",
    r"(phone|mobile).*(status|connected|battery|notification)",
    r"\b(battery|notification)s?\b.*(phone|mobile)",
]

VISION_PATTERNS = [
    r"(what|which|describe|look at|analyze|read|see|show).*(screen|window|image|photo|picture)",
    r"(what is on|what do you see|what.s on my screen|screenshot|which application.s? running)(?!.*calendar)",
    r"(ocr|read text|extract text).*(image|photo|screen)",
]

RAG_PATTERNS = [
    r"(what do my notes say|check my notes|in my notes|from my notes)",
    r"(according to|based on).*(my notes|my documents|my files)",
    r"(search|find|look up).*(my notes|my documents|my knowledge)",
    r"(what did i write|recall from|remember about)",
]

AGENT_PATTERNS = [
    r"(agent|multi.step|plan and|execute|automate).*(task|this|it)",
    r"(do|complete|finish|handle).*(for me|this task|multiple|steps)",
    r"(fix|organize|set up|build|create).*(project|folder|files|system)",
    r"\byou\s+run\b",
    r"\bexecute\s+this\b",
    r"\brun\s+the\s+code\b",
]

DATA_PATTERNS = [
    r"(analyze|analyse|read|load|open).*(csv|excel|xlsx|xls|file|data|spreadsheet)",
    r"(chart|graph|plot|visualize).*(data|file|csv|excel)",
    r"(what does|insights|summary|trend).*(data|file|csv|excel)",
]

CALENDAR_CREATE_PATTERNS = [
    r"(add|create|schedule|set|make|book).*(event|meeting|appointment|task)",
    r"(remind me|add to calendar|put on calendar)",
]

CALENDAR_WEEK_PATTERNS = [
    r"(this week|week's|weekly).*(schedule|plan|events|calendar|meetings?)",
    r"(what's|what is).*(this week|week ahead|upcoming week)",
    r"(calendar|schedule|agenda).*(this week|next week|for the week)",
    r"\bthis week\b.*(do i have|look like|ahead)",
]

# ──────────────────────────────────────────────
# Vision System Patterns (NEW)
# ──────────────────────────────────────────────
COUNCIL_PATTERNS = [
    r"(council|debate|roundtable|personas|minds)",
    r"(strategist|critic|builder|wildcard).*(think|say|opinion)",
    r"(complex|difficult|hard).*(decision|choice|question)",
]

DECISION_PATTERNS = [
    r"(simulate|life sim|branches|decision.*paths?)",
    r"(which.*(path|option|choice))\b",
    r"(what happens if|what would happen)",
    r"\bshould i\b.*(quit|leave|move|change.*career|give up|start|choose between)",
]

BRIEFING_PATTERNS = [
    r"(weekly|briefing|status report|week.*review)",
    r"(open loops|priorities|drift|alignment)",
    r"(how am i doing|my progress|am i on track)",
]

# UPGRADE #2: Morning Briefing Patterns
MORNING_BRIEFING_PATTERNS = [
    r"(good morning|morning briefing|morning report)",
    r"(morning update|daily briefing|daily digest)",
    r"\bwhat do i have today\b",
]

PROFILE_PATTERNS = [
    r"(my profile|cognitive profile|what do you know about me)",
    r"(prime directive|north star|my goal)",
    r"(drift|am i drifting|focus check)",
]

UPGRADE_PATTERNS = [
    r"(self.improve|upgrade yourself|arxiv|research.*papers?)",
    r"(improve yourself|latest research|read.*papers?)",
    r"\bwhat.*new.*learn\b|\blearn.*new.*thing\b",
]

SESSION_PATTERNS = [
    r"(end session|session summary|wrap up|sign off|goodbye boss)",
]

REPO_ANALYZE_PATTERNS = [
    r"(analyze repo|check repo|analyze github|repo dna|study repo)",
    r"(github\.com/[\w\-]+/[\w\-]+)",
]

SYSTEM_HEALTH_PATTERNS = [
    r"(system health|health check|status check|all systems|system status)",
    r"(are you (ok|okay|running|working|online)|everything (ok|working|fine))",
    r"(check (systems?|network|phone|calendar|disk|ram|memory|status))",
    r"(what.s (wrong|broken|offline|down)|diagnos(e|tics?))",
]

WAKE_PATTERNS = [
    r"^(wake up|hello|hey|hi|good morning|good evening|good afternoon)\s*edith\s*$",
    r"^edith\s*(wake up|you there|are you awake|come online|start)\s*$",
    r"^(wake up|edith|hey edith)$",
]

WEATHER_PATTERNS = [
    r"\b(weather|temperature|rain|forecast|humid|wind|hot|cold|outside)\b",
    r"\b(mausam|garmi|thandi|barish)\b",  # Hindi/Gujarati basics
]

OCR_PATTERNS = [
    r"(ocr|extract text|read.*(image|picture|screenshot|photo))",
    r"(scan.*text|text from image|recognize text)",
    r"(what.*say.*image|text.*screenshot)",
]

WHATSAPP_PATTERNS = [
    r"\b(whatsapp|wapp)\b",
    r"\bwa\b",
    r"(send.*whatsapp|whatsapp.*message|whatsapp.*unread)",
]

MCP_PATTERNS = [
    r"\bmcp\b",
    r"(read|open|show)\s+(file|files?)\s+(/[^\s]+|\S+\.\w+)",
    r"(write|save|create)\s+file\s+(/[^\s]+|\S+\.\w+)",
    r"(list|ls)\s+(files?|directory|dir|folder)\s*(/[^\s]*)?",
    r"(search web|brave search|web search via mcp)",
    r"\bgithub\b.*(repo|issue|pr|pull request|code|search)",
    r"\bnotion\b|\bobsidian\b",
    r"\b(search|find|list|read|create)\s+(notes?|vault)\b",
    r"(my drive|google drive|gdrive)\s+(files?|docs?|list|search)",
    r"(mcp|model context protocol)\s+(status|tools?|call|server)",
    r"\bspotify\b",
    r"\b(play|pause|skip|next track|previous track)\s+(music|song|track|album|playlist)\b",
    r"\bwhat.?s\s+playing\b",
    r"\b(google\s+)?(docs?|sheets?|slides?|forms?|workspace)\b",
    r"\b(spreadsheet|presentation)\b",
    r"\b(list|read|create)\s+(doc|document|sheet|spreadsheet|slide|presentation|form)\b",
]

COMPACT_PATTERNS = [
    r"\b(compact|compress|clear context|reset context|free memory)\b",
    r"\b/compact\b",
]

THINK_LEVEL_PATTERNS = [
    r"\b/(think|reason)\s+(high|deep|hard|max|low|fast|quick)\b",
    r"\bthink\s+(high|deep|hard|max|level)\b",
    r"\bthink\s+(low|fast|quick|shallow)\b",
]

TRACE_PATTERNS = [
    r"\b/(trace|tracing)\s+(on|off)\b",
    r"\btrace\s+(on|off)\b",
]

AGENT_STOP_PATTERNS = [
    r"\b(stop|cancel|abort|interrupt)\s+(agent|task|that|it)\b",
    r"\bstop\s+what\s+you.re\s+doing\b",
]

LIST_SKILLS_PATTERNS = [
    r"\b(list|show|what).*(skills?|capabilities)\b",
    r"\bskills?\b",
]

VAULT_PATTERNS = [
    r"\b(show|get|list|view|open|check|display)\s+(my\s+)?(vault|secrets?|passwords?|credentials?|api.?keys?)\b",
    r"\bvault\s+(secrets?|contents?|passwords?|keys?)\b",
    r"\bwhat.?s?\s+in\s+(my\s+)?vault\b",
    r"\b(unlock|access)\s+(my\s+)?vault\b",
]

DEVLOG_PATTERNS = [
    r"\b(add|write|log|save|record|append|note)\s+(to\s+|in\s+|into\s+)?(dev.?log|development.?log|journal|changelog)\b",
    r"\bdevlog\s*[:\-]",
    r"\b(log|record)\s+(this|that|it)\s*[:\-]",
    r"\badd\s+to\s+devlog\b",
]

MEMORY_STORE_PATTERNS = [
    r"\b(remember|note|save|store|keep track of|don.?t forget)\s+(that\s+)?i\s+(like|love|hate|prefer|use|want|need|am|have|do)\b",
    r"\b(remember|note|save|store)\s+(that\s+)?.{5,}",
    r"\bdon.?t\s+forget\s+(that\s+)?.{3,}",
    r"\bkeep\s+in\s+mind\s+(that\s+)?.{3,}",
]

MEMORY_RECALL_PATTERNS = [
    r"\bwhat\s+do\s+you\s+(know|remember|recall)\s+about\s+me\b",
    r"\b(show|tell\s+me|list)\s+what\s+you\s+(know|remember)\s+about\s+me\b",
    r"\bwhat\s+have\s+you\s+(saved|stored|remembered)\s+about\s+me\b",
    r"\bmy\s+(preferences?|profile|history|memory)\b",
]

def is_coding_request(text):
    text = text.lower()
    return any(re.search(p, text) for p in CODING_PATTERNS)


# Dangerous intents that need higher confidence to avoid misrouting
CONFIRM_INTENTS = {"shell", "create_file", "delete_file", "agent"}
# Minimum word count before allowing these intents
MIN_WORDS_FOR_ACTION = 3


def _count_matches(text, patterns):
    """Count how many patterns match the text (confidence scoring)."""
    return sum(1 for p in patterns if re.search(p, text))


def classify_intent_via_llm(user_input: str) -> str:
    # EDITH FIX v1.0 — LLM Semantic Fallback
    try:
        from smart_router import smart_call
        prompt = f"Categorize the following input into EXACTLY ONE word from this exact list: [search, weather, email, agent, council, memory, chat, code, system]. Return ONLY the single word. Do not add punctuation. Input: '{user_input}'"
        result = smart_call(prompt, intent="reason").strip().lower()
        import string
        valid = ["search", "weather", "email", "agent", "council", "memory", "chat", "code", "system", "identity", "greeting"]
        for p in string.punctuation:
            result = result.replace(p, "")
        if result in valid:
            return result
        for v in valid:
            if v in result:
                return v
    except Exception:
        pass
    return None


def detect_intent(text):
    text_lower = text.lower()
    word_count = len(text_lower.split())

    # High-priority command intents (before domain patterns)
    if any(re.search(p, text_lower) for p in COMPACT_PATTERNS):
        return "compact"
    if any(re.search(p, text_lower) for p in THINK_LEVEL_PATTERNS):
        return "think_level"
    if any(re.search(p, text_lower) for p in TRACE_PATTERNS):
        return "trace_toggle"
    if any(re.search(p, text_lower) for p in AGENT_STOP_PATTERNS):
        return "agent_stop"
    if any(re.search(p, text_lower) for p in LIST_SKILLS_PATTERNS):
        return "list_skills"

    # System health — high priority before general search
    if any(re.search(p, text_lower) for p in SYSTEM_HEALTH_PATTERNS):
        return "system_health"

    if any(re.search(p, text_lower) for p in REPO_ANALYZE_PATTERNS):
        return "repo_analyze"

    # Morning briefing — check before wake (more specific)
    if any(re.search(p, text_lower) for p in MORNING_BRIEFING_PATTERNS):
        # Only trigger if it's a briefing request, not a bare wake word
        if not re.match(r"^(good morning|morning)\s*edith\s*$", text_lower):
            return "morning_briefing"

    # Wake word (highest priority)
    if any(re.search(p, text_lower) for p in WAKE_PATTERNS):
        return "wake"

    # Identity questions — must fire before CODING_PATTERNS matches "create"
    _IDENTITY_PATTERNS = [
        r"\bwho\s+(made|created|built|designed|programmed|wrote|developed)\s+you\b",
        r"\bwho\s+are\s+you\b",
        r"\bwhat\s+are\s+you\b",
        r"\btell\s+me\s+about\s+yourself\b",
        r"\bintroduce\s+yourself\b",
        r"\byour\s+(name|creator|maker|origin|purpose)\b",
        r"\bwho\s+is\s+your\s+(creator|maker|developer|owner)\b",
    ]
    if any(re.search(p, text_lower) for p in _IDENTITY_PATTERNS):
        return "identity"

    # Vault — before chat (contains "secrets"/"passwords" which fall to chat)
    if any(re.search(p, text_lower) for p in VAULT_PATTERNS):
        return "vault"

    # Devlog — before code ("add to devlog" matches CODING_PATTERNS "create")
    if any(re.search(p, text_lower) for p in DEVLOG_PATTERNS):
        return "devlog"

    # Memory store — before chat ("remember that I like X" falls to chat)
    if any(re.search(p, text_lower) for p in MEMORY_STORE_PATTERNS):
        return "memory"

    # Memory recall — before rag (more specific)
    if any(re.search(p, text_lower) for p in MEMORY_RECALL_PATTERNS):
        return "memory"

    # Weather
    if any(re.search(p, text_lower) for p in WEATHER_PATTERNS):
        return "weather"

    # Email — check early before lookup/search swallows "what is in my inbox"
    if any(re.search(p, text_lower) for p in UNREAD_EMAIL_PATTERNS):
        return "unread_email"
    if any(re.search(p, text_lower) for p in EMAIL_PATTERNS):
        return "email"

    # Phase 5: OCR and WhatsApp
    if any(re.search(p, text_lower) for p in OCR_PATTERNS):
        return "ocr"
    if any(re.search(p, text_lower) for p in WHATSAPP_PATTERNS):
        return "whatsapp"

    # Vision system intents (check first — higher priority)
    if any(re.search(p, text_lower) for p in SESSION_PATTERNS):
        return "session_end"
    if any(re.search(p, text_lower) for p in COUNCIL_PATTERNS):
        return "council"
    if any(re.search(p, text_lower) for p in DECISION_PATTERNS):
        return "decision"
    if any(re.search(p, text_lower) for p in BRIEFING_PATTERNS):
        return "briefing"
    if any(re.search(p, text_lower) for p in PROFILE_PATTERNS):
        return "profile"
    if any(re.search(p, text_lower) for p in UPGRADE_PATTERNS):
        return "self_improve"

    # Early-exit: filesystem ops → mcp, execution ops → agent (before code check)
    # (CODING_PATTERNS matches "create"/"script"/"bash" too broadly)
    if re.search(r"\bmkdir\b", text_lower):
        return "mcp"
    _EARLY_MCP = [
        r"\bcreate\s+\S+\s+(folder|directory|dir)s?\b",   # "create 16 folders"
        r"\bcreate\s+(folder|directory|dir)s?\b",           # "create folder"
        r"\bmake\s+\S*\s*(folder|directory|dir)s?\b",       # "make a directory"
    ]
    if any(re.search(p, text_lower) for p in _EARLY_MCP) and word_count >= MIN_WORDS_FOR_ACTION:
        return "mcp"
    _EARLY_AGENT = [
        r"\byou\s+run\b",
        r"\bexecute\s+this\b",
        r"\brun\s+the\s+code\b",
    ]
    if any(re.search(p, text_lower) for p in _EARLY_AGENT) and word_count >= MIN_WORDS_FOR_ACTION:
        return "agent"
    _EARLY_SHELL = [
        r"\brun\s+the\s+(bash|shell|python|script)\b",
    ]
    if any(re.search(p, text_lower) for p in _EARLY_SHELL) and word_count >= MIN_WORDS_FOR_ACTION:
        return "shell"

    # Calendar create — before code scoring ("create an event" matches CODING_PATTERNS "create")
    _EARLY_CALENDAR_CREATE = [
        r"\b(add|create|schedule|set|make|book)\b.{0,40}\b(event|meeting|appointment)\b",
        r"\b(remind me|add to calendar|put on calendar)\b",
    ]
    if any(re.search(p, text_lower) for p in _EARLY_CALENDAR_CREATE):
        return "calendar_create"

    # Original intents — multi-pattern for code (needs good confidence)
    code_score = _count_matches(text_lower, CODING_PATTERNS)
    agent_score = _count_matches(text_lower, AGENT_PATTERNS)
    if code_score >= 2:
        return "code"
    # Low-confidence code (1 pattern) only wins if no agent signals present
    if code_score == 1 and word_count >= 4 and agent_score == 0:
        return "code"
    # Call intent — check BEFORE sms/phone to prevent misrouting
    if any(re.search(p, text_lower) for p in CALL_PATTERNS):
        return "call"
    if any(re.search(p, text_lower) for p in SMS_PATTERNS):
        return "sms"
    if any(re.search(p, text_lower) for p in PHONE_PATTERNS):
        return "phone"
    # Calendar — week BEFORE today (more specific → less likely to false-positive)
    if any(re.search(p, text_lower) for p in CALENDAR_WEEK_PATTERNS):
        return "calendar_week"
    if any(re.search(p, text_lower) for p in CALENDAR_TODAY_PATTERNS):
        return "calendar_today"
    if any(re.search(p, text_lower) for p in VISION_PATTERNS):
        return "vision"
    if any(re.search(p, text_lower) for p in RAG_PATTERNS):
        return "rag"

    # File query — natural file browsing (before agent/shell to prevent misrouting)
    if any(re.search(p, text_lower) for p in FILE_QUERY_PATTERNS):
        return "file_query"

    # Open app — check BEFORE data_analysis to prevent "open file browser" → data_analysis
    if any(re.search(p, text_lower) for p in OPEN_APP_PATTERNS):
        return "open_app"

    # Agent — needs higher confidence (multi-step, avoid false positives)
    if agent_score >= 1 and word_count >= MIN_WORDS_FOR_ACTION:
        return "agent"

    if any(re.search(p, text_lower) for p in DATA_PATTERNS):
        return "data_analysis"
    if any(re.search(p, text_lower) for p in CALENDAR_CREATE_PATTERNS):
        return "calendar_create"

    # Guard: if it mentions sports/news/current events, prefer search over calendar
    _has_realtime_topic = re.search(r"(ipl|cricket|match|score|won|lost|election|football|movie|stock|crypto|bitcoin)", text_lower)
    if not _has_realtime_topic:
        if any(re.search(p, text_lower) for p in CALENDAR_TODAY_PATTERNS):
            return "calendar_today"
        if any(re.search(p, text_lower) for p in CALENDAR_WEEK_PATTERNS):
            return "calendar_week"

    # Search (moved BEFORE calendar for real-time queries)
    if any(re.search(p, text_lower) for p in SEARCH_PATTERNS):
        return "search"
    if any(re.search(p, text_lower) for p in REASON_PATTERNS):
        return "reason"
    if any(re.search(p, text_lower) for p in LOOKUP_PATTERNS):
        return "lookup"
    # Calendar fallback (for real-time topic queries that didn't match search)
    if _has_realtime_topic:
        if any(re.search(p, text_lower) for p in CALENDAR_TODAY_PATTERNS):
            return "calendar_today"
        if any(re.search(p, text_lower) for p in CALENDAR_WEEK_PATTERNS):
            return "calendar_week"
    if any(re.search(p, text_lower) for p in SEARCH_PATTERNS):
        return "search"

    # Shell — require higher confidence for dangerous intents
    shell_score = _count_matches(text_lower, SHELL_PATTERNS)
    if shell_score >= 1 and word_count >= MIN_WORDS_FOR_ACTION:
        return "shell"

    # MCP — after shell, before generic file ops
    if any(re.search(p, text_lower) for p in MCP_PATTERNS):
        return "mcp"

    # File operations — explicit phrasing required
    if any(re.search(p, text_lower) for p in FILE_PATTERNS):
        if re.search(r"delete|remove", text_lower):
            return "delete_file"
        return "create_file"

    # Weak single-keyword match for code (fallback)
    if code_score == 1:
        return "code"

    # Phase 3.1: ML fallback when regex returns 'chat' (ambiguous)
    ml_result = _ml_classify(text)
    if ml_result and ml_result != "chat":
        return ml_result

    # EDITH FIX v1.0 — Final Semantic Fallback
    llm_result = classify_intent_via_llm(text)
    if llm_result and llm_result != "chat":
        return llm_result

    return "chat"


# ──────────────────────────────────────────────
# Phase 3.1: ML Intent Engine (sklearn)
# ──────────────────────────────────────────────
_ml_model = None
_ml_vectorizer = None
_ml_lock = threading.Lock()  # Protects _ml_model lazy-init from TOCTOU race
_ML_CONFIDENCE_THRESHOLD = 0.4

# Training data — each (text, intent) pair
_ML_TRAINING_DATA = [
    ("search for latest news", "search"),
    ("find articles about AI", "search"),
    ("what's happening in tech", "search"),
    ("look up machine learning trends", "search"),
    ("check my email inbox", "email"),
    ("read my emails", "email"),
    ("show unread messages", "email"),
    ("write a Python script", "code"),
    ("fix this bug in my code", "code"),
    ("create a function to sort", "code"),
    ("debug this error", "code"),
    ("run this command in terminal", "shell"),
    ("execute apt update", "shell"),
    ("install numpy package", "shell"),
    ("plan my day", "agent"),
    ("organize my project files", "agent"),
    ("create a todo list", "agent"),
    ("what is the weather today", "weather"),
    ("is it going to rain", "weather"),
    ("temperature outside", "weather"),
    ("explain how async works in Python", "reason"),
    ("compare Java and Python", "reason"),
    ("should I use React or Vue", "reason"),
    ("what is machine learning", "lookup"),
    ("who invented the telephone", "lookup"),
    ("define neural network", "lookup"),
    ("what's on my calendar", "calendar_today"),
    ("schedule a meeting", "calendar_create"),
    ("analyze this CSV file", "data_analysis"),
    ("plot the data", "data_analysis"),
    ("how are you doing", "chat"),
    ("tell me a joke", "chat"),
    ("good morning", "chat"),
    ("thanks for the help", "chat"),
    ("council debate this topic", "council"),
    ("roundtable discussion on strategy", "council"),
    ("simulate decision paths", "decision"),
    ("what happens if I quit my job", "decision"),
    ("weekly briefing please", "briefing"),
    ("show my cognitive profile", "profile"),
    ("update yourself", "self_improve"),
    ("take a photo and analyze", "vision"),
    ("what is on my screen", "vision"),
    ("read text from image", "vision"),
    ("send text to my phone", "sms"),
    ("ring my phone", "phone"),
    ("call my phone", "call"),
    ("call 9305819663", "call"),
    ("dial this number", "call"),
    ("make a phone call", "call"),
    ("i want you to call", "call"),
    ("send sms to 9876543210 saying hello", "sms"),
    ("text message to mom", "sms"),
    ("end session", "session_end"),
    ("wrap up session", "session_end"),
    ("mcp read file", "mcp"),
    ("list files via mcp", "mcp"),
    ("mcp search web", "mcp"),
    ("mcp server status", "mcp"),
    ("github repo search", "mcp"),
    ("read file from drive", "mcp"),
    # ── Extended training data (250+ additional samples) ──
    # email
    ("any new emails today", "email"),
    ("what is cooking in my inbox", "email"),
    ("got any messages", "email"),
    ("pull up my gmail", "email"),
    ("any mail waiting for me", "email"),
    ("inbox check", "email"),
    ("show me what is in my mailbox", "email"),
    ("anything sitting in my inbox", "email"),
    # unread_email
    ("how many unread do i have", "unread_email"),
    ("unseen messages count", "unread_email"),
    ("how many emails have not been read", "unread_email"),
    # calendar_today
    ("what is on my plate today", "calendar_today"),
    ("what meetings do i have", "calendar_today"),
    ("give me my agenda", "calendar_today"),
    ("any appointments today", "calendar_today"),
    ("what time is my next meeting", "calendar_today"),
    ("how does my day look", "calendar_today"),
    # calendar_create
    ("book me a slot tomorrow at 3pm", "calendar_create"),
    ("set up a meeting for friday", "calendar_create"),
    ("add dentist appointment next monday", "calendar_create"),
    ("put this on my calendar", "calendar_create"),
    # open_app
    ("open up my file browser", "open_app"),
    ("launch the file manager", "open_app"),
    ("open my files", "open_app"),
    ("start file explorer", "open_app"),
    ("bring up dolphin", "open_app"),
    ("fire up chrome", "open_app"),
    ("get firefox going", "open_app"),
    ("spin up vscode", "open_app"),
    ("open terminal please", "open_app"),
    # weather
    ("is it going to be hot today", "weather"),
    ("should i carry an umbrella", "weather"),
    ("what is the temperature outside", "weather"),
    ("how is the weather looking", "weather"),
    ("any rain expected", "weather"),
    ("what is it like outside", "weather"),
    # search
    ("look up the latest ipl score", "search"),
    ("find information about quantum computing", "search"),
    ("google this for me", "search"),
    ("search for best python frameworks 2026", "search"),
    ("what happened in the news today", "search"),
    ("current price of bitcoin", "search"),
    ("what is trending right now", "search"),
    # code
    ("write a function to reverse a list", "code"),
    ("i have a bug in my fastapi route", "code"),
    ("help me refactor this class", "code"),
    ("write unit tests for this module", "code"),
    ("explain this python traceback", "code"),
    ("create a bash script to backup files", "code"),
    ("fix the syntax error in my javascript", "code"),
    ("how do i implement async in python", "code"),
    ("write a regex to match email addresses", "code"),
    # shell
    ("run apt update for me", "shell"),
    ("check disk usage with df", "shell"),
    ("kill this process", "shell"),
    ("list all running services", "shell"),
    ("execute this bash script", "shell"),
    ("run git status", "shell"),
    ("chmod 755 on this file", "shell"),
    # agent
    ("handle all of this for me step by step", "agent"),
    ("automate this workflow", "agent"),
    ("complete this multi-step task", "agent"),
    ("do everything needed to set up this project", "agent"),
    ("take care of this end to end", "agent"),
    # vision
    ("what am i looking at on the screen", "vision"),
    ("can you describe my current screen", "vision"),
    ("look at my monitor and tell me what you see", "vision"),
    ("screenshot and analyze", "vision"),
    ("what application is open right now", "vision"),
    ("read what is written in this image", "vision"),
    # council
    ("run a roundtable discussion on this", "council"),
    ("get all your personas to weigh in", "council"),
    ("what do your different sides think", "council"),
    ("debate this with yourself", "council"),
    # decision
    ("help me think through this life decision", "decision"),
    ("what are my options and their outcomes", "decision"),
    ("simulate what happens if i quit my job", "decision"),
    ("walk me through the different paths", "decision"),
    # briefing
    ("give me my weekly update", "briefing"),
    ("how am i doing against my goals", "briefing"),
    ("status report please", "briefing"),
    ("what are my open items", "briefing"),
    ("am i on track", "briefing"),
    # profile
    ("what do you know about me", "profile"),
    ("show my cognitive profile", "profile"),
    ("am i drifting from my goals", "profile"),
    ("check my prime directive", "profile"),
    ("update my north star", "profile"),
    # self_improve
    ("check arxiv for new research", "self_improve"),
    ("propose an upgrade for yourself", "self_improve"),
    ("what can you do better", "self_improve"),
    ("improve your capabilities", "self_improve"),
    # memory (store)
    ("save this for later", "memory"),
    ("remember i prefer dark mode", "memory"),
    ("note that i do not like verbose responses", "memory"),
    ("keep in mind i use supabase for ayurstock", "memory"),
    ("store this preference", "memory"),
    ("never forget that i work best at night", "memory"),
    # memory (recall)
    ("what have you saved about me", "memory"),
    ("show my preferences", "memory"),
    ("what do you remember", "memory"),
    ("recall my history", "memory"),
    # rag
    ("look in my notes about this", "rag"),
    ("what do my notes say about ayurstock", "rag"),
    ("search my documents for this", "rag"),
    ("check my knowledge base", "rag"),
    ("find this in my personal notes", "rag"),
    # data_analysis
    ("analyze this spreadsheet", "data_analysis"),
    ("load this csv and show me trends", "data_analysis"),
    ("create a chart from this data", "data_analysis"),
    ("plot this excel file", "data_analysis"),
    ("what insights can you find in this data", "data_analysis"),
    # phone
    ("where is my phone", "phone"),
    ("ring my device", "phone"),
    ("how much battery does my phone have", "phone"),
    ("check my phone notifications", "phone"),
    # sms
    ("text my mom hello", "sms"),
    ("send an sms to this number", "sms"),
    ("shoot a quick text to vaibhav", "sms"),
    # call
    ("dial this number for me", "call"),
    ("place a call to the office", "call"),
    ("call 9305819663 now", "call"),
    ("make a phone call please", "call"),
    # chat
    ("what do you think about this idea", "chat"),
    ("just chat with me for a bit", "chat"),
    ("tell me something interesting", "chat"),
    ("how are things going", "chat"),
    ("i am bored entertain me", "chat"),
    ("give me a quick pep talk", "chat"),
    # lookup
    ("what is the capital of germany", "lookup"),
    ("define machine learning", "lookup"),
    ("who is linus torvalds", "lookup"),
    ("what does idempotent mean", "lookup"),
    # reason
    ("pros and cons of using rust vs python", "reason"),
    ("walk me through why this approach is better", "reason"),
    ("analyze the tradeoffs here", "reason"),
    ("help me think through this", "reason"),
    ("explain why this happens", "reason"),
    # system_health
    ("are all systems go", "system_health"),
    ("anything broken right now", "system_health"),
    ("run a full diagnostic", "system_health"),
    ("check everything is working", "system_health"),
    # repo_analyze
    ("analyze this github repo", "repo_analyze"),
    ("study this codebase for me", "repo_analyze"),
    # whatsapp
    ("send a whatsapp to my brother", "whatsapp"),
    ("message on whatsapp", "whatsapp"),
    # mcp
    ("read this file using mcp", "mcp"),
    ("use mcp to list the directory", "mcp"),
    ("search brave for this query", "mcp"),
    # devlog
    ("add to my dev journal", "devlog"),
    ("log this progress", "devlog"),
    ("record this in the devlog", "devlog"),
    # vault
    ("what api keys do i have stored", "vault"),
    ("show my credentials", "vault"),
    ("open the vault", "vault"),
    # session_end
    ("i am done for today", "session_end"),
    ("let us wrap up", "session_end"),
    ("signing off", "session_end"),
    # morning_briefing
    ("good morning edith what do i have today", "morning_briefing"),
    ("morning briefing please", "morning_briefing"),
    ("give me my daily digest", "morning_briefing"),
    # image_gen
    ("generate an image of a sunset", "image_gen"),
    ("create a picture of a robot", "image_gen"),
    ("draw something for me", "image_gen"),
    # wake
    ("hey edith wake up", "wake"),
    ("edith are you there", "wake"),
    ("hello edith", "wake"),
]


def _ensure_ml_model():
    """Lazy-load the ML intent model (trains on first use). Thread-safe."""
    global _ml_model, _ml_vectorizer

    if _ml_model is not None:
        return

    with _ml_lock:
        # Double-check after acquiring lock
        if _ml_model is not None:
            return

        try:
            from sklearn.feature_extraction.text import TfidfVectorizer
            from sklearn.linear_model import LogisticRegression

            texts = [t for t, _ in _ML_TRAINING_DATA]
            labels = [l for _, l in _ML_TRAINING_DATA]

            _ml_vectorizer = TfidfVectorizer(max_features=500, ngram_range=(1, 2))
            X = _ml_vectorizer.fit_transform(texts)

            _ml_model = LogisticRegression(max_iter=200, C=1.0)
            _ml_model.fit(X, labels)

        except Exception:
            _ml_model = None
            _ml_vectorizer = None


def _ml_classify(text: str) -> str:
    """Classify intent using ML model. Returns intent or None."""
    _ensure_ml_model()
    if not _ml_model or not _ml_vectorizer:
        return None

    try:
        X = _ml_vectorizer.transform([text.lower()])
        proba = _ml_model.predict_proba(X)[0]
        max_idx = proba.argmax()
        confidence = proba[max_idx]

        if confidence >= _ML_CONFIDENCE_THRESHOLD:
            return _ml_model.classes_[max_idx]
    except Exception:
        pass

    return None


def ml_intent_status() -> dict:
    """Get ML model status for Dashboard."""
    _ensure_ml_model()
    return {
        "loaded": _ml_model is not None,
        "training_samples": len(_ML_TRAINING_DATA),
        "confidence_threshold": _ML_CONFIDENCE_THRESHOLD,
    }

