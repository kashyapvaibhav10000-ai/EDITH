import re
import threading

CODING_PATTERNS = [
    r"(write|create|fix|debug|code|program|script|function|class|implement)",
    r"(python|javascript|bash|html|css|sql|java|rust|go|typescript)",
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
    r"(run|execute|terminal|command|shell|bash)\s+.{3,}",
    r"\b(install|uninstall|apt|pip|npm|pacman|yay)\s+\w+",
    r"(start|stop|restart|kill)\s+(service|process|server|daemon)",
    r"\b(htop|neofetch|systemctl|journalctl|dmesg)\b",
    r"\brun\s+the\s+(bash|shell|python|script)\b",
]

OPEN_APP_PATTERNS = [
    r"^(open|launch|start)\s+(chrome|chromium|firefox|brave|opera|browser|terminal|konsole|spotify|vlc|code|vscode|files|dolphin|nautilus|calculator|kcalc|steam|discord|slack|telegram|notion|obsidian|gimp|inkscape|blender|thunderbird|libreoffice|okular|mpv|celluloid|audacity|kdenlive|handbrake|virtualbox|postman|insomnia|dbeaver)\b",
    r"^(open|launch|start)\s+\w+\s*$",
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
    r"(check|read|show).*(email|mail|inbox)",
    r"what.*(email|mail)",
]

UNREAD_EMAIL_PATTERNS = [
    r"(unread|unseen).*(email|mail|message)",
    r"(any).*(new|unread).*(email|mail)",
]

CALENDAR_TODAY_PATTERNS = [
    r"(what's|what is|show|tell).*(today|schedule|plan|day)",
    r"(today's|my).*(schedule|plan|events|calendar)",
    r"what do i have today",
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
    r"(what is on|what do you see|what.s on my screen|screenshot|which application.s? running)",
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
    r"(add|create|schedule|set|make|book).*(event|meeting|appointment|reminder|task)",
    r"(remind me|add to calendar|put on calendar)",
]

CALENDAR_WEEK_PATTERNS = [
    r"(this week|week's|weekly).*(schedule|plan|events|calendar)",
    r"(what's|what is).*(week|this week)",
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
    r"(simulate|decision|life sim|branches|paths)",
    r"(should i|which.*(path|option|choice))",
    r"(what happens if|what would happen)",
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
    r"(self.improve|upgrade yourself|arxiv|research|papers)",
    r"(improve yourself|what.*learn|latest research)",
]

SESSION_PATTERNS = [
    r"(end session|session summary|wrap up|sign off|goodbye boss)",
]

SYSTEM_HEALTH_PATTERNS = [
    r"(system health|health check|status check|all systems|system status)",
    r"(are you (ok|okay|running|working|online)|everything (ok|working|fine))",
    r"(check (systems?|network|ollama|phone|calendar|disk|ram|memory|status))",
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
    r"(my drive|google drive|gdrive)\s+(files?|docs?|list|search)",
    r"(mcp|model context protocol)\s+(status|tools?|call|server)",
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
        prompt = f"Categorize the following input into EXACTLY ONE word from this exact list: [search, weather, email, agent, council, memory, chat, code, reminder, system]. Return ONLY the single word. Do not add punctuation. Input: '{user_input}'"
        result = smart_call(prompt, intent="reason").strip().lower()
        import string
        valid = ["search", "weather", "email", "agent", "council", "memory", "chat", "code", "reminder", "system"]
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

    # Morning briefing — check before wake (more specific)
    if any(re.search(p, text_lower) for p in MORNING_BRIEFING_PATTERNS):
        # Only trigger if it's a briefing request, not a bare wake word
        if not re.match(r"^(good morning|morning)\s*edith\s*$", text_lower):
            return "morning_briefing"

    # Wake word (highest priority)
    if any(re.search(p, text_lower) for p in WAKE_PATTERNS):
        return "wake"

    # Weather
    if any(re.search(p, text_lower) for p in WEATHER_PATTERNS):
        return "weather"

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
    if any(re.search(p, text_lower) for p in VISION_PATTERNS):
        return "vision"
    if any(re.search(p, text_lower) for p in RAG_PATTERNS):
        return "rag"

    # File query — natural file browsing (before agent/shell to prevent misrouting)
    if any(re.search(p, text_lower) for p in FILE_QUERY_PATTERNS):
        return "file_query"

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

    # Open app — no word count gate (2-word commands like "open chrome" valid)
    if any(re.search(p, text_lower) for p in OPEN_APP_PATTERNS):
        return "open_app"

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

    if any(re.search(p, text_lower) for p in UNREAD_EMAIL_PATTERNS):
        return "unread_email"
    if any(re.search(p, text_lower) for p in EMAIL_PATTERNS):
        return "email"

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

