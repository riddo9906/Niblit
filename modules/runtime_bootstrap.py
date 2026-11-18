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
    if getattr(sys, "frozen", False):
        # A bundle inside a source checkout must still run from its own files.
        # Walking upward would silently load the developer's modules/.env.
        return Path(sys.executable).resolve().parent
    for candidate in _candidate_roots(start):
        if (candidate / "niblit_core.py").exists() and (candidate / "niblit_io.py").exists():
            return candidate
    return Path(start or __file__).resolve().parent


def bootstrap_runtime_environment(start: Optional[os.PathLike[str] | str] = None) -> Path:
    """Ensure the Niblit repo root is importable and the CWD is consistent."""
    repo_root = _find_repo_root(start)
    # Installed releases have an independent, integrity-pinned runtime anchor.
    # Never let a replaced bundle .env, foreign CWD or developer shell select it.
    anchor = repo_root / 'release-runtime.json'
    if getattr(sys, 'frozen', False) and anchor.is_file():
        import json, hashlib
        from dotenv import dotenv_values
        binding = json.loads(anchor.read_text(encoding='utf-8'))
        manifest = Path(binding['manifest'])
        if hashlib.sha256(manifest.read_bytes()).hexdigest() != binding['manifest_sha256']:
            raise RuntimeError('Installed runtime manifest integrity mismatch')
        profile = Path(binding['configuration'])
        declared = json.loads(manifest.read_text(encoding='utf-8'))['resources']['configuration']['path']
        if profile.resolve() != Path(declared).resolve():
            raise RuntimeError('Installed runtime configuration identity mismatch')
        values = dotenv_values(profile)
        for key,value in values.items():
            if value is not None:os.environ[key] = value
        os.environ.update(NIBLIT_ENV_FILE=str(profile), NIBLIT_INSTALLATION_MANIFEST=str(manifest),
            NIBLIT_INSTALLATION_MANIFEST_SHA256=binding['manifest_sha256'])
        for key in ('NIBLIT_MT5_DEMO_DELIVERY_ENABLED','NIBLIT_FREQTRADE_DEMO_DELIVERY_ENABLED'):
            os.environ[key] = values.get(key) or '0'
    if os.environ.get("NIBLIT_INSTALLATION_MANIFEST"):
        from niblit_core.config.paths import apply_environment
        apply_environment()
    repo_root_str = str(repo_root)
    parent_root_str = str(repo_root.parent)

    os.chdir(repo_root)
    for path_str in list(sys.path):
        path = Path(path_str).resolve() if path_str else None
        if path is None:
            continue
        if str(path) == repo_root_str or str(path) == parent_root_str:
            sys.path.remove(path_str)

    sys.path.insert(0, repo_root_str)
    if not (getattr(sys, "frozen", False) and os.environ.get("NIBLIT_INSTALLATION_MANIFEST")):
        sys.path.insert(1, parent_root_str)

    return repo_root


def ensure_import_path(paths: Iterable[os.PathLike[str] | str] | None = None) -> None:
    for raw_path in paths or ():
        path_str = str(raw_path)
        if path_str not in sys.path:
            sys.path.insert(0, path_str)
