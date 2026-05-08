import subprocess
import os
from config import DOWNLOADS_DIR, MODELS, get_logger
from smart_router import smart_call

log = get_logger("video")
os.makedirs(DOWNLOADS_DIR, exist_ok=True)

def download_audio(url):
    print("[EDITH] Downloading audio from YouTube...")
    out_path = os.path.join(DOWNLOADS_DIR, "video_audio")
    result = subprocess.run([
        "yt-dlp",
        "-x", "--audio-format", "mp3",
        "--audio-quality", "0",
        "-o", out_path + ".%(ext)s",
        "--no-playlist",
        url
    ], capture_output=True, text=True)

    if result.returncode != 0:
        print("Error downloading:", result.stderr[-300:])
        return None

    mp3_path = out_path + ".mp3"
    if os.path.exists(mp3_path):
        print(f"[EDITH] Audio saved: {mp3_path}")
        return mp3_path

    for f in os.listdir(DOWNLOADS_DIR):
        if f.startswith("video_audio"):
            return os.path.join(DOWNLOADS_DIR, f)
    return None

def transcribe_audio(audio_path):
    print("[EDITH] Transcribing with Whisper.cpp (reusing voice model)...")
    print("       This may take 1-2 minutes depending on video length...")
    try:
        from voice import _get_whisper
        w = _get_whisper()
        segments = w.transcribe(audio_path)
        text = " ".join(seg.text.strip() for seg in segments if seg.text.strip())
        return text if text else None
    except Exception as e:
        log.error(f"Whisper transcription failed: {e}")
        print(f"Transcription error: {e}")
        return None

def summarize_with_qwen(transcript, title="this video"):
    print("[EDITH] Summarizing with Qwen...")
    prompt = f"""Summarize the following video transcript in a clear, concise way.

Structure your summary as:
1. TOPIC: What is this video about (1 sentence)
2. KEY POINTS: 3-5 main points as bullet points
3. CONCLUSION: Main takeaway (1-2 sentences)

Transcript:
{transcript[:4000]}"""
    return smart_call(prompt, intent="chat")

def summarize_video():
    print("\n[EDITH Video Summarizer]")
    print("Paste a YouTube URL and I will summarize it for you.")
    url = input(">> ").strip()
    if not url:
        print("No URL given.")
        return

    audio_path = download_audio(url)
    if not audio_path:
        print("[EDITH] Failed to download audio.")
        return

    transcript = transcribe_audio(audio_path)
    if not transcript:
        print("[EDITH] Failed to transcribe audio.")
        return

    print(f"\n[EDITH] Transcript length: {len(transcript)} characters")
    summary = summarize_with_qwen(transcript)

    print("\n" + "="*50)
    print("  EDITH VIDEO SUMMARY")
    print("="*50)
    print(summary)
    print("="*50)

    transcript_path = os.path.join(DOWNLOADS_DIR, "last_transcript.txt")
    with open(transcript_path, "w") as f:
        f.write(transcript)
    print(f"\n[Full transcript saved to {transcript_path}]")
    os.remove(audio_path)

if __name__ == "__main__":
    summarize_video()
