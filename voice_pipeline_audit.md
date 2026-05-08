# EDITH Voice Pipeline Audit — 2026-04-27
# Issue: Mic picks up background noise + Whisper hallucinations

---

## STATUS SUMMARY

10 missing checks found. 3 root causes identified.
No fixes made — audit only per request.

Files audited:
- edith_dashboard.html (browser voice pipeline)
- chat_server.py (/api/voice/transcribe endpoint)
- voice.py (_transcribe_groq, listen)
- config.py (no VAD/silence constants present)

---

## ISSUE 1 — Mic picks up background noise

### Q1: getUserMedia audio constraints
- `edith_dashboard.html:1317`: `getUserMedia({ audio: true })`
- `edith_dashboard.html:1581`: `getUserMedia({ audio: true })` (chat mic path)
- echoCancellation: **NOT SET** (browser default, unguaranteed)
- noiseSuppression: **NOT SET** (browser default, unguaranteed)
- autoGainControl: **NOT SET** (browser default is usually TRUE = amplifies background noise)

### Q2: SILENCE_THRESHOLD
- `edith_dashboard.html:1270`: `const SILENCE_THRESHOLD = 15;`
- Scale: 0–255 amplitude. 15 = 5.9% of max.
- **TOO LOW for noisy environment.** Fan/AC/ambient easily stays above 15 always.
- Consequence: silence never detected → MAX_RECORDING (15s) fires → full noise blob sent to Groq.

### Q3: SILENCE_DURATION
- `edith_dashboard.html:1271`: `const SILENCE_DURATION = 1500;`
- `edith_dashboard.html:1288`: stops recording after 1500ms continuous avgLevel < 15.
- Yes — recording stops after this much silence (when threshold actually triggers).

### Q4: fftSize / frequencyBinCount
- `edith_dashboard.html:1319`: `analyser.fftSize = 512;`
- frequencyBinCount = 512 / 2 = **256 bins**
- `edith_dashboard.html:1282–1284`: averages ALL 256 bins (0–24kHz).
- High-freq noise bins dilute speech signal. Poor speech/noise discrimination.

### Q5: Minimum recording duration before silence detection
- `edith_dashboard.html:1336`: `mediaRecorder.start();`
- `edith_dashboard.html:1338`: `startSilenceDetection(mediaRecorder);` — called immediately.
- No `hasSpeechDetected` flag. No time gate in `startSilenceDetection` (lines 1268–1303).
- **MISSING.** Silence detection runs from t=0ms. 100ms noise burst → 1500ms silence → stop → Groq.

### Q6: Minimum audio energy check before Groq
- `edith_dashboard.html:1346` `processVoiceBlob()`: blob sent directly, no energy check.
- `chat_server.py:278`: `len(audio_bytes) < 100` — size only, not energy.
- **MISSING.**

### Q7: Transcript meaningful check in chat_server.py
- `chat_server.py:278`: only `len(audio_bytes) < 100`
- `chat_server.py:308–310`: transcript extracted raw from Groq JSON
- `chat_server.py:320–321`: `if not transcript or not transcript.strip():` — empty string only
- No minimum word count. No minimum character length. No confidence threshold.
- **MISSING** all meaningful checks.

---

## ISSUE 2 — Hallucinated words in wrong language

### Q8: language parameter in voice.py _transcribe_groq()
- `voice.py:97`: `data={"model": GROQ_STT_MODEL},  # language omitted → Groq auto-detects`
- Language parameter **NOT SET**. Intentionally omitted per code comment.
- Auto-detect on noise → arbitrary language assigned → hallucination in that language.

### Q9: language parameter in chat_server.py /api/voice/transcribe
- `chat_server.py:305`: `data={"model": "whisper-large-v3-turbo"},`
- **No language parameter.**
- MIME type sent: `audio/webm` (dashboard line 1360; server reads header at line 281).

### Q10: Audio energy check BEFORE Groq
- `chat_server.py:277–306`: body → size check → temp file → Groq. No energy/RMS check.
- **MISSING.**

### Q11: Minimum audio blob size check
- `chat_server.py:278–279`: `if not audio_bytes or len(audio_bytes) < 100:`
- Threshold: **100 bytes**
- 1-second silent webm = ~2000–5000 bytes. 200ms noise burst = ~1000+ bytes.
- **TOO LOW.** Filters only corrupt/empty blobs. All noise blobs pass.

### Q12: Post-Groq transcript filters
- `chat_server.py:308–322`: no minimum word count, no minimum char length, no hallucination phrase list.
- **MISSING** all filters.

---

## ISSUE 3 — Recording starts too eagerly

### Q13: When does MediaRecorder start?
- `edith_dashboard.html:1336`: `mediaRecorder.start();`
- Starts **immediately** after `getUserMedia` resolves. Captures mic-open click sound.

### Q14: VAD before starting MediaRecorder
- **MISSING.** No voice activity detection before `mediaRecorder.start()`.
- voice.py:442 uses `webrtcvad.Vad(2)` for desktop path — browser path has no equivalent.

### Q15: MediaRecorder timeslice
- `edith_dashboard.html:1336`: `mediaRecorder.start();` — no timeslice argument.
- `ondataavailable` fires **only on stop**, not continuously.
- All audio accumulates in `chunks[]` → single blob on stop.

### Q16: Minimum speaking duration before silence detection activates
- `startSilenceDetection` lines 1268–1303: no `hasSpeechDetected` flag, no minimum speaking time.
- Interval fires every 100ms from t=0.
- **MISSING.** No 300ms gate. No minimum speaking duration anywhere in code.

### Q17: Minimum audio duration check after recording stops
- `edith_dashboard.html:1329–1334`: `if (chunks.length === 0) { ... return; }`
- Only checks chunks empty. 200ms noise blob = 1 chunk → passes.
- **MISSING.** 200ms accidental noise triggers full Groq request.

---

## ISSUE 4 — Browser audio pipeline

### Q18: echoCancellation
- `edith_dashboard.html:1317`: `{ audio: true }` — **NOT EXPLICITLY SET.**
- No guarantee against picking up EDITH's own TTS speaker output.

### Q19: noiseSuppression
- `edith_dashboard.html:1317`: `{ audio: true }` — **NOT EXPLICITLY SET.**

### Q20: autoGainControl
- `edith_dashboard.html:1317`: `{ audio: true }` — **NOT EXPLICITLY SET.**
- Browser default usually `true` → amplifies quiet background = amplifies ambient noise.

### Q21: Delay before recording starts after mic open
- `edith_dashboard.html:1317–1336`: getUserMedia → createAnalyser → connect → `mediaRecorder.start()`
- **No delay.** Captures click sound and mic init noise immediately.

### Q22: Sample rate
- `edith_dashboard.html:1325–1327`: `new MediaRecorder(micStream, { mimeType: '...' })`
- **Not specified.** Browser default (48000 or 44100 Hz). Not explicitly set.

---

## ISSUE 5 — Whisper hallucination patterns

### Q23: Hallucination string filters in chat_server.py
- `chat_server.py:320–321`: empty string only.
- **MISSING** ALL of: "thank you", "thanks for watching", "thanks", "bye", "goodbye",
  "subtitles", "www.", single characters, numbers-only strings.

### Q24: Minimum length check after transcript
- `chat_server.py:320`: `if not transcript or not transcript.strip():`
- Rejects empty string only. "ok" (1 word, 2 chars) passes. "thanks" passes.
- **MISSING** minimum word/char count.

### Q25: Semantic check on transcript
- **MISSING.** No semantic validation in chat_server.py or edith_dashboard.html before LLM routing.

---

## FINAL — Root cause summary

### Q26: PRIMARY reason mic picks up background noise
- **`edith_dashboard.html:1270`** — `SILENCE_THRESHOLD = 15` is root cause.
- Ambient noise avgLevel > 15 always → silence never detected → 15s noise blob sent to Groq.
- Secondary: **`edith_dashboard.html:1317`** — no explicit `noiseSuppression: true`.

### Q27: PRIMARY reason Groq returns hallucinated words
- **`chat_server.py:278`** — `len(audio_bytes) < 100` lets all noise blobs through.
- Groq Whisper on near-silent audio = known hallucination behavior.

### Q28: PRIMARY reason wrong language detected
- **`voice.py:97`** + **`chat_server.py:305`** — no `language` parameter in Groq STT calls.
- Whisper auto-detects from noise → assigns arbitrary language → hallucinates in it.

### Q29: All missing checks, ranked by importance

| Rank | MISSING CHECK | File | Line | What to add |
|------|--------------|------|------|-------------|
| 1 | Audio energy check before Groq | edith_dashboard.html | 1329 (onstop) | Reject blob if avg RMS below floor |
| 2 | Minimum recording duration | edith_dashboard.html | 1329 (onstop) | Reject if duration < 1000ms |
| 3 | Blob size threshold too low | chat_server.py | 278 | Raise 100 → 5000+ bytes |
| 4 | Hallucination phrase filter | chat_server.py | 320 | Block known ghost strings |
| 5 | Minimum transcript word count | chat_server.py | 320 | Reject < 2 words or < 5 chars |
| 6 | VAD before MediaRecorder start | edith_dashboard.html | 1317 | Require speech before recording |
| 7 | Minimum speaking duration gate | edith_dashboard.html | 1268 | hasSpeechDetected flag; start silence timer only after real speech detected |
| 8 | Explicit audio constraints | edith_dashboard.html | 1317 | echoCancellation:true, noiseSuppression:true, autoGainControl:false |
| 9 | Startup delay | edith_dashboard.html | 1336 | setTimeout 200ms before mediaRecorder.start() |
| 10 | Semantic check | chat_server.py | 322 | Validate transcript before routing |

### Q30: 3 most important fixes

1. **`edith_dashboard.html:1270`** — `SILENCE_THRESHOLD = 15`
   Root cause of noise blobs. 5.9% amplitude. Room noise exceeds this constantly.
   Fix: raise to 30–40 AND add `hasSpeechDetected` flag before starting silence timer.

2. **`chat_server.py:278`** — `len(audio_bytes) < 100`
   Noise blobs reach Groq → Whisper hallucinates. 100 bytes = nothing filtered.
   Fix: raise minimum to 5000+ bytes.

3. **`voice.py:97`** + **`chat_server.py:305`** — no `language` parameter
   Whisper auto-detects from noise → arbitrary language → wrong-language hallucinations.
   Fix: add `"language": "en"` to data dict in both Groq STT calls.

## Q1: What happens when user clicks VOICE CHANNEL button?

Button: edith_dashboard.html line 694
```html
<div class="action-btn" id="btn-voice" onclick="handleBtnVoice(event)">
```

Function chain:
- line 1108: `handleBtnVoice(e)` → calls `triggerRipple('btn-voice')` then `toggleVoiceMode()`
- line 1116-1127: `toggleVoiceMode()`:
  1. If already active → stopVoice()
  2. `navigator.mediaDevices.getUserMedia({ audio: true })` — open mic
  3. `new AudioContext()` — create audio context
  4. `createAnalyser()` — create analyser node (fftSize 512)
  5. `micStream source → connect(analyser)` — pipe mic into analyser
  6. `voiceActive = true`
  7. `setOrbState('listening')` — visual animation
  8. Add 'active','pulsing' CSS classes to button

---

## Q2: Does it record audio from browser microphone?

`getUserMedia({ audio: true })` called at line 1119 — YES mic is opened.

BUT: stream is ONLY connected to AnalyserNode (line 1122: `src.connect(analyser)`).
AnalyserNode = visualization only. No data captured.

- NO MediaRecorder created anywhere
- NO audio data buffered
- NO ondataavailable handler
- NO recording — pure waveform visualization

Same for chat mic (`startChatMic` lines 1271-1279) — also visualizer only.

---

## Q3: After recording — where does audio go?

NOWHERE. Stream never leaves the AnalyserNode.
No MediaRecorder.start(). No blob. No fetch() with audio body.
Zero backend calls with audio data from either voice button.

---

## Q4: Does audio endpoint exist in chat_server.py?

NO audio-accepting endpoint exists.

`GET /api/voice-status` (line 508) — returns JSON status only, accepts no audio.
No endpoint takes multipart/form-data, audio/wav, or raw audio bytes.

ENDPOINT DOES NOT EXIST.

---

## Q5: After LLM generates response — how does dashboard get it back?

SSE stream. Text chat only (voice never reaches LLM).

- line 1176: `sendToEdith(text)`
- line 1179: `fetch('/api/chat/stream', { method: 'POST', body: JSON.stringify({ message: text }) })`
- line 1184: `res.body.getReader()` — reads text/event-stream
- Events: `start`, `transcript`, `token`, `done`, `error`
- line 1225-1226: tokens accumulated in `streamBuffer` Map → streamed into chat bubble word-by-word

---

## Q6: After response received — does dashboard display it? TTS?

DISPLAY: Yes — streamed tokens render in chat panel via streamBuffer.

TTS: NO browser TTS. No `window.speechSynthesis` calls in dashboard HTML.
Python-side `speak()` exists in `voice.py` / `edith_widget.py` / `wake_listener.py`
but NOT triggered by web dashboard responses. Only triggered by hardware wake word path.

---

## Q7: WHERE EXACTLY DOES THE FLOW BREAK?

**File: edith_dashboard.html, lines 1119-1122**

```js
micStream = await navigator.mediaDevices.getUserMedia({ audio: true });
audioCtx = new (window.AudioContext || window.webkitAudioContext)();
analyser = audioCtx.createAnalyser(); analyser.fftSize = 512;
const src = audioCtx.createMediaStreamSource(micStream); src.connect(analyser);
```

Mic opened but ONLY piped to AnalyserNode for visual animation.
No MediaRecorder → no audio data → no STT → no text → no LLM call.

VOICE CHANNEL button = visualizer only. Zero connection to chat pipeline.
Chat mic button (`startChatMic` line 1271-1279) = same problem.

ENTIRE browser→STT→LLM→TTS voice pipeline IS MISSING.

---

## Q8: Audio-related endpoints in chat_server.py?

Only voice-related endpoint:
- `GET /api/voice-status` — line 508 — returns `{mode, tts_engine, tts_color}` — NO audio input

NO endpoint accepts audio bytes from browser. Zero audio upload endpoints exist.

---

## Q9: Does voice channel use same /api/chat endpoint as text?

NO. Voice channel (`toggleVoiceMode`) makes ZERO fetch calls.

- Text chat: `POST /api/chat/stream` (line 1179)
- Voice channel: no fetch at all
- `stopAllActive` (line 1140) sends `{message:'session_end'}` to `/api/chat` — that's TERMINATE button, not voice

---

## Q10: Complete endpoint list in chat_server.py

| Line | Method | Route |
|------|--------|-------|
| 57 | GET | `/` |
| 146 | POST | `/api/chat/stream` |
| 198 | POST | `/api/chat` |
| 335 | GET | `/api/system-status` |
| 341 | GET | `/api/recent_traces` |
| 364 | GET | `/api/monitor_schedule` |
| 385 | POST | `/api/feedback` |
| 424 | GET | `/dashboard` |
| 437 | GET | `/api/stats` |
| 457 | GET | `/api/status` |
| 508 | GET | `/api/voice-status` |
| 541 | GET | `/api/last-memory` |
| 564 | GET | `/api/phone` |
| 593 | GET | `/api/weather-status` |
| 606 | GET | `/api/traces/recent` |
| 645 | GET | `/api/logs/stream` (SSE) |
| 686 | GET | `/api/mcp/status` |
| 698 | GET | `/api/mcp/tools/{server_name}` |
| 710 | POST | `/api/mcp/call` |
| 730 | GET | `/api/mcp/config` |
| 742 | POST | `/api/mcp/config/add` |
| 771 | POST | `/api/mcp/config/toggle/{server_name}` |
| 792 | DELETE | `/api/mcp/config/remove/{server_name}` |
| 877 | GET | `/api/devpanel/modules` |
| 891 | POST | `/api/devpanel/query` |

---

## SUMMARY

Voice channel button = pure visualizer. No recording. No STT. No backend audio endpoint.
Entire browser→STT→LLM→TTS voice pipeline missing from web UI.
Text chat pipeline works (SSE stream via /api/chat/stream).
Voice pipeline does not exist in web UI.
