"""TaskExecutor — executes structured plans using registered handlers.

Usage example::

    executor = TaskExecutor()
    executor.register_handler("search", lambda p: {"results": []})
    result = executor.execute({"task_id": "t1", "type": "search", "payload": {}})
"""

from __future__ import annotations

import logging
import time
import uuid
from typing import Any, Callable, Dict, Optional

log = logging.getLogger("TaskExecutor")


class TaskExecutor:
    """Executes task plans and stores results by task_id."""

    def __init__(self) -> None:
        self._handlers: Dict[str, Callable] = {}
        self._results: Dict[str, Dict[str, Any]] = {}

    # ── public API ──

    def register_handler(self, task_type: str, handler: Callable) -> None:
        """Register *handler* for tasks of *task_type*."""
        self._handlers[task_type] = handler
        log.debug("TaskExecutor: registered handler for %s", task_type)

    def execute(self, plan: Dict[str, Any]) -> Dict[str, Any]:
        """Execute *plan* and return result dict."""
        task_id = plan.get("task_id", str(uuid.uuid4()))
        task_type = plan.get("type", "default")
        handler = self._handlers.get(task_type)
        start = time.time()
        try:
            if handler:
                output = handler(plan.get("payload", plan))
            else:
                output = {"status": "no_handler", "task_type": task_type}
        except Exception as exc:
            log.warning("TaskExecutor: handler error for %s — %s", task_type, exc)
            output = {"error": str(exc)}
        result = {
            "task_id": task_id,
            "task_type": task_type,
            "output": output,
            "elapsed_ms": round((time.time() - start) * 1000, 2),
        }
        self._results[task_id] = result
        log.info("TaskExecutor: completed %s in %.1f ms", task_id, result["elapsed_ms"])
        return result

    def get_result(self, task_id: str) -> Optional[Dict[str, Any]]:
        """Return stored result for *task_id* or None."""
        return self._results.get(task_id)


if __name__ == "__main__":
    print('Running task_executor.py')
