# EDITH Visual Flowcharts

## 1. web_search(query, num_results=3)

```mermaid
flowchart TD
    A[START: web_search] --> B["Set params:<br/>query, format=json<br/>engines: google,bing,duckduckgo"]
    B --> C["HTTP GET to SearXNG"]
    C --> D{Request<br/>Success?}
    D -->|No| E["Log Error"]
    E --> F["Return error dict"]
    D -->|Yes| G["Parse JSON response"]
    G --> H["Extract results[:num_results]"]
    H --> I["Loop through results"]
    I --> J["Extract: title, url, snippet"]
    J --> K["Append to results list"]
    K --> L{More<br/>results?}
    L -->|Yes| I
    L -->|No| M["Return results"]
    F --> N[END]
    M --> N
```

---

## 2. format_results(results)

```mermaid
flowchart TD
    A[START: format_results] --> B{"Results<br/>empty?"}
    B -->|Yes| C["Return: No results found"]
    B -->|No| D["Initialize output = ''"]
    D --> E["Loop enumerate results"]
    E --> F{"Error in<br/>result?"}
    F -->|Yes| G["Return: Search error msg"]
    F -->|No| H["Format:<br/>number. title<br/>snippet<br/>url"]
    H --> I["Append to output"]
    I --> J{"More<br/>results?"}
    J -->|Yes| E
    J -->|No| K["Return output.strip"]
    G --> L[END]
    C --> L
    K --> L
```

---

## 3. speak(text)

```mermaid
flowchart TD
    A[START: speak] --> B["Create temp .wav file"]
    B --> C["Run Piper TTS<br/>Input: text stdin<br/>Output: temp .wav"]
    C --> D["Play audio<br/>aplay -q file"]
    D --> E["Delete temp file"]
    E --> F[END]
```

---

## 4. _get_whisper()

```mermaid
flowchart TD
    A[START: _get_whisper] --> B{"_whisper_model<br/>already loaded?"}
    B -->|Yes| C["Return cached model"]
    B -->|No| D["Log: Loading model..."]
    D --> E{"Model file<br/>exists?"}
    E -->|No| F["Log error"]
    F --> G["Raise FileNotFoundError"]
    E -->|Yes| H["Import Model class<br/>from pywhispercpp"]
    H --> I["Load Model:<br/>threads=4<br/>no_realtime_output"]
    I --> J["Set global _whisper_model"]
    J --> K["Log: Model loaded"]
    K --> L["Return _whisper_model"]
    C --> M[END]
    G --> M
    L --> M
```

---

## 5. listen()

```mermaid
flowchart TD
    A[START: listen] --> B["Initialize VAD<br/>Sample rate: 16kHz<br/>Frame: 30ms"]
    B --> C["Open PyAudio stream<br/>Mono, 16-bit PCM"]
    C --> D["Print: 🎤 Listening..."]
    D --> E["Initialize tracking:<br/>frames=[], silent=0<br/>speaking=False"]
    E --> F["READ frame from stream"]
    F --> G{"VAD detects<br/>speech?"}
    G -->|Yes| H["speaking = True<br/>silent_frames = 0<br/>ADD to frames"]
    G -->|No| I{"Was<br/>speaking?"}
    I -->|Yes| J["silent_frames++<br/>ADD to frames"]
    J --> K{"Silent > 133<br/>frames?<br/>2 seconds?"}
    I -->|No| K
    K -->|Yes| L["Break loop"]
    K -->|No| F
    H --> F
    L --> M["Stop stream & close"]
    M --> N["Save frames as WAV"]
    N --> O["Load Whisper model"]
    O --> P["Transcribe WAV"]
    P --> Q["Replace 'edith' → 'EDITH'"]
    Q --> R["Delete temp WAV"]
    R --> S["Print: 📝 You said..."]
    S --> T["Return transcript"]
    T --> U[END]
```

---

## 6. cleanup()

```mermaid
flowchart TD
    A[START: cleanup] --> B["Connect ChromaDB<br/>Path: memory_db<br/>Collection: edith_memory"]
    B --> C["Fetch all items<br/>ids, documents"]
    C --> D["Define:<br/>noise_keywords"]
    D --> E["Initialize to_delete = []"]
    E --> F["Loop each id, doc"]
    F --> G{"Contains noise<br/>keyword AND<br/>len < 100?"}
    G -->|Yes| H["ADD id to to_delete"]
    G -->|No| I["Skip"]
    H --> J{"More<br/>items?"}
    I --> J
    J -->|Yes| F
    J -->|No| K{"to_delete<br/>non-empty?"}
    K -->|Yes| L["Delete from collection"]
    L --> M["Print: Cleaned N memories"]
    K -->|No| N["Print: Nothing to clean"]
    M --> O[END]
    N --> O
```

---

## 7. send_telegram(message, parse_mode)

```mermaid
flowchart TD
    A[START: send_telegram] --> B{"TOKEN and<br/>CHAT_ID set?"}
    B -->|No| C["Log error"]
    C --> D["Return False"]
    B -->|Yes| E["Set Telegram API URL"]
    E --> F["Split message into<br/>4000-char chunks"]
    F --> G["Loop each chunk"]
    G --> H["Create payload:<br/>chat_id, text, parse_mode"]
    H --> I["POST to Telegram"]
    I --> J{"Status<br/>200?"}
    J -->|No| K["Retry without parse_mode"]
    J -->|Yes| L["Continue"]
    K --> L
    L --> M{"More<br/>chunks?"}
    M -->|Yes| G
    M -->|No| N["Return True"]
    D --> O[END]
    N --> O
```

---

## 8. process_message(text)

```mermaid
flowchart TD
    A[START: process_message] --> B["Call detect_intent"]
    B --> C["Result: intent type"]
    C --> D{Intent<br/>type?}
    D -->|council| E["run_council"]
    D -->|decision| F["simulate_decision"]
    D -->|briefing| G["weekly_briefing"]
    D -->|profile| H{"Contains<br/>drift?"}
    H -->|Yes| I["detect_drift"]
    H -->|No| J{"Contains<br/>prime?"}
    J -->|Yes| K["Return prime_directive"]
    J -->|No| L["query_profile"]
    D -->|self_improve| M["run_self_improvement"]
    D -->|loop/remember| N["add_open_loop"]
    D -->|close/done| O["close_open_loop"]
    D -->|search| P["web_search"]
    P --> Q["format_results"]
    D -->|DEFAULT| R["Get prime_directive"]
    R --> S["Get profile context"]
    S --> T["Build prompt"]
    T --> U["Call safe_ollama_call"]
    E --> V["Return response"]
    F --> V
    G --> V
    I --> V
    K --> V
    L --> V
    M --> V
    N --> V
    O --> V
    Q --> V
    U --> V
    V --> W[END]
```

---

## 9. poll_telegram()

```mermaid
flowchart TD
    A[START: poll_telegram] --> B{"TOKEN and<br/>CHAT_ID?"}
    B -->|No| C["Print warning"]
    C --> D[RETURN]
    B -->|Yes| E["Start session"]
    E --> F["Send: EDITH online"]
    F --> G["Set last_update_id = None"]
    G --> H["TRY:"]
    H --> I["GET updates from Telegram<br/>timeout=10s"]
    I --> J{"Got<br/>updates?"}
    J -->|Yes| K["For each update"]
    J -->|No| K
    K --> L["Extract: update_id, text, chat_id"]
    L --> M{"Valid<br/>message?"}
    M -->|No| N["Skip"]
    M -->|Yes| O["track_query"]
    O --> P{"Is /start<br/>command?"}
    P -->|Yes| Q["Send: EDITH ready"]
    P -->|No| R["process_message"]
    R --> S["send_telegram response"]
    S --> T{"Exception?"}
    T -->|Yes| U["Log error<br/>Send error msg"]
    T -->|No| V["OK"]
    Q --> W{"More<br/>updates?"}
    N --> W
    V --> W
    U --> W
    W -->|Yes| K
    W -->|No| X["Sleep 2s"]
    X --> Y["Check for next batch"]
    Y --> Z{KeyboardInterrupt?}
    Z -->|Yes| AA["Send: Going offline"]
    Z -->|No| AB{"Exception?"}
    AB -->|Yes| AC["Log error<br/>Sleep 10s"]
    AB -->|No| H
    AC --> H
    AA --> AD[BREAK LOOP]
    AD --> AE[END]
    D --> AE
```

---

## 10. send_weekly_briefing()

```mermaid
flowchart TD
    A[START: send_weekly_briefing] --> B["Log: Generating briefing..."]
    B --> C["Call: weekly_briefing"]
    C --> D["Call: send_telegram<br/>parse_mode=None"]
    D --> E{"Send<br/>success?"}
    E -->|Yes| F["update_profile"]
    F --> G["Log: Sent successfully"]
    G --> H["Return True"]
    E -->|No| I["Return False"]
    H --> J[END]
    I --> J
```

---

## 11. send_drift_alert()

```mermaid
flowchart TD
    A[START: send_drift_alert] --> B["Get recent_queries 10"]
    B --> C{"Length<br/>< 5?"}
    C -->|Yes| D["Return early"]
    C -->|No| E["Call: detect_drift"]
    E --> F["Convert to lowercase"]
    F --> G{"Contains drift<br/>indicators?<br/>drift, not aligned,<br/>misalign, off track"}
    G -->|Yes| H["Build alert message"]
    H --> I["send_telegram<br/>parse_mode=Markdown"]
    I --> J["Log warning"]
    J --> K[END]
    G -->|No| L["No alert"]
    L --> K
    D --> K
```

---

## 12. start_briefing_scheduler()

```mermaid
flowchart TD
    A[START: start_briefing_scheduler] --> B["Import schedule module"]
    B --> C["Schedule:<br/>Sunday 08:00<br/>→ send_weekly_briefing"]
    C --> D["Schedule:<br/>Every 6 hours<br/>→ send_drift_alert"]
    D --> E["Log: Scheduler active"]
    E --> F["Create daemon thread"]
    F --> G["Thread function:"]
    G --> H["LOOP: schedule.run_pending"]
    H --> I["Sleep 60s"]
    I --> J["Repeat"]
    J --> K["Thread starts"]
    K --> L["Return thread reference"]
    L --> M[END]
```

---

## System Data Flow

```mermaid
graph LR
    TG["📱 Telegram<br/>Messages"]
    MIC["🎤 Microphone<br/>Audio"]

    TG -->|poll_telegram| ROUTE["🔀 Intent<br/>Router"]
    MIC -->|listen| ROUTE

    ROUTE -->|council| COUNCIL["Council"]
    ROUTE -->|decision| DECISION["Decision"]
    ROUTE -->|briefing| BRIEF["Briefing"]
    ROUTE -->|profile| PROFILE["Profile"]
    ROUTE -->|search| SEARCH["Search"]
    ROUTE -->|loop| MEMORY["Memory"]
    ROUTE -->|chat| LLM["LLM Chat"]

    SEARCH -->|web_search| SEARXNG["SearXNG<br/>API"]
    SEARXNG -->|results| FORMAT["format_results"]

    MEMORY -->|add/query| CHROMADB["🗄️ ChromaDB<br/>Vector DB"]
    PROFILE -->|query| CHROMADB

    COUNCIL --> LLM
    DECISION --> LLM
    BRIEF --> CHROMADB
    FORMAT --> RESPONSE["📤 Response"]
    LLM --> RESPONSE
    PROFILE --> RESPONSE

    RESPONSE -->|send_telegram| TG
    RESPONSE -->|speak| SPEAKER["🔊 Speaker"]
    CHROMADB -->|cleanup| NOISE["Remove noise"]
```

---

## Scheduler Flow

```mermaid
flowchart TD
    A["start_briefing_scheduler<br/>Creates daemon thread"]
    B["Scheduler Loop<br/>every 60s check"]
    C{"Is it Sunday<br/>08:00?"}
    D{"Is it<br/>6h interval?"}
    E["send_weekly_briefing"]
    F["send_drift_alert"]
    A --> B
    B --> C
    B --> D
    C -->|Yes| E
    D -->|Yes| F
    E --> B
    F --> B
    C -->|No| B
    D -->|No| B
```
