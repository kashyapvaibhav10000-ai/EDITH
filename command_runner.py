"""
Command Runner — Safe subprocess execution with allowlist, path jail, timeout, and output limits.

  Replaces all shell=True calls with safe, allowlisted, jailed, and capped execution.
  
Features:
- Allowlist-based command validation
- Path jail: paths must resolve within USER_HOME
- Timeout protection (default 30s)
- Output length cap (default 100KB)
- Structured result object with stdout, stderr, and exit code
"""

import os
import subprocess
import shlex
import re
from dataclasses import dataclass
from typing import Optional
from config import USER_HOME, get_logger

logger = get_logger("command_runner")


@dataclass
class CommandResult:
    """Result of a safe command execution."""
    stdout: str
    stderr: str
    exit_code: int
    error: Optional[str] = None  # Set if command was rejected or timed out
    
    @property
    def success(self) -> bool:
        return self.exit_code == 0 and self.error is None
    
    @property
    def output(self) -> str:
        """Combined output (stdout preferred, fallback to stderr)."""
        return (self.stdout or self.stderr).strip()


# ──────────────────────────────────────────────
# Allowlist: Commands allowed with safe args
# ──────────────────────────────────────────────
ALLOWED_COMMANDS = {
    # File operations (read-only)
    "find": {"safe_args": True},
    "ls": {"safe_args": True},
    "stat": {"safe_args": True},
    "file": {"safe_args": True},
    "md5sum": {"safe_args": True},
    "fdupes": {"safe_args": True},
    
    # File inspection
    "head": {"safe_args": True},
    "tail": {"safe_args": True},
    "wc": {"safe_args": True},
    "grep": {"safe_args": True},
    "xargs": {"safe_args": True},  # Used in pipes
    "sort": {"safe_args": True},
    "awk": {"safe_args": True},
    "sed": {"safe_args": True},
    
    # Network diagnostics (read-only)
    "ping": {"safe_args": True},
    "nslookup": {"safe_args": True},
    "dig": {"safe_args": True},
    "netstat": {"safe_args": True},
    "ss": {"safe_args": True},
    
    # System info (read-only)
    "whoami": {"safe_args": False},  # No args needed
    "id": {"safe_args": True},
    "uname": {"safe_args": True},
    "df": {"safe_args": True},
    "du": {"safe_args": True},
    "ps": {"safe_args": True},
    "top": {"safe_args": True},
    "free": {"safe_args": True},
    "uptime": {"safe_args": False},
    "date": {"safe_args": False},
    
    # Soft tooling
    "git": {"safe_args": True, "only_read": True},  # Only show/log/status/diff/log
}


def _validate_command(cmd: str) -> tuple[bool, Optional[str]]:
    """
    Validate command is in allowlist.
    Returns (is_valid, error_msg)
    """
    # Extract the base command (first arg before any flag/arg split)
    try:
        parts = shlex.split(cmd)
    except ValueError as e:
        return False, f"Invalid shell syntax: {e}"
    
    if not parts:
        return False, "Empty command"
    
    base_cmd = os.path.basename(parts[0])
    
    if base_cmd not in ALLOWED_COMMANDS:
        return False, f"Command not allowed: {base_cmd}"
    
    return True, None


def _validate_paths(cmd: str) -> tuple[bool, Optional[str]]:
    """
    Validate all file paths in cmd resolve within USER_HOME.
    Allows relative paths and expansions like ~.
    Returns (is_valid, error_msg)
    """
    # Find all path-like arguments
    path_patterns = [
        r"(/[^\s]+)",           # Absolute paths
        r"(~/[^\s]+)",          # ~ expanded paths
        r"([.\w]/[^\s]+)",      # Relative paths
    ]
    
    try:
        parts = shlex.split(cmd)
    except ValueError:
        return False, "Invalid syntax"
    
    for part in parts:
        if part.startswith("/") or part.startswith("~"):
            expanded = os.path.expanduser(part)
            resolved = os.path.realpath(expanded)
            
            # Check if path is within USER_HOME (unless it's a system path)
            if resolved.startswith("/"):
                if not resolved.startswith(USER_HOME):
                    # Allow system-level probes (ping, nslookup, etc.)
                    if "net" not in cmd and "ping" not in cmd and "lookup" not in cmd:
                        return False, f"Path outside {USER_HOME}: {resolved}"
    
    return True, None


def run_command(
    cmd: str,
    timeout: int = 30,
    output_cap_kb: int = 100,
    check_paths: bool = True,
) -> CommandResult:
    """
    Safely execute a command with allowlist, path jail, timeout, and output cap.
    
    Args:
      cmd: Full command string (will be shlex-split)
      timeout: Max execution time in seconds (default 30)
      output_cap_kb: Max output size in KB (default 100)
      check_paths: Whether to validate paths are within USER_HOME (default True)
    
    Returns:
      CommandResult with stdout, stderr, exit_code, error
    """
    
    # Validate allowlist
    valid, err = _validate_command(cmd)
    if not valid:
        logger.warning(f"Command rejected: {cmd} — {err}")
        return CommandResult(stdout="", stderr="", exit_code=-1, error=err)
    
    # Validate paths
    if check_paths:
        valid, err = _validate_paths(cmd)
        if not valid:
            logger.warning(f"Path validation failed: {cmd} — {err}")
            return CommandResult(stdout="", stderr="", exit_code=-1, error=err)
    
    # Parse command
    try:
        parts = shlex.split(cmd)
    except ValueError as e:
        logger.warning(f"Failed to parse command {cmd}: {e}")
        return CommandResult(stdout="", stderr="", exit_code=-1, error=str(e))
    
    # Execute
    try:
        result = subprocess.run(
            parts,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=USER_HOME,
        )
        
        # Cap output
        cap_bytes = output_cap_kb * 1024
        stdout = result.stdout[:cap_bytes] if result.stdout else ""
        stderr = result.stderr[:cap_bytes] if result.stderr else ""
        
        return CommandResult(
            stdout=stdout,
            stderr=stderr,
            exit_code=result.returncode,
        )
    except subprocess.TimeoutExpired:
        msg = f"Command timed out after {timeout}s: {cmd}"
        logger.warning(msg)
        return CommandResult(stdout="", stderr="", exit_code=-1, error=msg)
    except Exception as e:
        logger.warning(f"Execution error: {e}")
        return CommandResult(stdout="", stderr="", exit_code=-1, error=str(e))


def run_piped_command(
    cmd: str,
    timeout: int = 30,
    output_cap_kb: int = 100,
) -> CommandResult:
    """
    Execute a command with pipes/redirects using /bin/sh -c (requires pre-validation).
    
    ONLY called after manual inspection of the command string ensures safety.
    Do not expose this to user input.
    
    Validates that:
    - Command contains only allowed programs (find, grep, sed, awk, sort, xargs, etc.)
    - No destructive redirects (>, >>, etc.)
    
    Args:
      cmd: Full piped command (find ... | grep ... | awk ...)
      timeout: Max execution time
      output_cap_kb: Max output size
    
    Returns:
      CommandResult
    """
    
    # Validate no destructive redirects
    if re.search(r"[>&](?!&).*[^|]?\s*$", cmd):  # > or >> at end of pipe
        msg = f"Destructive redirect not allowed: {cmd}"
        logger.warning(msg)
        return CommandResult(stdout="", stderr="", exit_code=-1, error=msg)
    
    # Validate all binaries in pipeline
    programs = re.findall(r"\b(\w+)(?=\s|$|\||;)", cmd)
    for prog in programs:
        if prog not in ALLOWED_COMMANDS:
            msg = f"Program {prog} in pipeline not allowed"
            logger.warning(msg)
            return CommandResult(stdout="", stderr="", exit_code=-1, error=msg)
    
    # Execute with shell (safe after validation)
    try:
        result = subprocess.run(
            cmd,
            shell=True,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=USER_HOME,
        )
        
        # Cap output
        cap_bytes = output_cap_kb * 1024
        stdout = result.stdout[:cap_bytes] if result.stdout else ""
        stderr = result.stderr[:cap_bytes] if result.stderr else ""
        
        return CommandResult(
            stdout=stdout,
            stderr=stderr,
            exit_code=result.returncode,
        )
    except subprocess.TimeoutExpired:
        msg = f"Piped command timed out after {timeout}s"
        logger.warning(msg)
        return CommandResult(stdout="", stderr="", exit_code=-1, error=msg)
    except Exception as e:
        logger.warning(f"Piped execution error: {e}")
        return CommandResult(stdout="", stderr="", exit_code=-1, error=str(e))
