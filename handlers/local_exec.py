"""
handlers/local_exec.py — _run_local_exec helper (local system/file ops detection)
Shared by shell and search handlers.
"""

import os
import re
import shlex

from config import get_logger, get_user_dir, USER_HOME
from command_runner import run_piped_command, run_command

log = get_logger("handlers.local_exec")

_SYSINFO_TERMS = [
    (re.compile(r"\b(os|operating system|distro|linux version|what os)\b", re.I),
     "OS", "lsb_release -d 2>/dev/null || grep PRETTY_NAME /etc/os-release | cut -d= -f2 | tr -d '\"'"),
    (re.compile(r"\bkernel\b", re.I),
     "Kernel", "uname -r"),
    (re.compile(r"\b(cpu|processor)\b", re.I),
     "CPU", "lscpu | grep 'Model name' | sed 's/.*: *//' | head -1"),
    (re.compile(r"\b(ram|memory|mem)\b", re.I),
     "RAM", "free -h | grep ^Mem"),
    (re.compile(r"\bdisk\b", re.I),
     "Disk", "df -h -x tmpfs -x devtmpfs 2>/dev/null"),
    (re.compile(r"\bhostname\b", re.I),
     "Hostname", "hostname"),
    (re.compile(r"\buptime\b", re.I),
     "Uptime", "uptime -p"),
    (re.compile(r"\b(local|network|private|lan)\s+(ip|address|addr)\b|\bmy\s+ip\b|\bwhat.*my.*ip\b", re.I),
     "Network", "ip -br addr show"),
    (re.compile(r"\bmtu\b", re.I),
     "MTU", "ip link show | grep -E 'mtu|UP'"),
    (re.compile(r"\bnetwork interfaces?\b|\bshow.*interfaces?\b|\blist.*interfaces?\b", re.I),
     "Interfaces", "ip -br link show"),
]


def run_local_exec(user_input: str):
    """
    Detect and execute local system/file ops. Never web-search, never hallucinate.
    Returns result string or None if query is not a local op.
    """
    if os.getenv("EDITH_NODE_TYPE", "local") == "cloud":
        return None
    import random as _random
    import shutil as _shutil

    lower = user_input.lower()

    # ── 1. Process / resource monitoring ─────────────────────────────────────
    _PROC_PAT = re.compile(
        r"\b(process(?:es)?|running apps?|applications?)\b.{0,40}\b(cpu|memory|ram|consuming|usage)\b"
        r"|\b(cpu|memory|ram)\b.{0,40}\b(process(?:es)?|consuming|usage)\b"
        r"|\bps\b.{0,30}\b(cpu|mem|process)\b"
        r"|\b(running processes|active processes|top processes)\b",
        re.I
    )
    if _PROC_PAT.search(user_input):
        thresh_m = re.search(r"(\d+)\s*%", user_input)
        threshold = float(thresh_m.group(1)) if thresh_m else 0
        by_mem = bool(re.search(r"\b(memory|ram|mem)\b", lower))
        sort_col = "-%mem" if by_mem else "-%cpu"
        col_idx = "4" if by_mem else "3"
        if threshold > 0:
            cmd = f"ps aux --sort={sort_col} | awk 'NR==1 || ${col_idx}>{threshold}' | head -30"
        else:
            cmd = f"ps aux --sort={sort_col} | head -25"
        r = run_piped_command(cmd, timeout=10)
        out = (r.output or "").strip()
        if out:
            return f"```\n{out}\n```"

    # ── 2. Compound sysinfo ───────────────────────────────────────────────────
    matched_sys = [(label, cmd) for pat, label, cmd in _SYSINFO_TERMS if pat.search(user_input)]
    if len(matched_sys) >= 2:
        parts = []
        for label, cmd in matched_sys:
            r = run_piped_command(cmd, timeout=5)
            v = (r.output or "").strip()
            if v:
                parts.append(f"**{label}:**\n```\n{v}\n```")
        if parts:
            return "\n\n".join(parts)

    # ── 3. Single sysinfo term ────────────────────────────────────────────────
    if len(matched_sys) == 1:
        label, cmd = matched_sys[0]
        r = run_piped_command(cmd, timeout=5)
        v = (r.output or "").strip()
        if v:
            return f"```\n{v}\n```"

    # ── 4. Duplicate file finding ─────────────────────────────────────────────
    _DUP_PAT = re.compile(
        r"\b(duplicate|identical|same)\b.{0,20}\bfiles?\b"
        r"|\bfiles?\b.{0,20}\b(duplicate|identical)\b"
        r"|\bfind.*\bduplicate\b|\bduplicate.*\bfind\b",
        re.I
    )
    if _DUP_PAT.search(user_input):
        search_dir = USER_HOME
        for kw in ["downloads", "documents", "desktop"]:
            if kw in lower:
                search_dir = get_user_dir(kw)
                break
        abs_m = re.search(r"(/[^\s]+)", user_input)
        if abs_m:
            search_dir = abs_m.group(1)
        _safe_search_dir = shlex.quote(search_dir)
        r = run_piped_command(f"fdupes -r {_safe_search_dir} 2>/dev/null | head -50", timeout=30)
        out = (r.output or "").strip()
        if not out:
            r2 = run_piped_command(
                f"find {_safe_search_dir} -type f -not -empty 2>/dev/null | xargs md5sum 2>/dev/null "
                f"| sort | awk '{{if(prev==$1)print $0; prev=$1}}' | head -20",
                timeout=30
            )
            out = (r2.output or "").strip() or "No duplicate files found."
        return f"```\n{out}\n```"

    # ── 5. Find files by extension / size / date ──────────────────────────────
    _FIND_PAT = re.compile(
        r"\b(find all|find|locate|search for|list all)\b.{0,40}\bfiles?\b"
        r"|\bfiles?\b.{0,10}\b(larger|bigger|over|more than|smaller)\b"
        r"|\b\.(log|py|txt|pdf|jpg|png|mp4|csv|sh|conf|json|zip|mp3|tar|gz)\b.{0,20}\b(larger|smaller|files?|find)\b"
        r"|\bfind.{0,20}\b\.(log|py|txt|pdf|jpg|png|mp4|csv|sh|conf|json|zip|mp3|tar|gz)\b",
        re.I
    )
    if _FIND_PAT.search(user_input):
        ext_m = re.search(r"\.(log|py|txt|pdf|jpg|jpeg|png|mp4|csv|sh|conf|json|zip|tar|gz|mp3|wav|docx|xlsx)\b", lower)
        ext = ext_m.group(0) if ext_m else None
        size_m = re.search(r"(larger|bigger|greater|over|more than|>)\s*(\d+)\s*(mb|gb|kb)", lower)
        size_flag = None
        if size_m:
            n = int(size_m.group(2))
            unit = size_m.group(3)
            size_flag = f"+{n}M" if unit == "mb" else (f"+{n}G" if unit == "gb" else f"+{n}k")
        sort_desc = bool(re.search(r"\b(descend|largest|biggest|sort.*desc)\b", lower))
        name_part = f'-name "*{ext}"' if ext else '-type f'
        size_part = f"-size {size_flag}" if size_flag else ""
        cmd = (
            f"find {USER_HOME} {name_part} {size_part} 2>/dev/null "
            f"-exec ls -lh {{}} \\; 2>/dev/null"
        )
        if sort_desc or size_flag:
            cmd += " | sort -k5 -rh"
        cmd += " | head -30"
        r = run_piped_command(cmd, timeout=20)
        out = (r.output or "").strip()
        if out:
            return f"```\n{out}\n```"
        return f"No {ext or ''} files found matching criteria in {USER_HOME}."

    # ── 6. Random file selection + actual copy ────────────────────────────────
    _RAND_PAT = re.compile(
        r"\b(random(ly)?|select|pick|sample)\b.{0,50}\b(copy|move|put)\b"
        r"|\b(copy|move)\b.{0,30}\brandom\b"
        r"|\brandomly\s+(select|pick|choose|copy)\b",
        re.I
    )
    if _RAND_PAT.search(user_input):
        count_m = re.search(r"\b(\d+)\b", user_input)
        count = int(count_m.group(1)) if count_m else 10
        dest_dir = get_user_dir("downloads")
        for kw in ["downloads", "download", "documents", "desktop", "pictures", "home"]:
            if kw in lower:
                dest_dir = get_user_dir(kw)
                break
        test_m = re.search(r"\btest\s+folder\b|\btest_folder\b", lower)
        named_m = re.search(r"\bfolder\s+named\s+(\w+)\b|\bfolder\s+called\s+(\w+)\b", lower)
        if test_m:
            dest_dir = os.path.join(dest_dir, "test")
        elif named_m:
            folder_name = named_m.group(1) or named_m.group(2)
            dest_dir = os.path.join(dest_dir, folder_name)
        src_dir = USER_HOME
        src_m = re.search(r"\bfrom\s+(\w+)\b", lower)
        if src_m:
            src_dir = get_user_dir(src_m.group(1))
        try:
            all_files = [f for f in os.listdir(src_dir) if os.path.isfile(os.path.join(src_dir, f))]
        except OSError as e:
            return f"❌ Cannot access `{src_dir}`: {e}"
        if not all_files:
            return f"❌ No files in `{src_dir}`."
        selected = _random.sample(all_files, min(count, len(all_files)))
        os.makedirs(dest_dir, exist_ok=True)
        copied, failed = [], []
        for f in selected:
            src_path = os.path.join(src_dir, f)
            dst_path = os.path.join(dest_dir, f)
            try:
                _shutil.copy2(src_path, dst_path)
                if os.path.isfile(dst_path):
                    copied.append(f)
                else:
                    failed.append(f"{f}: not found after copy")
            except Exception as e:
                failed.append(f"{f}: {e}")
        summary = f"📁 Copied {len(copied)}/{len(selected)} files to `{dest_dir}`:\n"
        summary += "\n".join(f"  • {f}" for f in copied)
        if failed:
            summary += f"\n\n❌ Failed: {', '.join(failed[:5])}"
        return summary

    # ── 7. Network connectivity / ping / DNS ──────────────────────────────────
    _NET_PAT = re.compile(
        r"\b(ping|network access|internet connectivity|dns resolution|resolve dns|"
        r"validate network|check.*internet|check.*connectivity|network.*test|"
        r"pinging.*server|check.*ping|am i online|test.*network)\b",
        re.I
    )
    if _NET_PAT.search(user_input):
        parts = []
        r1 = run_piped_command("ping -c 3 -W 2 8.8.8.8 2>&1", timeout=15)
        if r1.output:
            parts.append(f"**Ping (8.8.8.8):**\n```\n{r1.output}\n```")
        r2 = run_piped_command("ping -c 2 -W 2 google.com 2>&1 | tail -3", timeout=10)
        if r2.output:
            parts.append(f"**DNS + Ping (google.com):**\n```\n{r2.output}\n```")
        r3 = run_piped_command("nslookup google.com 2>/dev/null | tail -4", timeout=8)
        if r3.output:
            parts.append(f"**DNS Lookup:**\n```\n{r3.output}\n```")
        if parts:
            return "\n\n".join(parts)
        return "❌ All network checks failed — likely offline."

    # ── 8. Privilege / permission check ──────────────────────────────────────
    _PRIV_PAT = re.compile(
        r"\b(privilege|permission|sudo access|current user|whoami|user permissions|"
        r"restricted director|groups?\b.*user|check.*permission|my.*user.*info|"
        r"id\s+command|who am i|check.*sudo)\b",
        re.I
    )
    if _PRIV_PAT.search(user_input):
        parts = []
        r1 = run_piped_command("whoami && id && groups", timeout=5)
        if r1.output:
            parts.append(f"**User / Groups:**\n```\n{r1.output}\n```")
        r2 = run_piped_command("sudo -l 2>&1 | head -20", timeout=8)
        if r2.output:
            parts.append(f"**Sudo Permissions:**\n```\n{r2.output}\n```")
        r3 = run_piped_command(
            "ls -ld /root /etc/sudoers /etc/shadow 2>&1 | awk '{print $1, $3, $4, $NF}'",
            timeout=5
        )
        if r3.output:
            parts.append(f"**Restricted Paths:**\n```\n{r3.output}\n```")
        if parts:
            return "\n\n".join(parts)

    # ── 9. Test execution / run multiple commands ─────────────────────────────
    _TEST_CMDS_PAT = re.compile(
        r"\b(test|check|verify|validate)\b.{0,50}\b(command|execution|capability|terminal)\b"
        r"|\brunning\s+(linux\s+)?commands?\s+(like|such as|including)\b"
        r"|\brun\s+(ls|pwd|df|free|ps|uname|whoami|id|hostname|uptime)\b",
        re.I
    )
    if _TEST_CMDS_PAT.search(user_input):
        _KNOWN_CMDS = ["ls", "pwd", "df", "free", "ps", "uname", "whoami", "id", "hostname", "uptime", "date", "env", "who"]
        found_cmds = [c for c in _KNOWN_CMDS if re.search(r'\b' + c + r'\b', user_input, re.I)]
        if not found_cmds:
            found_cmds = ["ls", "pwd", "df", "free", "ps"]
        parts = []
        for c in found_cmds:
            r = run_command(c, timeout=5, check_paths=False)
            out = (r.output or "").strip()
            if out:
                parts.append(f"**`{c}`:**\n```\n{out[:300]}\n```")
        if parts:
            return "\n\n".join(parts)

    return None
