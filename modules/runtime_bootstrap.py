"""Shared bootstrap helpers for Niblit entrypoints and tests."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Iterable, Optional


def _candidate_roots(start: Optional[os.PathLike[str] | str] = None) -> list[Path]:
    start_path = Path(start or __file__).resolve()
    candidates: list[Path] = []
    if start_path.is_file():
        start_path = start_path.parent
    current = start_path
    while True:
        candidates.append(current)
        if current.parent == current:
            break
        current = current.parent
    return candidates


def _find_repo_root(start: Optional[os.PathLike[str] | str] = None) -> Path:
    for candidate in _candidate_roots(start):
        if (candidate / "niblit_core.py").exists() and (candidate / "niblit_io.py").exists():
            return candidate
    return Path(start or __file__).resolve().parent


def bootstrap_runtime_environment(start: Optional[os.PathLike[str] | str] = None) -> Path:
    """Ensure the Niblit repo root is importable and the CWD is consistent."""
    repo_root = _find_repo_root(start)
    repo_root_str = str(repo_root)
    parent_root_str = str(repo_root.parent)

    os.chdir(repo_root)
    for path_str in (repo_root_str, parent_root_str):
        path = Path(path_str)
        if str(path) not in sys.path:
            sys.path.insert(0, str(path))

    return repo_root


def ensure_import_path(paths: Iterable[os.PathLike[str] | str] | None = None) -> None:
    for raw_path in paths or ():
        path_str = str(raw_path)
        if path_str not in sys.path:
            sys.path.insert(0, path_str)
