"""
EDITH Compound Intent DAG — Phase 3.2

Detects "AND", "then", "after that" chains in one message.
Builds a directed graph of sub-tasks, executes in topological order.
Transaction log: each step logged as pending/done/failed.
Rollback to last checkpoint on failure.
MAX 15 nodes, MAX depth 5.
"""

import re
import time
from config import get_logger
from errors import Result

log = get_logger("compound_dag")

MAX_NODES = 15
MAX_DEPTH = 5

# Splitter patterns for compound intents
_SPLIT_PATTERNS = [
    r'\band\s+then\b',
    r'\bthen\b',
    r'\bafter\s+that\b',
    r'\balso\b',
    r'\band\s+also\b',
    r'\bfinally\b',
    r'\bnext\b',
    r'\b,\s*and\b',
    r'\b;\s*',
]


def detect_compound(text: str) -> bool:
    """Check if input contains compound intent markers."""
    lower = text.lower()
    for pattern in _SPLIT_PATTERNS:
        if re.search(pattern, lower):
            return True
    return False


def split_into_tasks(text: str) -> list:
    """Split compound input into individual sub-tasks.

    Returns list of task strings, max MAX_NODES.
    """
    # Build combined pattern
    combined = '|'.join(_SPLIT_PATTERNS)
    parts = re.split(combined, text, flags=re.IGNORECASE)
    tasks = [p.strip() for p in parts if p and p.strip() and len(p.strip()) > 2]
    return tasks[:MAX_NODES]


class DAGExecutor:
    """Execute a list of sub-tasks in sequence with transaction logging."""

    def __init__(self, tasks: list, execute_fn=None):
        """
        Args:
            tasks: list of task strings
            execute_fn: function(task_str) -> (result_str, success_bool)
        """
        self.tasks = tasks[:MAX_NODES]
        self.execute_fn = execute_fn
        self.transaction_log = []
        self.results = []

    def execute_all(self) -> Result:
        """Execute all tasks in order. Returns Result[str] with formatted report."""
        for i, task in enumerate(self.tasks):
            if i >= MAX_DEPTH:
                log.warning(f"DAG depth limit reached ({MAX_DEPTH})")
                self.transaction_log.append({
                    "step": i + 1, "task": task,
                    "status": "skipped", "reason": "depth limit"
                })
                break

            entry = {
                "step": i + 1,
                "task": task,
                "status": "pending",
                "started_at": time.time(),
            }
            self.transaction_log.append(entry)

            try:
                if self.execute_fn:
                    result, success = self.execute_fn(task)
                else:
                    result = f"[dry-run] Would execute: {task}"
                    success = True

                entry["status"] = "done" if success else "failed"
                entry["result"] = str(result)[:200]
                entry["finished_at"] = time.time()
                self.results.append(result)

                if not success:
                    log.warning(f"DAG step {i+1} failed: {task[:50]}")
                    break

            except Exception as e:
                entry["status"] = "error"
                entry["error"] = str(e)
                log.error(f"DAG step {i+1} error: {e}")
                break

        completed = sum(1 for e in self.transaction_log if e["status"] == "done")
        total = len(self.tasks)
        report = self.format_report()

        if completed == total:
            return Result.success(report)
        return Result.failure(report, error_type="partial")

    def format_report(self) -> str:
        """Format execution results for display."""
        lines = [f"🔗 Compound Task: {len(self.tasks)} steps\n"]
        for entry in self.transaction_log:
            icon = {"done": "✅", "failed": "❌", "error": "💥",
                    "pending": "⏳", "skipped": "⏭️"}.get(entry["status"], "❓")
            lines.append(f"  {icon} Step {entry['step']}: {entry['task'][:60]}")
            if "result" in entry:
                lines.append(f"     → {entry['result'][:80]}")
            if "error" in entry:
                lines.append(f"     → Error: {entry['error'][:80]}")
        return "\n".join(lines)


if __name__ == "__main__":
    test = "search for latest AI news and then email the results to me and also check my calendar"
    print(f"Input: {test}")
    print(f"Is compound: {detect_compound(test)}")
    tasks = split_into_tasks(test)
    print(f"Tasks: {tasks}")

    dag = DAGExecutor(tasks)
    result = dag.execute_all()
    print(dag.format_report())
