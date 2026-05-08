import os
import subprocess
import shutil

# --- HITL Confirmation (The Non-Negotiable Rule) ---
def confirm(action_description):
    print(f"\n{'='*50}")
    print(f"⚠️  EDITH wants to: {action_description}")
    print(f"{'='*50}")
    while True:
        answer = input("Type Y to confirm or N to cancel: ").strip().lower()
        if answer in ["y", "n"]:
            return answer == "y"
        print("Please type Y or N")

# --- File Tools ---
def read_file(path):
    try:
        with open(path, "r") as f:
            return f.read()
    except Exception as e:
        return f"Error reading file: {e}"

def write_file(path, content, interactive=True):
    if interactive and not confirm(f"Write to file: {path}"):
        return "Action cancelled by user."
    try:
        with open(path, "w") as f:
            f.write(content)
        return f"File written: {path}"
    except Exception as e:
        return f"Error writing file: {e}"

def delete_file(path, interactive=True):
    if interactive and not confirm(f"DELETE file: {path}"):
        return "Action cancelled by user."
    try:
        os.remove(path)
        return f"File deleted: {path}"
    except Exception as e:
        return f"Error deleting file: {e}"

def move_file(src, dst):
    if not confirm(f"Move file: {src} → {dst}"):
        return "Action cancelled by user."
    try:
        shutil.move(src, dst)
        return f"File moved: {src} → {dst}"
    except Exception as e:
        return f"Error moving file: {e}"

def list_dir(path="."):
    try:
        items = os.listdir(path)
        return "\n".join(items)
    except Exception as e:
        return f"Error listing directory: {e}"

# --- Shell Tool ---
def run_shell(command):
    import shlex
    if not confirm(f"Run shell command: {command}"):
        return "Action cancelled by user."
    try:
        result = subprocess.run(
            shlex.split(command),
            capture_output=True, text=True, timeout=30
        )
        output = result.stdout or result.stderr
        return output.strip() or "Command ran with no output."
    except subprocess.TimeoutExpired:
        return "Command timed out after 30 seconds."
    except Exception as e:
        return f"Error running command: {e}"
