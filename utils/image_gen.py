import os
import urllib.parse
import requests
from config import IMAGES_DIR, get_logger
from smart_router import smart_call

def _llm(prompt, intent="chat"):
    return smart_call(prompt, intent=intent)

def _llm_gen(prompt, intent="chat"):
    return smart_call(prompt, intent=intent)

log = get_logger("image_gen")
os.makedirs(IMAGES_DIR, exist_ok=True)

def generate_image(prompt):
    print(f"[EDITH] Generating image for: {prompt}")
    encoded = urllib.parse.quote(prompt)
    url = f"https://image.pollinations.ai/prompt/{encoded}?width=512&height=512&nologo=true"

    save_path = os.path.join(IMAGES_DIR, "generated.png")
    print("[EDITH] Calling Pollinations API (free, no key needed)...")
    try:
        r = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=30)
        r.raise_for_status()
        with open(save_path, "wb") as f:
            f.write(r.content)
        print(f"[EDITH] Image saved to: {save_path}")
        return save_path
    except Exception as e:
        log.error(f"Image generation failed: {e}")
        print(f"[EDITH] Image generation failed: {e}")
        return None

def enhance_prompt_with_qwen(raw_prompt):
    print("[EDITH] Enhancing prompt with Qwen...")
    prompt = f"Turn this into a detailed image generation prompt in one sentence, no explanation: {raw_prompt}"
    return _llm_gen(prompt, intent="reason")

def image_generator():
    print("\n[EDITH Image Generator] Powered by Pollinations.ai")
    print("Describe what you want to see:")
    raw = input(">> ").strip()
    if not raw:
        print("No prompt given.")
        return

    enhance = input("\nEnhance prompt with AI? [y/n]: ").strip().lower()
    if enhance == "y":
        prompt = enhance_prompt_with_qwen(raw)
        print(f"\n[EDITH] Enhanced prompt: {prompt}")
    else:
        prompt = raw

    import subprocess
    path = generate_image(prompt)
    if path:
        subprocess.Popen(["xdg-open", path])
        print("\n✅ Image opened!")

if __name__ == "__main__":
    image_generator()
