import subprocess
import shlex
import datetime
import os
from config import LOG_DIR, EDITH_PATH, get_logger

log = get_logger("security")
AUDIT_LOG = os.path.join(LOG_DIR, "security_audit.log")

def run(cmd):
    if not isinstance(cmd, (str, list)):
        raise ValueError(f"run() expects str or list, got {type(cmd)}")
    if isinstance(cmd, str):
        cmd = shlex.split(cmd)
    r = subprocess.run(cmd, shell=False, capture_output=True, text=True)
    return r.stdout.strip() or r.stderr.strip()

def audit():
    lines = []
    ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    lines.append("=" * 50)
    lines.append("EDITH Security Audit — " + ts)
    lines.append("=" * 50)

    lines.append("\n[FIREWALL]")
    fw = run("sudo ufw status")
    lines.append(fw)
    lines.append("Firewall: ACTIVE OK" if "active" in fw.lower() else "Firewall: INACTIVE WARNING")

    lines.append("\n[OPEN PORTS]")
    lines.append(run("ss -tlnp"))

    lines.append("\n[DOCKER STATUS]")
    lines.append(run("docker ps 2>/dev/null || echo 'No containers running'"))

    lines.append("\n[DISK ENCRYPTION]")
    lsblk = run("lsblk -o NAME,TYPE,FSTYPE")
    if "crypto" in lsblk or "luks" in lsblk.lower():
        lines.append("LUKS detected OK")
    else:
        lines.append("No LUKS encryption WARNING — consider encrypting /home")

    lines.append("\n[OLLAMA EXPOSURE]")
    ollama_check = run("ss -tlnp | grep 11434")
    if "127.0.0.1" in ollama_check:
        lines.append("Ollama localhost only OK")
    elif ollama_check:
        lines.append("WARNING: Ollama exposed! " + ollama_check)
    else:
        lines.append("Ollama not running")

    lines.append("\n[EDITH FILES PERMISSIONS]")
    lines.append(run(f"ls -la {EDITH_PATH}/*.py | awk '{{print $1, $9}}'"))

    report = "\n".join(lines)
    print(report)
    with open(AUDIT_LOG, "a") as f:
        f.write(report + "\n")
    print("\nAudit saved to " + AUDIT_LOG)
    log.info("Security audit completed")

if __name__ == "__main__":
    audit()
