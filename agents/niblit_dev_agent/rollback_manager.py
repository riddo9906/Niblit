#!/usr/bin/env python3
"""Deterministic rollback snapshot infrastructure for governed execution."""

from __future__ import annotations

import hashlib
import time
from pathlib import Path
from typing import Any

from agents.niblit_dev_agent.telemetry_hooks import DevAgentTelemetryHooks


class RollbackManager:
    """Stores pre-execution snapshots and staged rollback plans."""

    def __init__(self, repo_root: str | Path, telemetry: DevAgentTelemetryHooks | None = None) -> None:
        self._repo_root = Path(repo_root).resolve()
        self._telemetry = telemetry
        self._snapshots: dict[str, dict[str, Any]] = {}
        self._plans: dict[str, dict[str, Any]] = {}

    def capture_pre_execution_snapshot(
        self,
        task_id: str,
        *,
        files: dict[str, dict[str, Any]],
        mutation_manifest: dict[str, Any],
    ) -> dict[str, Any]:
        """Capture deterministic pre-execution file state."""
        snapshot = {
            "task_id": task_id,
            "captured_at": time.time(),
            "files": files,
            "mutation_manifest": dict(mutation_manifest),
        }
        self._snapshots[task_id] = snapshot
        if self._telemetry:
            self._telemetry.increment("dev_agent_rollback_snapshots_total", 1)
        return snapshot

    def build_staged_rollback_plan(
        self,
        task_id: str,
        *,
        staged_changes: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Create a diff-aware rollback plan from staged changes + snapshot."""
        snapshot = self._snapshots.get(task_id, {})
        files = snapshot.get("files", {})
        restore_actions: list[dict[str, Any]] = []
        for change in staged_changes:
            relpath = str(change.get("relpath", ""))
            pre = files.get(relpath, {})
            restore_actions.append(
                {
                    "relpath": relpath,
                    "restore_exists": bool(pre.get("exists", False)),
                    "restore_content": pre.get("content"),
                    "restore_hash": pre.get("sha256"),
                    "protected_runtime_path": bool(change.get("protected", False)),
                }
            )
        plan = {
            "task_id": task_id,
            "generated_at": time.time(),
            "restore_actions": restore_actions,
            "deterministic": True,
            "review_required": True,
        }
        self._plans[task_id] = plan
        return plan

    def build_diff_aware_restoration(
        self,
        task_id: str,
        *,
        post_change_hashes: dict[str, str | None],
    ) -> dict[str, Any]:
        """Annotate rollback plan with hash drift between pre/post execution."""
        snapshot = self._snapshots.get(task_id, {})
        files = snapshot.get("files", {})
        drift = {}
        for relpath, post_hash in post_change_hashes.items():
            drift[relpath] = {
                "before": files.get(relpath, {}).get("sha256"),
                "after": post_hash,
                "changed": files.get(relpath, {}).get("sha256") != post_hash,
            }
        return {
            "task_id": task_id,
            "drift": drift,
            "diff_aware": True,
        }

    def get_snapshot(self, task_id: str) -> dict[str, Any] | None:
        return self._snapshots.get(task_id)

    def get_plan(self, task_id: str) -> dict[str, Any] | None:
        return self._plans.get(task_id)

    @staticmethod
    def hash_content(content: str | None) -> str | None:
        if content is None:
            return None
        return hashlib.sha256(content.encode("utf-8")).hexdigest()
