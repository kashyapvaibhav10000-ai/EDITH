# EDITH Function Flowcharts

## Overview
EDITH is a multi-modal AI assistant with voice input/output, web search, memory management, and Telegram integration.

---

## 1. SEARCH MODULE (search.py)

### web_search(query, num_results=3)
```
START
  ↓
SET params = {query, format: json, engines: google,bing,duckduckgo}
  ↓
REQUEST searxng_api with params (timeout: 10s)
  ↓
  ├─ SUCCESS?
  │   ├─ YES → Parse JSON response
  │   │   ↓
  │   │   EXTRACT results[:num_results]
  │   │   ↓
  │   │   FOR each result:
  │   │   ├─ Extract: title, url, snippet
  │   │   ├─ Add to results[] list
  │   │   ↓
  │   │   RETURN results[]
  │   │
  │   └─ NO (Exception)
  │       ↓
  │       LOG error
  │       ↓
  │       RETURN [{"error": str(e)}]
END
```

**Flow Logic:**
- Makes HTTP GET request to SearXNG API
- Passes query and preference for multiple search engines
- Extracts and filters first N results
- Returns structured list or error

---

### format_results(results)
```
START
  ↓
IS results EMPTY?
  ├─ YES → RETURN "No results found."
  │
  └─ NO
      ↓
      INITIALIZE output = ""
      ↓
      FOR each result (enumerate starting at 1):
      │
      ├─ "error" in result?
      │   ├─ YES → RETURN f"Search error: {error_msg}"
      │   │
      │   └─ NO
      │       ↓
      │       Append formatted line:
      │       "{number}. {title}"
      │       "   {snippet}"
      │       "   {url}"
      │       ↓
      │
      RETURN output.strip()
END
```

**Flow Logic:**
- Validates that results exist
- Checks for errors first
- Formats each result with title, snippet, URL
- Numbers results sequentially

---

## 2. VOICE MODULE (voice.py)

### speak(text)
```
START
  ↓
CREATE temp .wav file
  ↓
RUN piper TTS:
├─ Input: text (stdin)
├─ Model: PIPER_MODEL
├─ Output: temp .wav file
  ↓
PLAY audio: aplay -q <file>
  ↓
DELETE temp .wav file
  ↓
END
```

**Flow Logic:**
- Creates temporary WAV file as output
- Pipes text to Piper TTS model
- Plays audio using aplay system command
- Cleans up temporary file

---

### _get_whisper()
```
START
  ↓
IS _whisper_model already loaded?
  ├─ YES → RETURN _whisper_model
  │
  └─ NO
      ↓
      LOG "Loading Whisper.cpp model (first voice use)..."
      ↓
      CHECK if WHISPER_MODEL_PATH exists
      │
      ├─ NOT EXISTS → LOG error → RAISE FileNotFoundError
      │
      └─ EXISTS
          ↓
          IMPORT Model from pywhispercpp.model
          ↓
          LOAD Model:
          ├─ Path: WHISPER_MODEL_PATH
          ├─ Threads: 4
          ├─ No realtime/progress output
          ↓
          SET _whisper_model = Model instance
          ↓
          LOG "Whisper.cpp model loaded."
          ↓
          RETURN _whisper_model
END
```

**Flow Logic:**
- Lazy-loads Whisper model only on first use
- Checks for model file existence
- Configures with 4 threads and suppresses logging
- Caches global reference for reuse

---

### listen()
```
START
  ↓
INITIALIZE:
├─ VAD (Voice Activity Detection) - sensitivity level 2
├─ Sample rate: 16000 Hz
├─ Frame duration: 30ms
├─ Frame size: 480 bytes
  ↓
INITIALIZE PyAudio stream:
├─ Mono channel
├─ 16-bit PCM
├─ 16000 Hz sample rate
├─ Input device
├─ Suppress stderr for PyAudio logs
  ↓
PRINT "🎤 Listening..."
  ↓
INITIALIZE tracking:
├─ frames = []
├─ silent_frames = 0
├─ speaking = False
├─ max_silent_frames = 133 (2 seconds at 30ms frames)
  ↓
LOOP (infinite):
┌─────────────────────────┐
│ READ frame from stream  │
├─────────────────────────┤
│ ANALYZE: is_speech?     │
│                         │
│ ├─ YES (speech detected)│
│ │   ├─ speaking = True  │
│ │   ├─ silent_frames=0  │
│ │   └─ ADD to frames[]  │
│ │                       │
│ └─ NO (silent)          │
│     └─ IF speaking:     │
│        ├─ silent_frames++
│        ├─ ADD to frames[]
│        └─ IF silent >133
│           └─ BREAK LOOP
└─────────────────────────┘
  ↓
STOP stream, close PauseAudio
  ↓
SAVE frames as WAV file (temp)
  ↓
LOAD Whisper model via _get_whisper()
  ↓
TRANSCRIBE WAV:
├─ Get segments from model
├─ Join text: " ".join(segments.text)
├─ Replace "edith" → "EDITH" (case-insensitive)
  ↓
DELETE temp WAV file
  ↓
PRINT "📝 You said: {transcript}"
  ↓
RETURN transcript
END
```

**Flow Logic:**
- Continuously records until 2 seconds of silence
- Uses VAD to distinguish speech from noise
- Transcribes recorded audio with Whisper
- Formats output and substitutes "edith" with "EDITH"

---

## 3. CLEANUP MODULE (cleanup.py)

### cleanup()
```
START
  ↓
CONNECT to ChromaDB:
├─ Path: /home/vaibhav/EDITH/memory_db
├─ Collection: "edith_memory"
  ↓
FETCH all items:
├─ ids[]
├─ documents[]
  ↓
DEFINE noise_keywords:
["hello", "hi", "bye", "okay", "ok", "thanks", "thank you"]
  ↓
INITIALIZE to_delete = []
  ↓
FOR EACH (id, doc) in (ids, documents):
│
├─ DOES doc contain ANY noise_keyword?
│   AND doc.length < 100 chars?
│   │
│   ├─ YES → ADD id to to_delete[]
│   │
│   └─ NO → Continue to next
│
NEXT
  ↓
IS to_delete[] non-empty?
│
├─ YES
│   ├─ DELETE collection items by ids
│   ├─ PRINT f"Cleaned {len(to_delete)} noise memories."
│   │
└─ NO
    └─ PRINT "Nothing to clean."
  ↓
END
```

**Flow Logic:**
- Connects to persistent ChromaDB database
- Identifies "noise" memories (short, trivial messages)
- Marks short messages with noise keywords for deletion
- Cleans up database periodically

---

## 4. TELEGRAM BOT MODULE (telegram_bot.py)

### send_telegram(message, parse_mode="Markdown")
```
START
  ↓
VALIDATE credentials:
├─ TOKEN exists?
├─ CHAT_ID exists?
│
└─ NOT EXISTS?
    ├─ LOG error
    └─ RETURN False
  ↓
SET url = "https://api.telegram.org/bot{TOKEN}/sendMessage"
  ↓
SPLIT message into 4000-char chunks
(Telegram limit: 4096 chars)
  ↓
FOR each chunk:
│
├─ CREATE payload:
│  ├─ chat_id: CHAT_ID
│  ├─ text: chunk
│  ├─ parse_mode: parse_mode
│  │
│  ├─ POST to Telegram API (timeout: 10s)
│  │   │
│  │   ├─ status_code == 200?
│  │   │   ├─ YES → Continue
│  │   │   │
│  │   │   └─ NO → RETRY without parse_mode
│  │   │
│  │   └─ Exception?
│  │       ├─ LOG error
│  │       └─ RETURN False
│
NEXT chunk
  ↓
RETURN True (all chunks sent)
END
```

**Flow Logic:**
- Verifies Telegram credentials
- Breaks long messages into chunks (API limit)
- Retries failed markdown formatting
- Handles network errors gracefully

---

### process_message(text)
```
START
  ↓
DETECT intent from text using detect_intent()
  ↓
ROUTE based on intent:
│
├─ "council"
│   ├─ CALL run_council(text)
│   └─ RETURN result
│
├─ "decision"
│   ├─ CALL simulate_decision(text)
│   └─ RETURN result
│
├─ "briefing"
│   ├─ CALL weekly_briefing()
│   └─ RETURN result
│
├─ "profile"
│   ├─ "drift" mentioned?
│   │   ├─ YES → detect_drift()
│   │   │
│   │   └─ NO
│   │       ├─ "prime directive" mentioned?
│   │       │   ├─ YES → RETURN prime directive
│   │       │   │
│   │       │   └─ NO → query_profile(text, n=5)
│   │
│   └─ RETURN formatted profiles
│
├─ "self_improve"
│   ├─ CALL run_self_improvement()
│   └─ RETURN result or error
│
├─ "loop" / "remember" / "note"
│   ├─ add_open_loop(text)
│   └─ RETURN confirmation
│
├─ "close" / "done" / "resolved"
│   ├─ close_open_loop(text)
│   └─ RETURN completion message
│
├─ "search"
│   ├─ CALL web_search(text)
│   ├─ format_results()
│   └─ RETURN formatted search results
│
└─ DEFAULT (no intent match)
    ├─ GET prime_directive()
    ├─ GET profile context (n=3)
    ├─ BUILD prompt:
    │  "You are EDITH..."
    │  {prime_directive}
    │  {user_profile}
    │  {user_message}
    │
    ├─ CALL safe_ollama_call(chat_model, prompt)
    └─ RETURN response
  ↓
END
```

**Flow Logic:**
- Intent-based routing system
- Specialized handlers for each intent
- Falls back to general chat with context
- Combines user profile and prime directive

---

### poll_telegram()
```
START
  ↓
VALIDATE credentials
  ├─ TOKEN & CHAT_ID present?
  │   └─ NO → Print warning, RETURN
  │
  ├─ START session
  ├─ SEND "🤖 EDITH online" message
  │
  └─ INITIALIZE last_update_id = None
  ↓
LOOP (infinite):
┌────────────────────────────┐
│ TRY:                        │
├────────────────────────────┤
│ GET updates from Telegram: │
│ ├─ url: getUpdates API    │
│ ├─ timeout: 10s           │
│ ├─ offset: last_update_id │
│ └─ Parse JSON             │
│                            │
│ FOR each update:           │
│ ├─ SET last_update_id++   │
│ ├─ EXTRACT message text   │
│ ├─ EXTRACT chat_id        │
│ │                          │
│ ├─ VALIDATE:              │
│ │ └─ chat_id == CHAT_ID?  │
│ │    └─ text not empty?   │
│ │                          │
│ ├─ YES → track_query()    │
│ │   │                      │
│ │   ├─ Is "/start"?       │
│ │   │   ├─ YES → Send ok  │
│ │   │   │   CONTINUE      │
│ │   │   │                  │
│ │   │   └─ NO             │
│ │   │       ├─ process_message(text)
│ │   │       ├─ send_telegram(response)
│ │   │       │              │
│ │   │       └─ Exception?  │
│ │   │           ├─ LOG     │
│ │   │           └─ Send err
│ │                          │
│ └─ NO → Continue           │
│                            │
│ SLEEP 2 seconds           │
│                            │
├────────────────────────────┤
│ EXCEPT KeyboardInterrupt:  │
│ ├─ Send goodbye message   │
│ ├─ BREAK LOOP             │
│                            │
├────────────────────────────┤
│ EXCEPT generic Exception:  │
│ ├─ LOG error              │
│ └─ SLEEP 10s (backoff)    │
└────────────────────────────┘
  ↓
END
```

**Flow Logic:**
- Long-polling Telegram for updates
- Tracks query for session metrics
- Routes each message through process_message()
- Handles disconnections with exponential backoff

---

### send_weekly_briefing()
```
START
  ↓
LOG "Generating weekly briefing..."
  ↓
CALL weekly_briefing()
  ↓
SEND via send_telegram():
├─ message: briefing
├─ parse_mode: None (plain text)
  ↓
SUCCESS?
│
├─ YES
│   ├─ update_profile("Weekly briefing sent", "telegram")
│   ├─ LOG success
│   └─ RETURN True
│
└─ NO
    └─ RETURN False
  ↓
END
```

**Flow Logic:**
- Generates weekly briefing summary
- Sends to Telegram without markdown formatting
- Updates user profile with event tracking

---

### send_drift_alert()
```
START
  ↓
GET recent_queries (last 10)
  ↓
IS recent.length < 5?
├─ YES → RETURN (not enough data)
│
└─ NO
    │
    ├─ CALL detect_drift()
    │ (analyzes if user behavior aligns with profile)
    │
    ├─ CONVERT response to lowercase
    │
    ├─ CHECK for drift indicators:
    │ ["drift", "not aligned", "misalign", "off track", "warning"]
    │
    ├─ ANY indicators found?
    │   │
    │   ├─ YES
    │   │   ├─ BUILD alert message
    │   │   ├─ send_telegram(alert)
    │   │   ├─ LOG warning
    │   │   │
    │   │   └─ NO
    │   │       └─ (silent - no alert)
    │
    ↓
END
```

**Flow Logic:**
- Validates sufficient query history
- Runs drift detection analysis
- Only alerts if drift indicators found
- Prevents alert spam

---

### start_briefing_scheduler()
```
START
  ↓
IMPORT schedule module
  ↓
SCHEDULE tasks:
├─ Weekly briefing: Sunday 08:00 → send_weekly_briefing()
├─ Drift alerts: Every 6 hours → send_drift_alert()
  ↓
LOG "Scheduler active: [tasks]"
  ↓
CREATE background thread:
│
├─ LOOP (infinite):
│  ├─ Run pending tasks (if time reached)
│  ├─ SLEEP 60 seconds
│  └─ Repeat
│
└─ Thread properties: daemon=True
  ↓
START thread
  ↓
RETURN thread reference
END
```

**Flow Logic:**
- Uses APScheduler to schedule recurring tasks
- Runs in background daemon thread
- Weekly briefings on Sunday mornings
- Drift checks every 6 hours
- Non-blocking (returns to main loop)

---

## System Architecture Overview

```
┌─────────────────────────────────────────────────┐
│        EDITH MAIN ENTRY POINT                   │
│  (telegram_bot.py / voice interface)            │
└────────────────┬────────────────────────────────┘
                 │
    ┌────────────┼─────────────┬──────────────┐
    ↓            ↓             ↓              ↓
┌────────┐ ┌──────────┐ ┌──────────┐ ┌────────────┐
│ Voice  │ │ Telegram │ │ Scheduler│ │ Background│
│ I/O    │ │ Polling  │ │ (Briefing)│ │ Tasks    │
└────────┘ └──────────┘ └──────────┘ └────────────┘
    │            │             │              │
    └────────────┼─────────────┴──────────────┘
                 │
         ┌───────▼────────────┐
         │ process_message()  │
         │ Intent Routing     │
         └────┬───────────────┘
             │
    ┌────────┼────────┬─────────┬──────────┐
    ↓        ↓        ↓         ↓          ↓
 ┌────────┐┌─────────┐┌──────┐┌──────────┐┌──────┐
 │Search  ││Council  ││Decision││Self-    ││Memory││
 │        ││         ││        ││Improve  ││      ││
 │web_    ││run_     ││simulate││run_     ││query ││
 │search()││council()││_decision()│_self_   ││_     ││
 │        ││         ││        ││improve()││profile││
 └────────┘└─────────┘└──────┘└──────────┘└──────┘
                 │
         ┌───────▼────────────┐
         │    ChromaDB        │
         │  Vector Memory DB  │
         │  Persistent store  │
         └────────────────────┘
```

---

## Key Integration Points

1. **Voice Module** (`speak()` + `listen()`)
   - Real-time input/output
   - Integrates with PyAudio, Whisper, Piper TTS

2. **Search Module** (`web_search()`)
   - Queries SearXNG Meta-search engine
   - Formats results for display

3. **Memory Module** (`cleanup()`)
   - ChromaDB vector database
   - Persistent vector embeddings of past interactions

4. **Telegram Integration**
   - `poll_telegram()`: Live message polling
   - `process_message()`: Intent router
   - `send_telegram()`: Message sender
   - Scheduler: Recurring tasks (briefings, drift checks)

5. **Config & Logging**
   - Centralized configuration
   - Structured logging across modules
