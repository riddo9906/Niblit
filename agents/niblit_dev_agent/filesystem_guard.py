#!/usr/bin/env python3
"""Sandboxed filesystem mutation guard for NiblitDevAgent governed tasks."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

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
    """Tracks, validates, and sandboxes filesystem mutations.

    All write/delete operations must go through this guard.  The guard:
    - Blocks writes to runtime-critical paths unless ``force=True`` is passed.
    - Records rollback metadata (original content hash, path, operation type)
      for every modification.
    - Tracks all changed files so callers can audit or rollback.

    This guard does NOT perform autonomous writes on its own; it is purely a
    controlled channel.  Callers supply the actual content.
    """

    def __init__(
        self,
        repo_root: str | Path,
        telemetry: DevAgentTelemetryHooks | None = None,
    ) -> None:
        self._repo_root = Path(repo_root).resolve()
        self._telemetry = telemetry
        self._change_log: list[dict[str, Any]] = []

    # ── Path resolution / validation ─────────────────────────────────────────

    def _abs(self, relpath: str) -> Path:
        target = (self._repo_root / relpath).resolve()
        # Prevent path traversal outside repo_root
        try:
            target.relative_to(self._repo_root)
        except ValueError as exc:
            raise FilesystemGuardError(
                f"Path traversal attempt blocked: {relpath!r}"
            ) from exc
        return target

    def _is_protected(self, relpath: str) -> bool:
        try:
            candidate = Path(relpath)
            for protected in _PROTECTED_PATHS:
                p = Path(protected)
                # Exact match or candidate is inside a protected directory
                if candidate == p:
                    return True
                try:
                    candidate.relative_to(p)
                    return True
                except ValueError:
                    pass
        except Exception:
            pass
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

    # ── Mutation operations ───────────────────────────────────────────────────

    def write_file(
        self,
        relpath: str,
        content: str | bytes,
        *,
        encoding: str = "utf-8",
        force: bool = False,
    ) -> dict[str, Any]:
        """Write *content* to *relpath*, returning rollback metadata.

        Raises :class:`FilesystemGuardError` if *relpath* is protected and
        ``force`` is not set.
        """
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
        """Delete *relpath*, returning rollback metadata with original content hash."""
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
        """Return the list of relative paths that have been modified."""
        return [r["relpath"] for r in self._change_log]

    def change_log(self) -> list[dict[str, Any]]:
        """Return a deep copy of the full change log."""
        return [dict(r) for r in self._change_log]

    def rollback_metadata(self) -> dict[str, Any]:
        """Return a rollback-oriented summary of all changes."""
        return {
            "changes": self.change_log(),
            "total_changes": len(self._change_log),
            "affected_paths": self.changed_files(),
            "protected_touched": [
                r["relpath"] for r in self._change_log if r["protected"]
            ],
        }

    def clear_log(self) -> None:
        """Reset the change log (e.g., after a successful commit)."""
        self._change_log.clear()

    def validate_path(self, relpath: str) -> dict[str, Any]:
        """Non-mutating validation report for a path."""
        return {
            "relpath": relpath,
            "is_protected": self._is_protected(relpath),
            "exists": (self._repo_root / relpath).exists(),
            "absolute": str(self._abs(relpath)),
        }
