import sys
import os
import json


def main():
    script_dir = os.path.dirname(os.path.abspath(__file__))
    friend_wav = os.path.join(script_dir, "voices", "friend.wav")

    if not os.path.exists(friend_wav):
        print(json.dumps({"status": "error", "message": f"friend.wav not found at {friend_wav}"}), flush=True)
        sys.exit(1)

    try:
        from chatterbox.tts import ChatterboxTTS
        import torchaudio
        model = ChatterboxTTS.from_pretrained(device="cpu")
    except Exception as e:
        print(json.dumps({"status": "error", "message": f"Model load failed: {e}"}), flush=True)
        sys.exit(1)

    # Signal parent that model is loaded and ready for requests
    print(json.dumps({"status": "ready"}), flush=True)

    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except json.JSONDecodeError as e:
            print(json.dumps({"status": "error", "message": f"JSON parse error: {e}"}), flush=True)
            continue

        if req.get("exit"):
            break

        text = req.get("text", "")
        out_wav = req.get("out_wav", "")

        if not text or not out_wav:
            print(json.dumps({"status": "error", "message": "missing text or out_wav"}), flush=True)
            continue

        try:
            wav = model.generate(
                text,
                audio_prompt_path=friend_wav,
                exaggeration=0.5,
                cfg_weight=0.5,
                temperature=0.8,
            )
            torchaudio.save(out_wav, wav, model.sr)
            print(json.dumps({"status": "ok", "out_wav": out_wav}), flush=True)
        except Exception as e:
            print(json.dumps({"status": "error", "message": str(e)}), flush=True)


if __name__ == "__main__":
    main()
