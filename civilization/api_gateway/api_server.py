"""APIServer — front-door request handler for the civilisation API gateway.

Usage example::

    server = APIServer(auth, task_api, knowledge_api)
    resp = server.handle("/tasks/submit", "POST", {"Authorization": "Bearer ..."}, {})
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List

log = logging.getLogger("CivilizationAPIServer")


class APIServer:
    """Handles HTTP-like requests for the civilisation API.

    Args:
        auth: Authentication instance.
        task_api: TaskAPI instance.
        knowledge_api: KnowledgeAPI instance.
    """

    def __init__(self, auth: Any, task_api: Any, knowledge_api: Any) -> None:
        self._auth = auth
        self._tasks = task_api
        self._knowledge = knowledge_api
        self._stats: Dict[str, int] = {
            "total": 0, "success": 0, "auth_fail": 0, "not_found": 0,
        }

    # ── public API ──

    def handle(
        self,
        path: str,
        method: str,
        headers: Dict[str, str],
        body: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Route *path*/*method* to the appropriate handler."""
        self._stats["total"] += 1
        token = (headers.get("Authorization") or "").removeprefix("Bearer ").strip()
        if token and not self._auth.validate_token(token):
            self._stats["auth_fail"] += 1
            return {"status_code": 401, "body": {"error": "invalid_token"}}
        result = self._dispatch(path, method, body)
        self._stats["success"] += 1
        return result

    def get_routes(self) -> List[str]:
        """Return registered route paths."""
        return [
            "POST /tasks/goal",
            "POST /tasks/submit",
            "GET /tasks/{task_id}",
            "GET /tasks",
            "POST /knowledge/query",
            "POST /knowledge/submit",
            "GET /knowledge/{key}",
        ]

    def get_stats(self) -> Dict[str, Any]:
        """Return request statistics."""
        return dict(self._stats)

    # ── internals ──

    def _dispatch(self, path: str, method: str, body: Dict[str, Any]) -> Dict[str, Any]:
        if path == "/tasks/goal" and method == "POST":
            return {"status_code": 200, "body": self._tasks.submit_goal(body.get("goal", ""))}
        if path == "/tasks/submit" and method == "POST":
            return {"status_code": 200, "body": self._tasks.submit_task(
                body.get("task_type", "generic"), body.get("payload", {}))}
        if path.startswith("/tasks/") and method == "GET":
            task_id = path.removeprefix("/tasks/")
            return {"status_code": 200, "body": self._tasks.get_task_status(task_id)}
        if path == "/tasks" and method == "GET":
            return {"status_code": 200, "body": {"tasks": self._tasks.list_tasks()}}
        if path == "/knowledge/query" and method == "POST":
            return {"status_code": 200, "body": {"results": self._knowledge.query(body.get("q", ""))}}
        if path == "/knowledge/submit" and method == "POST":
            return {"status_code": 200, "body": self._knowledge.submit_knowledge(
                body.get("content", ""), body.get("tags"))}
        if path.startswith("/knowledge/") and method == "GET":
            key = path.removeprefix("/knowledge/")
            result = self._knowledge.get_knowledge(key)
            if result is None:
                self._stats["not_found"] += 1
                return {"status_code": 404, "body": {"error": "not_found"}}
            return {"status_code": 200, "body": result}
        self._stats["not_found"] += 1
        return {"status_code": 404, "body": {"error": "not_found", "path": path}}
