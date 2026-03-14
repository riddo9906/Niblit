#!/usr/bin/env python3
"""
ENHANCED FILESYSTEM MANAGER MODULE
Full-featured file manager: create, read, write, edit, execute all file types.

Features:
- CRUD operations for any file type
- Execute scripts (Python, Bash, JS) directly
- Termux environment detection and support
- Binary and text file handling
- Directory management and structure creation
- File type detection
"""

import os
import sys
import stat
import shutil
import logging
import subprocess
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

log = logging.getLogger("FilesystemManager")

# File type -> how to execute it
_EXEC_MAP: Dict[str, str] = {
    ".py": sys.executable,
    ".sh": "bash",
    ".js": "node",
    ".rb": "ruby",
    ".pl": "perl",
    ".php": "php",
    ".lua": "lua",
}

# Text file extensions
_TEXT_EXTS = {
    ".py", ".js", ".ts", ".sh", ".bash", ".zsh",
    ".html", ".htm", ".css", ".scss", ".less",
    ".json", ".yaml", ".yml", ".toml", ".ini", ".cfg", ".conf",
    ".txt", ".md", ".rst", ".log", ".csv", ".tsv",
    ".xml", ".svg", ".sql", ".rb", ".php", ".go", ".rs", ".c", ".cpp",
    ".h", ".java", ".kt", ".swift", ".r", ".pl",
}

# Niblit standard folder structure
_NIBLIT_STRUCTURE: List[str] = [
    "modules",
    "logs",
    "scripts",
    "downloads",
    "uploads",
    "generated",
    "backups",
    "data",
]


def _detect_termux() -> bool:
    """Return True if running inside a Termux environment."""
    return (
        "TERMUX_VERSION" in os.environ
        or os.path.isdir("/data/data/com.termux")
        or "termux" in os.environ.get("PREFIX", "").lower()
    )


class FilesystemManager:
    """Full-featured file manager for all file types."""

    def __init__(self, base_dir: Optional[str] = None, db: Any = None):
        self.base_dir = Path(base_dir or os.getcwd())
        self.db = db
        self.is_termux = _detect_termux()
        if self.is_termux:
            log.info("[FilesystemManager] Termux environment detected.")
        log.debug("[FilesystemManager] base_dir=%s", self.base_dir)

    def ensure_structure(self, base_path: Optional[str] = None) -> str:
        """Create the standard Niblit folder structure."""
        base = Path(base_path or self.base_dir)
        created = []
        for folder in _NIBLIT_STRUCTURE:
            target = base / folder
            if not target.exists():
                target.mkdir(parents=True, exist_ok=True)
                created.append(str(target))
        msg = f"Ensured structure at {base}. Created: {len(created)} folder(s)."
        log.info("[FilesystemManager] %s", msg)
        return msg

    def write(
        self,
        filepath: str,
        content: Union[str, bytes],
        mode: str = "w",
        encoding: str = "utf-8",
    ) -> Dict[str, Any]:
        """Create or overwrite a file with content."""
        path = self._resolve(filepath)
        result: Dict[str, Any] = {
            "path": str(path), "success": False, "error": None, "bytes": 0
        }
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            if isinstance(content, bytes) or "b" in mode:
                with open(path, "wb") as fh:
                    data = content if isinstance(content, bytes) else content.encode(encoding)
                    fh.write(data)
                    result["bytes"] = len(data)
            else:
                with open(path, mode, encoding=encoding) as fh:
                    fh.write(content)
                    result["bytes"] = len(content)
            result["success"] = True
        except OSError as exc:
            result["error"] = str(exc)
            log.error("[FilesystemManager] Write failed: %s", exc)
        return result

    def append(self, filepath: str, content: str, encoding: str = "utf-8") -> Dict[str, Any]:
        """Append content to an existing (or new) file."""
        return self.write(filepath, content, mode="a", encoding=encoding)

    def create_dir(self, dirpath: str) -> Dict[str, Any]:
        """Create a directory (and parents) if it doesn't exist."""
        path = self._resolve(dirpath)
        result: Dict[str, Any] = {"path": str(path), "success": False, "error": None}
        try:
            path.mkdir(parents=True, exist_ok=True)
            result["success"] = True
        except OSError as exc:
            result["error"] = str(exc)
        return result

    def read(
        self,
        filepath: str,
        encoding: str = "utf-8",
        binary: bool = False,
    ) -> Dict[str, Any]:
        """Read a file's content."""
        path = self._resolve(filepath)
        result: Dict[str, Any] = {
            "path": str(path), "content": None, "success": False,
            "error": None, "size": 0, "type": "binary" if binary else "text",
        }
        if not path.exists():
            result["error"] = f"File not found: {path}"
            return result
        try:
            if binary or path.suffix.lower() not in _TEXT_EXTS:
                with open(path, "rb") as fh:
                    data = fh.read()
                result["content"] = data
                result["type"] = "binary"
                result["size"] = len(data)
            else:
                with open(path, "r", encoding=encoding, errors="replace") as fh:
                    text = fh.read()
                result["content"] = text
                result["size"] = len(text)
            result["success"] = True
        except OSError as exc:
            result["error"] = str(exc)
        return result

    def read_lines(self, filepath: str, encoding: str = "utf-8") -> List[str]:
        """Read a text file as a list of lines."""
        r = self.read(filepath, encoding=encoding)
        if r["success"] and isinstance(r["content"], str):
            return r["content"].splitlines()
        return []

    def list_dir(self, dirpath: str = ".") -> Dict[str, Any]:
        """List files and directories at a path."""
        path = self._resolve(dirpath)
        result: Dict[str, Any] = {
            "path": str(path), "entries": [], "success": False, "error": None
        }
        if not path.is_dir():
            result["error"] = f"Not a directory: {path}"
            return result
        try:
            entries = []
            for entry in sorted(path.iterdir()):
                entries.append({
                    "name": entry.name,
                    "type": "dir" if entry.is_dir() else "file",
                    "size": entry.stat().st_size if entry.is_file() else 0,
                    "modified": datetime.fromtimestamp(
                        entry.stat().st_mtime, tz=timezone.utc
                    ).isoformat(),
                })
            result["entries"] = entries
            result["success"] = True
        except OSError as exc:
            result["error"] = str(exc)
        return result

    def replace_in_file(
        self,
        filepath: str,
        old_text: str,
        new_text: str,
        encoding: str = "utf-8",
    ) -> Dict[str, Any]:
        """Replace all occurrences of old_text with new_text in a file."""
        r = self.read(filepath, encoding=encoding)
        if not r["success"]:
            return r
        content = r["content"]
        if not isinstance(content, str):
            return {**r, "error": "Cannot edit binary file with text replace"}
        count = content.count(old_text)
        new_content = content.replace(old_text, new_text)
        write_result = self.write(filepath, new_content, encoding=encoding)
        write_result["replacements"] = count
        return write_result

    def insert_at_line(
        self,
        filepath: str,
        line_num: int,
        text: str,
        encoding: str = "utf-8",
    ) -> Dict[str, Any]:
        """Insert text at a specific line number (1-based)."""
        lines = self.read_lines(filepath, encoding=encoding)
        insert_at = min(max(0, line_num - 1), len(lines))
        lines.insert(insert_at, text)
        return self.write(filepath, "\n".join(lines) + "\n", encoding=encoding)

    def delete(self, filepath: str) -> Dict[str, Any]:
        """Delete a file or directory."""
        path = self._resolve(filepath)
        result: Dict[str, Any] = {"path": str(path), "success": False, "error": None}
        try:
            if path.is_dir():
                shutil.rmtree(str(path))
            else:
                path.unlink()
            result["success"] = True
        except OSError as exc:
            result["error"] = str(exc)
        return result

    def copy(self, src: str, dst: str) -> Dict[str, Any]:
        """Copy a file or directory."""
        src_p, dst_p = self._resolve(src), self._resolve(dst)
        result: Dict[str, Any] = {
            "src": str(src_p), "dst": str(dst_p), "success": False, "error": None
        }
        try:
            if src_p.is_dir():
                shutil.copytree(str(src_p), str(dst_p))
            else:
                dst_p.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(str(src_p), str(dst_p))
            result["success"] = True
        except OSError as exc:
            result["error"] = str(exc)
        return result

    def move(self, src: str, dst: str) -> Dict[str, Any]:
        """Move/rename a file or directory."""
        src_p, dst_p = self._resolve(src), self._resolve(dst)
        result: Dict[str, Any] = {
            "src": str(src_p), "dst": str(dst_p), "success": False, "error": None
        }
        try:
            dst_p.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(src_p), str(dst_p))
            result["success"] = True
        except OSError as exc:
            result["error"] = str(exc)
        return result

    def execute(
        self,
        filepath: str,
        args: Optional[List[str]] = None,
        timeout: int = 30,
    ) -> Dict[str, Any]:
        """Execute a script file (.py, .sh, .js, etc.)."""
        path = self._resolve(filepath)
        result: Dict[str, Any] = {
            "path": str(path), "success": False, "stdout": "",
            "stderr": "", "returncode": -1, "error": None,
        }
        if not path.is_file():
            result["error"] = f"File not found: {path}"
            return result

        ext = path.suffix.lower()
        runner = _EXEC_MAP.get(ext)

        if runner:
            cmd = [runner, str(path)] + (args or [])
        elif os.access(str(path), os.X_OK):
            cmd = [str(path)] + (args or [])
        else:
            try:
                path.chmod(path.stat().st_mode | stat.S_IEXEC)
                cmd = [str(path)] + (args or [])
            except OSError as exc:
                result["error"] = f"Cannot execute '{path}': {exc}"
                return result

        try:
            proc = subprocess.run(
                cmd, capture_output=True, text=True,
                timeout=timeout, cwd=str(self.base_dir),
            )
            result["stdout"] = proc.stdout
            result["stderr"] = proc.stderr
            result["returncode"] = proc.returncode
            result["success"] = proc.returncode == 0
        except subprocess.TimeoutExpired:
            result["error"] = f"Execution timed out after {timeout}s"
        except (OSError, FileNotFoundError) as exc:
            result["error"] = f"OS error: {exc}"
        return result

    def run_code_string(
        self,
        language: str,
        code: str,
        timeout: int = 10,
    ) -> Dict[str, Any]:
        """Run a code string in a temp file."""
        lang_map = {
            "python": (".py", sys.executable),
            "python3": (".py", sys.executable),
            "bash": (".sh", "bash"),
            "sh": (".sh", "sh"),
            "javascript": (".js", "node"),
            "js": (".js", "node"),
        }
        entry = lang_map.get(language.lower())
        if not entry:
            return {"success": False, "error": f"Language '{language}' not supported"}

        ext, runner = entry
        tmp_path: Optional[str] = None
        result: Dict[str, Any] = {
            "success": False, "stdout": "", "stderr": "", "returncode": -1, "error": None
        }
        try:
            with tempfile.NamedTemporaryFile(
                mode="w", suffix=ext, delete=False, encoding="utf-8"
            ) as tmp:
                tmp.write(code)
                tmp_path = tmp.name
            if ext == ".sh":
                os.chmod(tmp_path, 0o755)
            proc = subprocess.run(
                [runner, tmp_path], capture_output=True, text=True, timeout=timeout
            )
            result["stdout"] = proc.stdout
            result["stderr"] = proc.stderr
            result["returncode"] = proc.returncode
            result["success"] = proc.returncode == 0
        except subprocess.TimeoutExpired:
            result["error"] = f"Timed out after {timeout}s"
        except (OSError, FileNotFoundError) as exc:
            result["error"] = str(exc)
        finally:
            if tmp_path and os.path.exists(tmp_path):
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass
        return result

    def info(self, filepath: str) -> Dict[str, Any]:
        """Return metadata about a file."""
        path = self._resolve(filepath)
        if not path.exists():
            return {"error": f"Not found: {path}"}
        try:
            s = path.stat()
            return {
                "path": str(path),
                "name": path.name,
                "extension": path.suffix,
                "type": "dir" if path.is_dir() else "file",
                "size_bytes": s.st_size,
                "modified": datetime.fromtimestamp(s.st_mtime, tz=timezone.utc).isoformat(),
                "is_executable": os.access(str(path), os.X_OK),
                "is_text": path.suffix.lower() in _TEXT_EXTS,
            }
        except OSError as exc:
            return {"error": str(exc)}

    def find(self, pattern: str, search_dir: str = ".") -> List[str]:
        """Find files matching a glob pattern."""
        base = self._resolve(search_dir)
        return [str(p) for p in base.glob(pattern)]

    def environment_info(self) -> str:
        """Return info about the current runtime environment."""
        lines = ["Filesystem Environment:"]
        lines.append(f"  Base dir    : {self.base_dir}")
        lines.append(f"  Termux      : {'Yes' if self.is_termux else 'No'}")
        lines.append(f"  Platform    : {sys.platform}")
        lines.append(f"  Python      : {sys.version.split()[0]}")
        lines.append(f"  CWD         : {os.getcwd()}")
        try:
            usage = shutil.disk_usage(str(self.base_dir))
            free_mb = usage.free // (1024 * 1024)
            total_mb = usage.total // (1024 * 1024)
            lines.append(f"  Disk free   : {free_mb} MB / {total_mb} MB")
        except OSError:
            pass
        return "\n".join(lines)

    def summary(self) -> str:
        """Return a quick summary of capabilities."""
        termux_note = " (Termux mode)" if self.is_termux else ""
        executables = list(_EXEC_MAP.keys())
        return (
            f"FilesystemManager{termux_note}\n"
            f"  Base: {self.base_dir}\n"
            f"  Supported execute: {', '.join(executables)}\n"
            f"  Operations: create, read, write, append, edit, delete, copy, move, execute"
        )

    def _resolve(self, filepath: str) -> Path:
        """Resolve a path relative to base_dir, or absolute."""
        p = Path(filepath)
        if p.is_absolute():
            return p
        return self.base_dir / p

    # Keep backward-compatible usage timer
    _last_used: float = 0.0

    def mark_used(self) -> None:
        """Mark last use time."""
        self._last_used = time.time()


if __name__ == "__main__":
    import logging as _logging  # pylint: disable=reimported,ungrouped-imports
    _logging.basicConfig(level=_logging.INFO, format="%(message)s")
    print("=== FilesystemManager self-test ===\n")

    fsm = FilesystemManager(base_dir="/tmp/niblit_fsm_test")
    print(fsm.environment_info())
    print()

    r = fsm.write("hello.txt", "Hello from Niblit!\n")
    print(f"Write: {r['success']}")

    r = fsm.read("hello.txt")
    print(f"Read: {r['content']!r}")

    r = fsm.list_dir(".")
    print(f"List: {[e['name'] for e in r['entries']]}")

    r = fsm.run_code_string("python", "print('Python execution works!')")
    print(f"Execute Python: {r['stdout'].strip()}")

    print(fsm.ensure_structure())
    print("\nFilesystemManager OK")
