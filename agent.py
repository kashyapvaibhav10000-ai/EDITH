"""
EDITH Agent — Item 4: State Machine Execution Loop

State machine: PLANNING → EXECUTING → VALIDATING → REPLANNING → DONE/FAILED
SQLite persistence: every state transition logged to agent_runs table.

Preserved (used by intent_dispatch.py execute_pending_action):
  plan_task(), get_command(), is_dangerous(), compute_confidence()

New:
  AgentRunner — manages state transitions + persistence
  start_agent_task() — non-blocking entry point for web server
  get_task_status() — poll task state by task_id
  resume_agent_task() — HITL YES/NO gate for web server flow
"""

import subprocess
import asyncio
import os
import re
import shlex
import shutil
import sqlite3
import uuid
import datetime
import json
import threading
from enum import Enum
from dataclasses import dataclass, field
from typing import List, Optional

from config import DANGEROUS_PATTERNS, get_logger, EDITH_PATH
from errors import Result
from event_bus import bus, Topic
from smart_router import smart_call

log = get_logger("agent")

_AGENT_DB = os.path.join(EDITH_PATH, "agent_runs.db")
_db_lock = threading.Lock()
_STOP_AGENT = threading.Event()


def interrupt_agent():
    """Signal the running agent to stop at the next step boundary."""
    _STOP_AGENT.set()


def clear_interrupt():
    """Clear the interrupt signal (call before starting a new task)."""
    _STOP_AGENT.clear()


# ──────────────────────────────────────────────
# State Machine
# ──────────────────────────────────────────────
class AgentState(Enum):
    PLANNING   = "planning"
    EXECUTING  = "executing"
    VALIDATING = "validating"
    REPLANNING = "replanning"
    DONE       = "done"
    FAILED     = "failed"


@dataclass
class AgentStep:
    description: str
    command: str = ""
    confidence: float = 0.0
    dangerous: bool = False
    status: str = "pending"   # pending | ok | blocked | error | skipped
    output: str = ""
    error: str = ""


@dataclass
class AgentRun:
    task_id: str
    task: str
    state: AgentState
    steps: List[AgentStep] = field(default_factory=list)
    current_step: int = 0
    replan_count: int = 0
    created_at: str = ""
    updated_at: str = ""
    error: str = ""


# ──────────────────────────────────────────────
# SQLite Persistence
# ──────────────────────────────────────────────
def _get_db() -> sqlite3.Connection:
    conn = sqlite3.connect(_AGENT_DB)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("""CREATE TABLE IF NOT EXISTS agent_runs (
        task_id TEXT PRIMARY KEY,
        task TEXT NOT NULL,
        state TEXT NOT NULL,
        steps_json TEXT DEFAULT '[]',
        current_step INTEGER DEFAULT 0,
        replan_count INTEGER DEFAULT 0,
        created_at TEXT,
        updated_at TEXT,
        error TEXT DEFAULT ''
    )""")
    conn.commit()
    return conn


def _persist(run: AgentRun):
    now = datetime.datetime.now().isoformat()
    run.updated_at = now
    steps_json = json.dumps([s.__dict__ for s in run.steps])
    with _db_lock:
        conn = _get_db()
        conn.execute("""INSERT OR REPLACE INTO agent_runs
            (task_id, task, state, steps_json, current_step, replan_count, created_at, updated_at, error)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (run.task_id, run.task, run.state.value, steps_json,
             run.current_step, run.replan_count,
             run.created_at or now, now, run.error)
        )
        conn.commit()
        conn.close()


def _load_run(task_id: str) -> Optional[AgentRun]:
    with _db_lock:
        conn = _get_db()
        row = conn.execute(
            "SELECT task_id, task, state, steps_json, current_step, replan_count, created_at, updated_at, error "
            "FROM agent_runs WHERE task_id = ?", (task_id,)
        ).fetchone()
        conn.close()
    if not row:
        return None
    steps = [AgentStep(**s) for s in json.loads(row[3])]
    return AgentRun(
        task_id=row[0], task=row[1], state=AgentState(row[2]),
        steps=steps, current_step=row[4], replan_count=row[5],
        created_at=row[6], updated_at=row[7], error=row[8]
    )


# ──────────────────────────────────────────────
# LLM helpers
# ──────────────────────────────────────────────
def _llm(prompt, intent="reason"):
    return smart_call(prompt, intent=intent)

def _llm_gen(prompt, intent="reason"):
    return smart_call(prompt, intent=intent)


# ──────────────────────────────────────────────
# Core helpers (preserved for intent_dispatch.py)
# ──────────────────────────────────────────────
def is_dangerous(cmd):
    """Check if a command contains any dangerous patterns.
    
    Uses regex-based normalization to catch whitespace obfuscation,
    command substitution, variable expansion, and semicolon chaining.
    """
    cmd_lower = cmd.lower().strip()
    # Normalize ALL whitespace variants (double spaces, tabs, newlines) — not just single space
    cmd_nospace = re.sub(r'\s+', '', cmd_lower)
    for pattern in DANGEROUS_PATTERNS:
        pattern_nospace = re.sub(r'\s+', '', pattern.lower())
        if pattern.lower() in cmd_lower or pattern_nospace in cmd_nospace:
            return True
    if "|" in cmd and any(d in cmd_lower for d in ["rm", "dd", "mkfs", "shred", "wipefs"]):
        return True
    if ">" in cmd and any(f in cmd_lower for f in ["/etc/", "/dev/", "/boot/", "/usr/", "/bin/", "/sbin/"]):
        return True
    # Detect semicolon command chaining — check each sub-statement recursively
    if ";" in cmd:
        for stmt in cmd.split(";"):
            stmt = stmt.strip()
            if stmt and is_dangerous(stmt):
                return True
    _DANGER_REGEX = [
        r'\$\{[^}]+\}',                          # variable expansion ${VAR}
        r'`[^`]+`',                               # backtick execution
        r'\bnc\s+-\w*e\b|\bbash\s+-i\b|/dev/tcp', # reverse shells
        r'curl\s+\S+.*\|\s*(ba)?sh|wget\s+\S+.*\|\s*(ba)?sh', # remote exec
    ]
    for pattern in _DANGER_REGEX:
        if re.search(pattern, cmd):
            return True
    return False


def _sanitize_command(cmd: str) -> str:
    forbidden = ["&", "|", ";", ">", "<", "`", "$(", ")"]
    cleaned = cmd
    for char in forbidden:
        cleaned = cleaned.replace(char, "")
    return cleaned.strip()


def _get_sandboxed_command(cmd_list: list) -> list:
    if shutil.which("firejail"):
        return ["firejail", "--private-tmp", "--net=none"] + cmd_list
    log.warning("No firejail found — running as user")
    return cmd_list


def compute_confidence(cmd: str, step: str) -> float:
    score = 0.5
    if is_dangerous(cmd):
        score -= 0.5
    if "/home/" in cmd or cmd.startswith("/"):
        score += 0.2
    safe_cmds = ["ls", "cat", "echo", "pwd", "whoami", "date", "head", "tail",
                 "wc", "grep", "find", "du", "df", "mkdir", "cp", "touch"]
    first_word = cmd.split()[0] if cmd.split() else ""
    if first_word in safe_cmds:
        score += 0.3
    if "\n" not in cmd and ";" not in cmd:
        score += 0.1
    step_words = set(step.lower().split())
    cmd_words = set(cmd.lower().split())
    if len(step_words & cmd_words) >= 2:
        score += 0.1
    return round(max(0.0, min(1.0, score)), 2)


def _load_coding_style() -> str:
    """Load Vaibhav's coding style personality if available."""
    try:
        from config import CODING_PERSONALITY_TXT
        if os.path.exists(CODING_PERSONALITY_TXT):
            with open(CODING_PERSONALITY_TXT) as _fh:
                return _fh.read() + "\n\n"
    except Exception:
        pass
    return ""


def plan_task(task) -> str:
    style_prefix = _load_coding_style()
    prompt = f"""{style_prefix}You are EDITH, a Linux assistant on Manjaro.
Break the task into max 3 steps. Use only plain text, no markdown, no backticks, no code blocks.
Use absolute paths like 
Never include steps like "open terminal", "navigate to directory", or "cd" — just do the actual task directly.
For bulk operations (create N files/folders, rename N items, etc.), use ONE step — do NOT list individual items.

Task: {task}

Reply ONLY like this:
1. First action
2. Second action
3. Third action"""
    return _llm(prompt, intent="reason")


def get_command(step) -> str:
    prompt = f"""You are EDITH on Linux Manjaro.
Convert this step into a single bash command.
Rules:
- Absolute paths only, starting with 
- No cd commands alone
- No markdown, no backticks, no code blocks
- Reply with ONLY the raw bash command, nothing else
- For bulk ops (create N folders/files), use bash brace expansion: mkdir -p /path/{{1..N}} or mkdir -p /path/name_{{1..N}}
- Never loop with individual commands when brace expansion works

Step: {step}"""
    cmd = _llm(prompt, intent="reason")
# ──────────────────────────────────────────────
# AgentRunner — state machine
# ──────────────────────────────────────────────
class AgentRunner:
    """Manages a single agent task through its state machine lifecycle."""

    MAX_REPLANS = 3

    def __init__(self, task: str, task_id: str = None):
        self.run = AgentRun(
            task_id=task_id or str(uuid.uuid4())[:8],
            task=task,
            state=AgentState.PLANNING,
            created_at=datetime.datetime.now().isoformat(),
        )
        _persist(self.run)

    def _transition(self, new_state: AgentState, error: str = ""):
        old = self.run.state
        self.run.state = new_state
        self.run.error = error
        log.info(f"Agent [{self.run.task_id}] {old.value} → {new_state.value}")
        _persist(self.run)

    def plan(self) -> Result:
        """PLANNING: generate steps from task description."""
        try:
            raw_plan = plan_task(self.run.task)
            steps = []
            for line in raw_plan.split("\n"):
                line = line.strip()
                if line and line[0].isdigit() and "." in line:
                    desc = line.split(".", 1)[-1].strip()
                    if desc:
                        cmd = get_command(desc)
                        steps.append(AgentStep(
                            description=desc,
                            command=_sanitize_command(cmd),
                            confidence=compute_confidence(cmd, desc),
                            dangerous=is_dangerous(cmd),
                        ))
            if not steps:
                self._transition(AgentState.FAILED, "Planning produced no valid steps")
                return Result.failure("Planning produced no valid steps", error_type="agent")

            self.run.steps = steps
            self.run.current_step = 0
            self._transition(AgentState.EXECUTING)
            return Result.success(raw_plan)
        except Exception as e:
            self._transition(AgentState.FAILED, str(e))
            return Result.from_exception(e)

    async def execute_next(self) -> Result:
        """EXECUTING: run the next pending step. Returns Result with step output."""
        if self.run.state not in (AgentState.EXECUTING, AgentState.REPLANNING):
            return Result.failure(f"Cannot execute in state {self.run.state.value}", error_type="agent")

        idx = self.run.current_step
        if idx >= len(self.run.steps):
            self._transition(AgentState.VALIDATING)
            return Result.success("All steps executed — validating")

        step = self.run.steps[idx]

        if step.dangerous:
            step.status = "blocked"
            step.error = "Dangerous command blocked"
            self.run.current_step += 1
            _persist(self.run)
            return Result.success(f"⛔ Step {idx+1} blocked (dangerous): `{step.command}`")

        _MAX_OUTPUT = 1024 * 1024  # 1MB stdout cap
        try:
            cmd_parts = _get_sandboxed_command(["bash", "-c", step.command])
            proc = await asyncio.create_subprocess_exec(
                *cmd_parts,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=os.path.expanduser("~"),
            )
            try:
                stdout_chunks, stderr_chunks, total = [], [], 0
                async for chunk in proc.stdout:
                    total += len(chunk)
                    if total > _MAX_OUTPUT:
                        proc.kill()
                        await proc.wait()
                        step.status = "error"
                        step.error = "Output exceeded 1MB limit — process killed"
                        self.run.current_step += 1
                        _persist(self.run)
                        return Result.failure(f"Step {idx+1} error: {step.error}", error_type="agent")
                    stdout_chunks.append(chunk)
                stderr_data = await asyncio.wait_for(proc.stderr.read(_MAX_OUTPUT), timeout=120)
                await asyncio.wait_for(proc.wait(), timeout=120)
            except asyncio.TimeoutError:
                proc.kill()
                await proc.wait()
                step.status = "error"
                step.error = "Timeout (120s)"
                self.run.current_step += 1
                _persist(self.run)
                return Result.failure(f"Step {idx+1} error: {step.error}", error_type="agent")

            stdout_data = b"".join(stdout_chunks).decode(errors="replace")
            stderr_str = stderr_data.decode(errors="replace")
            step.output = (stdout_data or stderr_str or "").strip()[:500]
            step.status = "ok" if proc.returncode == 0 else "error"
            if proc.returncode != 0:
                step.error = step.output
        except Exception as e:
            step.status = "error"
            step.error = str(e)

        self.run.current_step += 1
        _persist(self.run)

        if step.status == "ok":
            return Result.success(f"✅ Step {idx+1}: {step.description[:50]}\n{step.output}")
        return Result.failure(f"Step {idx+1} error: {step.error}", error_type="agent")

    async def execute_all(self) -> Result:
        """Run all steps in sequence. Returns summary Result."""
        outputs = []
        while self.run.current_step < len(self.run.steps):
            if _STOP_AGENT.is_set():
                _STOP_AGENT.clear()
                self._transition(AgentState.FAILED, "Interrupted by user")
                return Result.failure("Agent interrupted by user", error_type="interrupted")
            r = await self.execute_next()
            outputs.append(r.value if r.ok else r.error)
        self._transition(AgentState.VALIDATING)
        return self.validate()

    def validate(self) -> Result:
        """VALIDATING: check results, transition to DONE or REPLANNING."""
        if self.run.state != AgentState.VALIDATING:
            return Result.failure(f"Cannot validate in state {self.run.state.value}", error_type="agent")

        failed = [s for s in self.run.steps if s.status == "error"]
        blocked = [s for s in self.run.steps if s.status == "blocked"]
        ok_steps = [s for s in self.run.steps if s.status == "ok"]

        if not failed:
            self._transition(AgentState.DONE)
            summary = self._format_summary()
            return Result.success(summary)

        if self.run.replan_count < self.MAX_REPLANS:
            self.run.replan_count += 1
            self._transition(AgentState.REPLANNING)
            return Result.success(f"⚠️ {len(failed)} step(s) failed — replanning (attempt {self.run.replan_count}/{self.MAX_REPLANS})")

        self._transition(AgentState.FAILED, f"{len(failed)} step(s) failed after {self.run.replan_count} replan(s)")
        return Result.failure(self._format_summary(), error_type="agent")

    def replan(self) -> Result:
        """REPLANNING: retry failed steps with new commands."""
        if self.run.state != AgentState.REPLANNING:
            return Result.failure(f"Cannot replan in state {self.run.state.value}", error_type="agent")

        for step in self.run.steps:
            if step.status == "error":
                try:
                    prompt = (
                        f"Previous command failed: `{step.command}`\n"
                        f"Error: {step.error}\n"
                        f"Step goal: {step.description}\n"
                        f"Provide an alternative single bash command to achieve the same goal."
                    )
                    new_cmd = _llm(prompt, intent="reason")
                    new_cmd = new_cmd.replace("```", "").strip().split("\n")[0]
                    step.command = _sanitize_command(new_cmd)
                    step.confidence = compute_confidence(step.command, step.description)
                    step.dangerous = is_dangerous(step.command)
                    step.status = "pending"
                    step.output = ""
                    step.error = ""
                except Exception as e:
                    log.warning(f"Replan failed for step '{step.description}': {e}")

        # Reset execution pointer to first failed step
        self.run.current_step = next(
            (i for i, s in enumerate(self.run.steps) if s.status == "pending"), 0
        )
        self._transition(AgentState.EXECUTING)
        _persist(self.run)
        return Result.success(f"Replanned — retrying from step {self.run.current_step + 1}")

    def _format_summary(self) -> str:
        lines = [f"🤖 Agent Run: {self.run.task}\n", f"State: {self.run.state.value.upper()}\n"]
        for i, s in enumerate(self.run.steps, 1):
            icon = {"ok": "✅", "blocked": "⛔", "error": "❌", "skipped": "⏭️", "pending": "⏳"}.get(s.status, "?")
            lines.append(f"{icon} Step {i}: {s.description[:60]}")
            if s.output:
                lines.append(f"   → {s.output[:100]}")
            if s.error:
                lines.append(f"   ✗ {s.error[:80]}")
        return "\n".join(lines)


# ──────────────────────────────────────────────
# Web-server-safe entry points
# ──────────────────────────────────────────────
def start_agent_task(task: str) -> Result:
    """Plan a task and return task_id + plan string. Non-blocking."""
    try:
        runner = AgentRunner(task)
        r = runner.plan()
        if not r.ok:
            return r
        return Result.success({
            "task_id": runner.run.task_id,
            "plan": r.value,
            "steps": [s.__dict__ for s in runner.run.steps],
            "state": runner.run.state.value,
        })
    except Exception as e:
        return Result.from_exception(e)


def get_task_status(task_id: str) -> Result:
    """Get current state of a task by ID."""
    run = _load_run(task_id)
    if not run:
        return Result.failure(f"Task {task_id} not found", error_type="not_found")
    return Result.success({
        "task_id": run.task_id,
        "task": run.task,
        "state": run.state.value,
        "current_step": run.current_step,
        "steps": [s.__dict__ for s in run.steps],
        "error": run.error,
    })


def execute_agent_task(task_id: str) -> Result:
    """Start execution in background thread. Returns task_id immediately; caller polls get_task_status()."""
    run = _load_run(task_id)
    if not run:
        return Result.failure(f"Task {task_id} not found", error_type="not_found")
    if run.state not in (AgentState.EXECUTING, AgentState.REPLANNING):
        return Result.failure(f"Task not in executable state (state={run.state.value})", error_type="agent")

    runner = AgentRunner.__new__(AgentRunner)
    runner.run = run

    def _run():
        try:
            result = asyncio.run(runner.execute_all())
            while runner.run.state == AgentState.REPLANNING:
                replan_result = runner.replan()
                if not replan_result.ok:
                    result = replan_result
                    break
                result = asyncio.run(runner.execute_all())
            if result.ok:
                bus.publish(Topic.AGENT_DONE, {"task_id": task_id, "summary": str(result.value)[:200]})
            else:
                bus.publish(Topic.AGENT_ERROR, {"task_id": task_id, "error": result.error})
        except Exception as e:
            log.error(f"Agent thread [{task_id}] failed: {e}")
            bus.publish(Topic.AGENT_ERROR, {"task_id": task_id, "error": str(e)})

    threading.Thread(target=_run, daemon=True, name=f"agent-{task_id}").start()
    return Result.success({"task_id": task_id, "state": "executing"})


# ──────────────────────────────────────────────
# Dry-run (preserved from Phase 4.8)
# ──────────────────────────────────────────────
def dry_run_agent(task: str) -> Result:
    log.info(f"Agent dry-run: {task}")
    plan = plan_task(task)
    steps = []
    for line in plan.split("\n"):
        line = line.strip()
        if line and line[0].isdigit() and "." in line:
            step = line.split(".", 1)[-1].strip()
            if step:
                steps.append(step)
    results = []
    for step in steps:
        cmd = get_command(step)
        confidence = compute_confidence(cmd, step)
        dangerous = is_dangerous(cmd)
        results.append({
            "step": step, "command": cmd, "confidence": confidence,
            "dangerous": dangerous,
            "status": "blocked" if dangerous else "ready",
        })
    return Result.success({
        "task": task, "plan": plan, "steps": results,
        "avg_confidence": round(sum(r["confidence"] for r in results) / max(len(results), 1), 2),
        "any_dangerous": any(r["dangerous"] for r in results),
        "dry_run": True,
    })


def format_dry_run(result) -> str:
    data = result.value if isinstance(result, Result) else result
    lines = [f"🔍 Agent Dry-Run: {data['task']}\n"]
    lines.append(f"Plan:\n{data['plan']}\n")
    for i, step in enumerate(data["steps"], 1):
        icon = "⛔" if step["dangerous"] else "✅"
        conf = f"({step['confidence']:.0%})"
        lines.append(f"  {icon} Step {i}: {step['step'][:60]}")
        lines.append(f"     → {step['command']}")
        lines.append(f"     Confidence: {conf} | Status: {step['status']}")
    lines.append(f"\nOverall Confidence: {data['avg_confidence']:.0%}")
    if data["any_dangerous"]:
        lines.append("⚠️ Some steps were flagged as DANGEROUS")
    return "\n".join(lines)


# ──────────────────────────────────────────────
# CLI (preserved, terminal-only)
# ──────────────────────────────────────────────
def run_agent(task):
    print(f"\nEDITH Agent - Task: {task}\n")
    log.info(f"Agent task started: {task}")
    runner = AgentRunner(task)
    print("Planning...")
    r = runner.plan()
    if not r.ok:
        print(f"Planning failed: {r.error}")
        return
    print(f"\nPlan:\n{r.value}")
    print("\nProceed? [Y/N]: ", end="", flush=True)
    if input().strip().lower() != "y":
        print("Cancelled.")
        return
    result = asyncio.run(runner.execute_all())
    print(f"\n{result.value if result.ok else result.error}")


if __name__ == "__main__":
    task = input("What task should EDITH complete? ")
    run_agent(task)
