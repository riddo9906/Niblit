#!/usr/bin/env python3
"""
BUILD SCANNER MODULE
Scan, read, and understand the Niblit build directory at
/data/data/com.termux/files/home/NiblitAIOS/Niblit-Modules/Niblit-apk/Niblit.

Enables Niblit to read its own source files and store their contents in
KnowledgeDB for self-understanding and autonomous self-improvement.
"""

import logging
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

log = logging.getLogger("BuildScanner")

# Niblit build path — imported from the canonical definition in evolve.py
try:
    from modules.evolve import TERMUX_DEPLOY_PATH as NIBLIT_BUILD_PATH
except Exception:
    NIBLIT_BUILD_PATH = Path(
        "/data/data/com.termux/files/home/NiblitAIOS/Niblit-Modules/Niblit-apk/Niblit"
    )

# Maximum bytes read per file to avoid flooding memory
_MAX_READ_BYTES = 32 * 1024  # 32 KB


class BuildScanner:
    """Scan and read the Niblit build directory.

    Provides Niblit with self-knowledge about its own source code by
    listing files, reading their contents, and optionally persisting
    summaries to KnowledgeDB so the autonomous learning engine can
    incorporate that self-knowledge into its improvement cycles.

    Usage:
        scanner = BuildScanner(db=knowledge_db)
        print(scanner.summarize())
        result = scanner.read_file("niblit_core.py")
    """

    def __init__(self, build_path: Optional[str] = None, db: Any = None):
        self.build_path = Path(build_path) if build_path else NIBLIT_BUILD_PATH
        self.db = db
        self._stats: Dict[str, int] = {"scans": 0, "files_read": 0, "errors": 0}
        log.debug("[BuildScanner] build_path=%s", self.build_path)

    # ──────────────────────────────────────────────────────
    # PUBLIC API
    # ──────────────────────────────────────────────────────

    def scan(self, subdir: str = "") -> Dict[str, Any]:
        """List all files in the build directory (or a subdirectory).

        Returns a dict with keys: path, files, dirs, total, error.
        Each file entry is {"name", "ext", "size", "path"}.
        """
        target = self.build_path / subdir if subdir else self.build_path
        result: Dict[str, Any] = {
            "path": str(target),
            "files": [],
            "dirs": [],
            "total": 0,
            "error": None,
        }
        if not target.exists():
            result["error"] = f"Path not found: {target}"
            return result

        try:
            files: List[Dict[str, Any]] = []
            dirs: List[str] = []
            for entry in sorted(target.iterdir()):
                if entry.name.startswith("."):
                    continue  # skip hidden
                if entry.is_dir():
                    dirs.append(entry.name)
                else:
                    files.append({
                        "name": entry.name,
                        "ext": entry.suffix.lower(),
                        "size": entry.stat().st_size,
                        "path": str(entry),
                    })
            result["files"] = files
            result["dirs"] = dirs
            result["total"] = len(files) + len(dirs)
            self._stats["scans"] += 1
        except PermissionError as exc:
            result["error"] = f"Permission denied: {exc}"
            self._stats["errors"] += 1
        except OSError as exc:
            result["error"] = str(exc)
            self._stats["errors"] += 1
        return result

    def read_file(self, filepath: str) -> Dict[str, Any]:
        """Read a file from the build directory.

        *filepath* may be absolute or relative to build_path.
        Returns {"path", "content", "size", "success", "error"}.
        """
        path = (
            Path(filepath)
            if Path(filepath).is_absolute()
            else self.build_path / filepath
        )
        result: Dict[str, Any] = {
            "path": str(path),
            "content": "",
            "size": 0,
            "success": False,
            "error": None,
        }
        if not path.exists():
            result["error"] = f"File not found: {path}"
            return result
        if not path.is_file():
            result["error"] = f"Not a file: {path}"
            return result

        try:
            size = path.stat().st_size
            with open(path, "r", encoding="utf-8", errors="replace") as fh:
                content = fh.read(_MAX_READ_BYTES)
            if size > _MAX_READ_BYTES:
                content += f"\n... [truncated — file is {size} bytes]"
            result["content"] = content
            result["size"] = size
            result["success"] = True
            self._stats["files_read"] += 1
            self._store_file(path.name, content)
        except OSError as exc:
            result["error"] = str(exc)
            self._stats["errors"] += 1
        return result

    def summarize(self) -> str:
        """Return a human-readable summary of the build directory."""
        scan = self.scan()
        if scan.get("error"):
            return f"❌ Build scanner: {scan['error']}"

        lines = [
            f"🏗️ **Niblit Build Directory:** `{scan['path']}`",
            f"  Subdirectories : {len(scan['dirs'])}",
            f"  Files          : {len(scan['files'])}",
        ]
        if scan["dirs"]:
            lines.append(f"  📁 Dirs: {', '.join(scan['dirs'][:10])}")

        py_files = [f for f in scan["files"] if f["ext"] == ".py"]
        if py_files:
            names = ", ".join(f["name"] for f in py_files[:10])
            lines.append(f"  🐍 Python files ({len(py_files)}): {names}")

        other = [f for f in scan["files"] if f["ext"] != ".py"]
        if other:
            names = ", ".join(f["name"] for f in other[:8])
            lines.append(f"  📄 Other files ({len(other)}): {names}")

        return "\n".join(lines)

    def scan_recursive(self, max_depth: int = 3) -> List[Dict[str, Any]]:
        """Recursively scan the build directory up to *max_depth* levels.

        Returns a flat list of file-info dicts (name, path, ext, size, depth).
        """
        results: List[Dict[str, Any]] = []
        self._walk(self.build_path, 0, max_depth, results)
        return results

    def get_stats(self) -> Dict[str, int]:
        """Return scanner statistics."""
        return dict(self._stats)

    # ──────────────────────────────────────────────────────
    # INTERNALS
    # ──────────────────────────────────────────────────────

    def _walk(
        self, path: Path, depth: int, max_depth: int, results: list
    ) -> None:
        if depth > max_depth:
            return
        try:
            for entry in sorted(path.iterdir()):
                if entry.name.startswith("."):
                    continue
                if entry.is_file():
                    results.append({
                        "name": entry.name,
                        "path": str(entry),
                        "ext": entry.suffix.lower(),
                        "size": entry.stat().st_size,
                        "depth": depth,
                    })
                elif entry.is_dir() and depth < max_depth:
                    self._walk(entry, depth + 1, max_depth, results)
        except (PermissionError, OSError):
            pass

    def _store_file(self, name: str, content: str) -> None:
        """Persist file-content summary to KnowledgeDB."""
        if not self.db or not hasattr(self.db, "add_fact"):
            return
        try:
            self.db.add_fact(
                f"build_file:{name}:{int(time.time())}",
                content[:500],
                tags=["build", "self_knowledge", "source"],
            )
        except Exception:
            pass
