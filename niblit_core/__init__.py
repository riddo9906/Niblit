"""Compatibility package for niblit_core with config submodules."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType
from typing import Any

_LEGACY_MODULE: ModuleType | None = None
_LEGACY_PATH = Path(__file__).resolve().parents[1] / "niblit_core.py"


def _load_legacy_module() -> ModuleType:
    global _LEGACY_MODULE
    if _LEGACY_MODULE is None:
        spec = importlib.util.spec_from_file_location("_niblit_core_legacy", _LEGACY_PATH)
        if spec is None or spec.loader is None:
            raise ImportError(f"Unable to load niblit_core legacy module at {_LEGACY_PATH}")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        _LEGACY_MODULE = module
    return _LEGACY_MODULE


def __getattr__(name: str) -> Any:
    return getattr(_load_legacy_module(), name)


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(dir(_load_legacy_module())))
