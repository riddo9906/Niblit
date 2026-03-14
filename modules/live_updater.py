#!/usr/bin/env python3
"""
LIVE UPDATER MODULE
Safely reload, patch, and upgrade Niblit modules at runtime.

Features:
- Hot-reload any Python module without restarting
- Syntax validation before applying
- Automatic backup of current module state
- Rollback on reload failure
- Update history log
- Safe upgrade flow: backup → validate → reload → verify → (rollback on error)
"""

import sys
import os
import time
import logging
import importlib
import importlib.util
import ast
import traceback
import shutil
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Any

log = logging.getLogger("LiveUpdater")


class ModuleBackup:
    """Snapshot of a module's file content before an update."""

    def __init__(self, module_name: str, source_path: str):
        self.module_name = module_name
        self.source_path = source_path
        self.ts = datetime.now(timezone.utc).isoformat()
        self.original_content: Optional[str] = None
        self._read()

    def _read(self):
        try:
            with open(self.source_path, "r", encoding="utf-8") as fh:
                self.original_content = fh.read()
        except Exception as e:
            log.warning(f"[LiveUpdater] Could not read {self.source_path} for backup: {e}")

    def restore(self) -> bool:
        """Restore the original file from backup."""
        if self.original_content is None:
            return False
        try:
            with open(self.source_path, "w", encoding="utf-8") as fh:
                fh.write(self.original_content)
            return True
        except Exception as e:
            log.error(f"[LiveUpdater] Restore failed for {self.module_name}: {e}")
            return False


class LiveUpdater:
    """
    Safe hot-reload and upgrade engine.

    Usage:
        updater = LiveUpdater(base_dir="/path/to/niblit")
        result = updater.reload_module("modules.knowledge_db")
        result = updater.apply_patch("modules.knowledge_db", new_code_str)
    """

    def __init__(self, base_dir: Optional[str] = None):
        self.base_dir = Path(base_dir or os.getcwd())
        self._lock = threading.Lock()
        self._history: List[Dict[str, Any]] = []
        self._backup_dir = self.base_dir / ".update_backups"
        self._backup_dir.mkdir(exist_ok=True)
        log.info("[LiveUpdater] Initialized — base_dir=%s", self.base_dir)

    # ──────────────────────────────────────────────
    # PUBLIC API
    # ──────────────────────────────────────────────

    def reload_module(self, module_name: str) -> Dict[str, Any]:
        """
        Hot-reload a currently loaded module.

        Returns a dict with keys: success, module, message, error.
        """
        with self._lock:
            return self._safe_reload(module_name)

    def apply_patch(self, module_name: str, new_source: str) -> Dict[str, Any]:
        """
        Apply new source code to a module file, then reload it.

        Validates syntax first, backs up old file, rewrites, reloads.
        Rolls back on any failure.
        """
        with self._lock:
            return self._safe_patch(module_name, new_source)

    def reload_all_changed(self) -> List[Dict[str, Any]]:
        """
        Reload all modules whose files have changed since they were last loaded.
        Checks file mtime vs module's __spec__.origin mtime.
        """
        results = []
        for mod_name, mod in list(sys.modules.items()):
            spec = getattr(mod, "__spec__", None)
            if spec is None or not spec.origin:
                continue
            origin = Path(spec.origin)
            if not origin.is_file() or str(self.base_dir) not in str(origin):
                continue
            try:
                file_mtime = origin.stat().st_mtime
                load_time = getattr(mod, "_load_time", None)
                if load_time and file_mtime > load_time:
                    results.append(self.reload_module(mod_name))
            except Exception:
                pass
        return results

    def get_history(self, limit: int = 20) -> List[Dict[str, Any]]:
        """Return the last N update records."""
        return self._history[-limit:]

    def status(self) -> Dict[str, Any]:
        """Return a summary of the updater's state."""
        return {
            "base_dir": str(self.base_dir),
            "backup_dir": str(self._backup_dir),
            "updates_applied": len(self._history),
            "last_update": self._history[-1] if self._history else None,
        }

    # ──────────────────────────────────────────────
    # INTERNALS
    # ──────────────────────────────────────────────

    def _find_module_path(self, module_name: str) -> Optional[Path]:
        """Locate the .py file for a module name (dotted or plain)."""
        # Already loaded → use spec
        mod = sys.modules.get(module_name)
        if mod:
            spec = getattr(mod, "__spec__", None)
            if spec and spec.origin and spec.origin.endswith(".py"):
                return Path(spec.origin)

        # Derive path from module_name (e.g. "modules.knowledge_db" → modules/knowledge_db.py)
        rel = module_name.replace(".", os.sep) + ".py"
        candidate = self.base_dir / rel
        if candidate.is_file():
            return candidate

        # Last resort: importlib find_spec
        try:
            spec = importlib.util.find_spec(module_name)
            if spec and spec.origin:
                return Path(spec.origin)
        except Exception:
            pass

        return None

    def _validate_syntax(self, source: str, module_name: str) -> Optional[str]:
        """Return None if syntax is valid, else an error message."""
        try:
            ast.parse(source)
            return None
        except SyntaxError as e:
            return f"SyntaxError in {module_name}: {e}"

    def _backup_file(self, module_name: str, path: Path) -> Optional[Path]:
        """Save a timestamped copy of the file to the backup dir."""
        try:
            safe_name = module_name.replace(".", "_")
            ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
            dest = self._backup_dir / f"{safe_name}__{ts}.py.bak"
            shutil.copy2(str(path), str(dest))
            log.debug("[LiveUpdater] Backed up %s → %s", path.name, dest.name)
            return dest
        except Exception as e:
            log.warning("[LiveUpdater] Backup failed for %s: %s", module_name, e)
            return None

    def _safe_reload(self, module_name: str) -> Dict[str, Any]:
        ts_start = time.time()
        record: Dict[str, Any] = {
            "action": "reload",
            "module": module_name,
            "ts": datetime.now(timezone.utc).isoformat(),
            "success": False,
            "message": "",
            "error": None,
        }
        try:
            mod = sys.modules.get(module_name)
            if mod is None:
                # Try to import it first
                mod = importlib.import_module(module_name)

            importlib.reload(mod)
            # Stamp reload time
            try:
                mod._load_time = time.time()
            except Exception:
                pass

            record["success"] = True
            record["message"] = f"✅ Module '{module_name}' reloaded successfully."
            log.info("[LiveUpdater] %s", record["message"])
        except Exception as e:
            record["error"] = str(e)
            record["message"] = f"❌ Reload failed for '{module_name}': {e}"
            log.error("[LiveUpdater] %s\n%s", record["message"], traceback.format_exc())

        record["elapsed_ms"] = round((time.time() - ts_start) * 1000, 1)
        self._history.append(record)
        return record

    def _safe_patch(self, module_name: str, new_source: str) -> Dict[str, Any]:
        ts_start = time.time()
        record: Dict[str, Any] = {
            "action": "patch",
            "module": module_name,
            "ts": datetime.now(timezone.utc).isoformat(),
            "success": False,
            "message": "",
            "error": None,
            "backup": None,
            "rolled_back": False,
        }

        # 1. Validate syntax
        err = self._validate_syntax(new_source, module_name)
        if err:
            record["error"] = err
            record["message"] = f"❌ Patch rejected — {err}"
            self._history.append(record)
            return record

        # 2. Find file
        path = self._find_module_path(module_name)
        if path is None:
            record["error"] = "Module file not found"
            record["message"] = f"❌ Cannot find source file for '{module_name}'"
            self._history.append(record)
            return record

        # 3. Backup current file
        backup_path = self._backup_file(module_name, path)
        record["backup"] = str(backup_path) if backup_path else None

        # 4. Write new source
        try:
            with open(str(path), "w", encoding="utf-8") as fh:
                fh.write(new_source)
        except Exception as e:
            record["error"] = f"Write failed: {e}"
            record["message"] = f"❌ Could not write new source for '{module_name}': {e}"
            self._history.append(record)
            return record

        # 5. Reload
        reload_result = self._safe_reload(module_name)
        if not reload_result["success"]:
            # 6. Rollback on failure
            log.warning("[LiveUpdater] Reload failed; rolling back %s", module_name)
            if backup_path and backup_path.is_file():
                try:
                    shutil.copy2(str(backup_path), str(path))
                    record["rolled_back"] = True
                    # Re-reload the original
                    self._safe_reload(module_name)
                except Exception as rb_e:
                    log.error("[LiveUpdater] Rollback write failed: %s", rb_e)
            record["error"] = reload_result["error"]
            record["message"] = (
                f"❌ Patch applied but reload failed for '{module_name}'. "
                + ("Rolled back to previous version." if record["rolled_back"] else "Rollback failed.")
            )
        else:
            record["success"] = True
            record["message"] = f"✅ Patch applied and '{module_name}' reloaded successfully."

        record["elapsed_ms"] = round((time.time() - ts_start) * 1000, 1)
        self._history.append(record)
        return record

    def summarize_history(self) -> str:
        """Return a human-readable update history."""
        if not self._history:
            return "No updates have been applied in this session."
        lines = ["🔄 **Live Update History** (most recent last):"]
        for rec in self._history[-10:]:
            icon = "✅" if rec["success"] else "❌"
            lines.append(
                f"  {icon} [{rec['ts'][:19]}] {rec['action'].upper()} {rec['module']} — {rec['message']}"
            )
        return "\n".join(lines)


# ──────────────────────────────────────────────────────
# STANDALONE SELF-TEST
# ──────────────────────────────────────────────────────
if __name__ == "__main__":
    import logging
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    print("=== LiveUpdater self-test ===")
    updater = LiveUpdater()

    # Test reload of a stdlib module (safe, always available)
    result = updater.reload_module("json")
    print(f"json reload: {result['message']}")

    # Test validation of bad syntax
    bad_patch = updater.apply_patch("json", "def broken syntax here !!")
    print(f"bad patch: {bad_patch['message']}")

    print(f"\nHistory:\n{updater.summarize_history()}")
    print("LiveUpdater OK")
