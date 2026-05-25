#!/usr/bin/env python3
"""Sandboxed filesystem mutation guard for NiblitDevAgent governed tasks."""

from __future__ import annotations

import difflib
import hashlib
import time
from pathlib import Path
from typing import Any

from agents.niblit_dev_agent.mutation_manifest import build_manifest
from agents.niblit_dev_agent.task_contracts import DevTaskContract
from agents.niblit_dev_agent.telemetry_hooks import DevAgentTelemetryHooks

# Runtime-sensitive paths that must NEVER be written without explicit approval
_PROTECTED_PATHS: frozenset[str] = frozenset({
    "niblit_core.py",
    "core/runtime_manager.py",
    "core/event_bus.py",
    "core/task_queue.py",
    "core/orchestrator.py",
    "modules/runtime_router_v2.py",
    "modules/local_brain.py",
    "modules/llm_provider_manager.py",
    "shared/governance_contract",
    "Dockerfile",
    "fly.toml",
    "vercel.json",
    "render.yaml",
    ".env",
})


class FilesystemGuardError(RuntimeError):
    """Raised when a guarded write is attempted on a protected path."""


class FilesystemGuard:
    """Tracks, validates, stages, and applies controlled filesystem mutations."""

    def __init__(
        self,
        repo_root: str | Path,
        telemetry: DevAgentTelemetryHooks | None = None,
    ) -> None:
        self._repo_root = Path(repo_root).resolve()
        self._telemetry = telemetry
        self._change_log: list[dict[str, Any]] = []
        self._staged_plans: dict[str, dict[str, Any]] = {}

    # ── Path resolution / validation ─────────────────────────────────────────

    def _abs(self, relpath: str) -> Path:
        target = (self._repo_root / relpath).resolve()
        try:
            target.relative_to(self._repo_root)
        except ValueError as exc:
            raise FilesystemGuardError(
                f"Path traversal attempt blocked: {relpath!r}"
            ) from exc
        return target

    def _is_protected(self, relpath: str) -> bool:
        candidate = Path(relpath)
        for protected in _PROTECTED_PATHS:
            p = Path(protected)
            if candidate == p:
                return True
            try:
                candidate.relative_to(p)
                return True
            except ValueError:
                continue
        return False

    def _validate_path(self, relpath: str, force: bool = False) -> None:
        if self._is_protected(relpath) and not force:
            raise FilesystemGuardError(
                f"Write blocked: '{relpath}' is a protected runtime-critical path. "
                "Pass force=True only with governance approval."
            )

    @staticmethod
    def _file_hash(path: Path) -> str | None:
        if not path.exists():
            return None
        try:
            data = path.read_bytes()
            return hashlib.sha256(data).hexdigest()
        except OSError:
            return None

    def _read_text(self, relpath: str) -> str | None:
        path = self._abs(relpath)
        if not path.exists():
            return None
        try:
            return path.read_text(encoding="utf-8")
        except OSError:
            return None

    # ── Preview / staging operations ──────────────────────────────────────────

    def preview_write(
        self,
        relpath: str,
        content: str | bytes,
        *,
        encoding: str = "utf-8",
    ) -> dict[str, Any]:
        """Return a diff preview without writing."""
        abs_path = self._abs(relpath)
        before = self._read_text(relpath) or ""
        after = content.decode(encoding) if isinstance(content, bytes) else content
        diff = "\n".join(
            difflib.unified_diff(
                before.splitlines(),
                after.splitlines(),
                fromfile=f"a/{relpath}",
                tofile=f"b/{relpath}",
                lineterm="",
            )
        )
        return {
            "operation": "write",
            "relpath": relpath,
            "exists": abs_path.exists(),
            "protected": self._is_protected(relpath),
            "pre_hash": self._file_hash(abs_path),
            "post_hash": hashlib.sha256(after.encode(encoding)).hexdigest(),
            "diff_preview": diff,
        }

    def preview_delete(self, relpath: str) -> dict[str, Any]:
        """Return delete preview without mutating the filesystem."""
        abs_path = self._abs(relpath)
        return {
            "operation": "delete",
            "relpath": relpath,
            "exists": abs_path.exists(),
            "protected": self._is_protected(relpath),
            "pre_hash": self._file_hash(abs_path),
            "post_hash": None,
            "diff_preview": f"--- a/{relpath}\n+++ /dev/null",
        }

    def stage_write(
        self,
        plan_id: str,
        relpath: str,
        content: str | bytes,
        *,
        encoding: str = "utf-8",
    ) -> dict[str, Any]:
        """Stage a write mutation for explicit approval."""
        preview = self.preview_write(relpath, content, encoding=encoding)
        self._staged_plans.setdefault(plan_id, {"created_at": time.time(), "changes": []})
        staged = {
            **preview,
            "content": content.decode(encoding) if isinstance(content, bytes) else content,
            "encoding": encoding,
        }
        self._staged_plans[plan_id]["changes"].append(staged)
        if self._telemetry:
            self._telemetry.increment("dev_agent_fs_staged_writes_total", 1)
        return staged

    def stage_delete(self, plan_id: str, relpath: str) -> dict[str, Any]:
        """Stage a delete mutation for explicit approval."""
        preview = self.preview_delete(relpath)
        self._staged_plans.setdefault(plan_id, {"created_at": time.time(), "changes": []})
        self._staged_plans[plan_id]["changes"].append(preview)
        if self._telemetry:
            self._telemetry.increment("dev_agent_fs_staged_deletes_total", 1)
        return preview

    def staged_plan(self, plan_id: str) -> dict[str, Any]:
        return dict(self._staged_plans.get(plan_id, {"created_at": None, "changes": []}))

    def mutation_manifest(
        self,
        *,
        plan_id: str,
        contract: DevTaskContract,
        affected_runtime_systems: list[str] | None = None,
        restart_required: bool = False,
    ) -> dict[str, Any]:
        """Build machine-readable mutation metadata for the staged plan."""
        plan = self.staged_plan(plan_id)
        affected_files = [str(c.get("relpath", "")) for c in plan.get("changes", [])]
        manifest = build_manifest(
            contract,
            affected_files=affected_files,
            affected_runtime_systems=affected_runtime_systems or [],
            restart_required=restart_required,
            metadata={"plan_id": plan_id},
        )
        return manifest.to_dict()

    def validate_execution_scope(self, plan_id: str, allowed_modules: list[str]) -> dict[str, Any]:
        """Ensure staged paths are constrained to planned/approved module scope."""
        plan = self.staged_plan(plan_id)
        if not allowed_modules:
            return {"valid": False, "reason": "empty_allowed_modules", "invalid_paths": []}
        invalid_paths = []
        for change in plan.get("changes", []):
            relpath = str(change.get("relpath", ""))
            if not any(relpath == m or relpath.startswith(m.rstrip("/") + "/") for m in allowed_modules):
                invalid_paths.append(relpath)
        return {
            "valid": not invalid_paths,
            "invalid_paths": invalid_paths,
            "allowed_modules": list(allowed_modules),
        }

    def prepare_rollback_snapshot(self, plan_id: str) -> dict[str, Any]:
        """Capture pre-execution snapshot data for all staged paths."""
        plan = self.staged_plan(plan_id)
        files: dict[str, dict[str, Any]] = {}
        for change in plan.get("changes", []):
            relpath = str(change.get("relpath", ""))
            content = self._read_text(relpath)
            files[relpath] = {
                "exists": content is not None,
                "content": content,
                "sha256": None if content is None else hashlib.sha256(content.encode("utf-8")).hexdigest(),
                "protected": self._is_protected(relpath),
            }
        return {"plan_id": plan_id, "files": files}

    def execute_staged_plan(self, plan_id: str, *, force: bool = False) -> dict[str, Any]:
        """Apply staged mutations after external approval workflow has passed."""
        plan = self.staged_plan(plan_id)
        applied_changes = []
        for change in plan.get("changes", []):
            op = change.get("operation")
            relpath = str(change.get("relpath", ""))
            if op == "write":
                applied_changes.append(
                    self.write_file(
                        relpath,
                        str(change.get("content", "")),
                        encoding=str(change.get("encoding", "utf-8")),
                        force=force,
                    )
                )
            elif op == "delete":
                applied_changes.append(self.delete_file(relpath, force=force))
        return {"plan_id": plan_id, "applied_changes": applied_changes}

    # ── Immediate mutation operations ──────────────────────────────────────────

    def write_file(
        self,
        relpath: str,
        content: str | bytes,
        *,
        encoding: str = "utf-8",
        force: bool = False,
    ) -> dict[str, Any]:
        self._validate_path(relpath, force=force)
        abs_path = self._abs(relpath)
        pre_hash = self._file_hash(abs_path)
        existed = abs_path.exists()

        abs_path.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(content, bytes):
            abs_path.write_bytes(content)
        else:
            abs_path.write_text(content, encoding=encoding)

        post_hash = self._file_hash(abs_path)
        record = {
            "operation": "write",
            "relpath": relpath,
            "existed_before": existed,
            "pre_hash": pre_hash,
            "post_hash": post_hash,
            "protected": self._is_protected(relpath),
            "forced": force,
        }
        self._change_log.append(record)
        if self._telemetry:
            self._telemetry.increment("dev_agent_fs_writes_total", 1)
        return record

    def delete_file(
        self,
        relpath: str,
        *,
        force: bool = False,
    ) -> dict[str, Any]:
        self._validate_path(relpath, force=force)
        abs_path = self._abs(relpath)
        pre_hash = self._file_hash(abs_path)
        existed = abs_path.exists()

        if existed:
            abs_path.unlink()

        record = {
            "operation": "delete",
            "relpath": relpath,
            "existed_before": existed,
            "pre_hash": pre_hash,
            "post_hash": None,
            "protected": self._is_protected(relpath),
            "forced": force,
        }
        self._change_log.append(record)
        if self._telemetry:
            self._telemetry.increment("dev_agent_fs_deletes_total", 1)
        return record

    # ── Inspection / rollback ─────────────────────────────────────────────────

    def changed_files(self) -> list[str]:
        return [r["relpath"] for r in self._change_log]

    def change_log(self) -> list[dict[str, Any]]:
        return [dict(r) for r in self._change_log]

    def rollback_metadata(self) -> dict[str, Any]:
        return {
            "changes": self.change_log(),
            "total_changes": len(self._change_log),
            "affected_paths": self.changed_files(),
            "protected_touched": [
                r["relpath"] for r in self._change_log if r["protected"]
            ],
        }

    def clear_log(self) -> None:
        self._change_log.clear()

    def validate_path(self, relpath: str) -> dict[str, Any]:
        return {
            "relpath": relpath,
            "is_protected": self._is_protected(relpath),
            "exists": (self._repo_root / relpath).exists(),
            "absolute": str(self._abs(relpath)),
        }
