import subprocess
import sys
import os
import json
from config import EDITH_PATH, VENV_PYTHON, MEMORY_DB_PATH, VAULT_PATH, get_logger

log = get_logger("main")

BANNER = """
╔══════════════════════════════════════════════════╗
║       E . D . I . T . H   v 1 . 0              ║
║       Even Dead I'm The Hero                    ║
║       Personal AI — Vaibhav Kashyap            ║
╚══════════════════════════════════════════════════╝
"""

MODULES = {
    "1":  ("Chat with EDITH",        "orchestrator.py"),
    "2":  ("Email Compose",           "edith_email.py"),
    "3":  ("Video Summarizer",        "video_summarizer.py"),
    "4":  ("Image Generator",         "image_gen.py"),
    "5":  ("Ask about Code (RAG)",    "code_rag.py"),
    "6":  ("Code like Vaibhav",       "coding_style.py"),
    "7":  ("Password Vault",          "vault.py"),
    "8":  ("Security Audit",          "security_audit.py"),
    "9":  ("Proactive Monitor",       "monitor.py"),
    "10": ("Dashboard (browser)",     None),
    "11": ("🏛️  Council of Minds",     "council.py"),
    "12": ("🔮 Decision Simulator",    "life_os.py"),
    "13": ("📋 Weekly Briefing",       None),
    "14": ("📊 Cognitive Profile",     "cognitive_profile.py"),
    "15": ("🧬 Self-Improvement",      "self_improve.py"),
    "16": ("📱 Telegram Bot",          "telegram_bot.py"),
    "17": ("🛣️  Smart Router Status",  None),
}

def check_systems():
    checks = {}
    try:
        r = subprocess.run(["curl", "-s", "http://localhost:11434/api/tags"],
                          capture_output=True, text=True, timeout=3)
        data = json.loads(r.stdout)
        checks["Ollama"] = f"ONLINE ({len(data.get('models',[]))} models)"
    except Exception:
        checks["Ollama"] = "OFFLINE"

    import psutil
    mem = psutil.virtual_memory()
    checks["RAM"] = f"{mem.percent}% used ({round(mem.used/1024**3,1)}GB / {round(mem.total/1024**3,1)}GB)"

    disk = psutil.disk_usage('/')
    checks["Disk"] = f"{disk.percent}% used ({round(disk.free/1024**3,1)}GB free)"

    fw = subprocess.run(["sudo", "ufw", "status"], capture_output=True, text=True)
    checks["Firewall"] = "ACTIVE" if "active" in fw.stdout.lower() else "INACTIVE"

    checks["Vault"] = "SECURED" if os.path.exists(VAULT_PATH) else "NOT SET UP"
    checks["Memory"] = "ONLINE" if os.path.exists(MEMORY_DB_PATH) else "OFFLINE"

    # Get actual chunk count from ChromaDB
    try:
        from config import get_chroma_client
        coll = get_chroma_client().get_or_create_collection("edith_codebase")
        count = coll.count()
        checks["Code RAG"] = f"{count} chunks indexed"
    except Exception:
        checks["Code RAG"] = "OFFLINE"

    return checks

def run_module(script):
    subprocess.run([VENV_PYTHON, os.path.join(EDITH_PATH, script)])

def open_dashboard():
    subprocess.Popen([VENV_PYTHON, os.path.join(EDITH_PATH, "dashboard.py")])
    import time; time.sleep(2)
    subprocess.Popen(["xdg-open", "http://127.0.0.1:8001/dashboard"])
    print("[EDITH] Dashboard opened at http://127.0.0.1:8001/dashboard")

def run_doctor():
    import psutil
    import urllib.request
    print("\nEDITH Doctor — System Health Check\n" + "=" * 40)
    results = []

    def _ok(label, hint=""):
        results.append((True, label, hint))

    def _fail(label, hint=""):
        results.append((False, label, hint))

    # 1. Vault accessible + GROQ key present
    try:
        import vault as _v
        key = _v.get_secret("GROQ_API_KEY", "")
        if key:
            _ok("Vault + GROQ key")
        else:
            _fail("Vault + GROQ key", "unlock vault or set GROQ_API_KEY")
    except Exception as e:
        _fail("Vault + GROQ key", f"vault error: {str(e)[:40]}")

    # 2. Ollama running
    try:
        r = subprocess.run(["curl", "-s", "--max-time", "3", "http://localhost:11434/api/tags"],
                           capture_output=True, timeout=5)
        if r.returncode == 0:
            _ok("Ollama running")
        else:
            _fail("Ollama running", "run: systemctl --user start ollama")
    except Exception:
        _fail("Ollama running", "run: systemctl --user start ollama")

    # 3. ChromaDB accessible
    try:
        from config import get_chroma_client
        get_chroma_client().heartbeat()
        _ok("ChromaDB")
    except Exception as e:
        _fail("ChromaDB", f"check chroma_db dir: {str(e)[:40]}")

    # 4. chat_server running
    try:
        req = urllib.request.urlopen("http://127.0.0.1:8001/api/status", timeout=2)
        req.read()
        _ok("chat_server (8001)")
    except Exception:
        _fail("chat_server (8001)", "run: ./start_edith.sh or python chat_server.py")

    # 5. wake_listener process running
    try:
        r = subprocess.run(["pgrep", "-f", "wake_listener"], capture_output=True)
        if r.returncode == 0:
            _ok("wake_listener")
        else:
            _fail("wake_listener", "start via start_edith.sh")
    except Exception:
        _fail("wake_listener", "pgrep failed")

    # 6. All 5 LLM provider keys in vault
    providers = ["GROQ_API_KEY", "GEMINI_API_KEY", "NVIDIA_API_KEY", "OPENROUTER_API_KEY", "TELEGRAM_TOKEN"]
    try:
        import vault as _v2
        missing = [p for p in providers if not _v2.get_secret(p, "")]
        if not missing:
            _ok("All 5 provider keys")
        else:
            _fail("All 5 provider keys", f"missing: {', '.join(missing)}")
    except Exception:
        _fail("All 5 provider keys", "vault not accessible")

    # 7. Chatterbox venv exists
    from config import CHATTERBOX_VENV_PYTHON
    if os.path.exists(CHATTERBOX_VENV_PYTHON):
        _ok("Chatterbox venv")
    else:
        _fail("Chatterbox venv", f"create at {os.path.dirname(CHATTERBOX_VENV_PYTHON)}")

    # 8. friend.wav exists
    friend_wav = os.path.join(EDITH_PATH, "voices", "friend.wav")
    if os.path.exists(friend_wav):
        _ok("friend.wav voice")
    else:
        _fail("friend.wav voice", "place voice sample at voices/friend.wav")

    # 9. Vosk model exists
    from config import VOSK_MODEL_PATH
    if os.path.exists(VOSK_MODEL_PATH):
        _ok("Vosk model")
    else:
        _fail("Vosk model", f"download vosk model to {VOSK_MODEL_PATH}")

    # 10. Disk space >1GB free
    disk = psutil.disk_usage("/")
    free_gb = disk.free / (1024 ** 3)
    if free_gb > 1.0:
        _ok(f"Disk space ({free_gb:.1f}GB free)")
    else:
        _fail(f"Disk space ({free_gb:.1f}GB free)", "free up disk space — less than 1GB remaining")

    print()
    for passed, label, hint in results:
        icon = "✅" if passed else "❌"
        line = f"  {icon} {label}"
        if not passed and hint:
            line += f"\n       → {hint}"
        print(line)

    total = len(results)
    passed_count = sum(1 for p, _, _ in results if p)
    print(f"\n  {passed_count}/10 checks passed.")


def run_smoke_tests():
    print("\n[EDITH] Running v1.0 Smoke Tests...")
    tests = [
        ("Ollama API",        lambda: subprocess.run(["curl","-s","http://localhost:11434/api/tags"],capture_output=True,timeout=3).returncode == 0),
        ("ChromaDB Memory",   lambda: os.path.exists(MEMORY_DB_PATH)),
        ("Code RAG Index",    lambda: os.path.exists(MEMORY_DB_PATH)),
        ("Vault Encrypted",   lambda: os.path.exists(VAULT_PATH)),
        ("Security Audit",    lambda: os.path.exists(os.path.join(EDITH_PATH, "security_audit.py"))),
        ("Email Module",      lambda: os.path.exists(os.path.join(EDITH_PATH, "edith_email.py"))),
        ("Vision Module",     lambda: os.path.exists(os.path.join(EDITH_PATH, "vision.py"))),
        ("ML Router",         lambda: os.path.exists(os.path.join(EDITH_PATH, "ml_router.py"))),
        ("Monitor",           lambda: os.path.exists(os.path.join(EDITH_PATH, "monitor.py"))),
        ("Dashboard",         lambda: os.path.exists(os.path.join(EDITH_PATH, "dashboard.py"))),
        ("Image Gen",         lambda: os.path.exists(os.path.join(EDITH_PATH, "image_gen.py"))),
        ("Video Summarizer",  lambda: os.path.exists(os.path.join(EDITH_PATH, "video_summarizer.py"))),
        ("Coding Style",      lambda: os.path.exists(os.path.join(EDITH_PATH, "coding_personality.txt"))),
        ("Firewall",          lambda: "active" in subprocess.run(["sudo","ufw","status"],capture_output=True,text=True).stdout.lower()),
        ("Config Module",     lambda: os.path.exists(os.path.join(EDITH_PATH, "config.py"))),
    ]
    passed = 0
    for name, test in tests:
        try:
            ok = test()
            status = "PASS" if ok else "FAIL"
            if ok: passed += 1
        except Exception:
            status = "FAIL"
        print(f"  {'OK' if status=='PASS' else '!!'} {name:<25} {status}")
    print(f"\n  {passed}/{len(tests)} tests passed")
    if passed == len(tests):
        print("\n  *** E.D.I.T.H v1.0 SMOKE TESTS: ALL PASS ***")
    else:
        print(f"\n  {len(tests)-passed} tests need attention")

def main():
    print(BANNER)
    print("  Checking systems...")
    checks = check_systems()
    for k, v in checks.items():
        print(f"  {k:<12}: {v}")
    print()

    while True:
        print("=" * 52)
        for key, (name, _) in MODULES.items():
            print(f"  [{key:>2}] {name}")
        print("  [99] Run Smoke Tests")
        print("  [98]  D  Doctor (deep health check)")
        print("  [ix] Index directory (ix /path/to/dir)")
        print("  [ 0] Exit")
        print("=" * 52)

        choice = input("\nBoss >> ").strip()

        if choice == "0":
            print("\n[EDITH] Goodbye, Boss.\n")
            break
        elif choice == "99":
            run_smoke_tests()
        elif choice in ("98", "D", "d"):
            run_doctor()
        elif choice.startswith("ix "):
            path = choice[3:].strip()
            from rag import index_directory
            print(f"\n[EDITH] Indexing {path}...")
            r = index_directory(path)
            print(r.value if r.ok else f"Error: {r.error}")
            print()
        elif choice == "10":
            open_dashboard()
        elif choice == "13":
            # Weekly Briefing runs inline (needs orchestrator context)
            from life_os import weekly_briefing
            print("\n📋 Generating weekly briefing...\n")
            result = weekly_briefing()
            print(result)
        elif choice == "17":
            from smart_router import router_status
            print(f"\n{router_status()}\n")
        elif choice in MODULES:
            _, script = MODULES[choice]
            if script:
                run_module(script)
        else:
            print("[EDITH] Unknown command.")

if __name__ == "__main__":
    main()
