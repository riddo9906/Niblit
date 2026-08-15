"""Compatibility package for niblit_core with config submodules."""

from __future__ import annotations

import importlib.util
import sys
from types import ModuleType
from typing import Any

from pathlib import Path

# Resolve the legacy module path without triggering the package namespace
_LEGACY_PATH = Path(__file__).resolve().parent.parent / "niblit_core.py"

_LEGACY_MODULE: ModuleType | None = None


def _load_legacy_module() -> ModuleType:
    global _LEGACY_MODULE
    if _LEGACY_MODULE is None:
        # Python 3.14's dataclass decorator performs strict type checking that
        # requires the module to be registered in sys.modules before class creation.
        # The dataclass code checks: ns = sys.modules.get(cls.__module__).__dict__
        # We must ensure 'niblit_core' is in sys.modules BEFORE exec_module.
        
        # Create and register the module placeholder FIRST with the CORRECT name
        # that classes in niblit_core.py expect (their __module__ is 'niblit_core')
        _placeholder = ModuleType("niblit_core")
        _placeholder.__package__ = "niblit_core"
        _placeholder.__path__ = []
        sys.modules["niblit_core"] = _placeholder
        
        # Ensure niblit_core.config subpackage is also registered
        _config_pkg = ModuleType("niblit_core.config")
        _config_pkg.__package__ = "niblit_core"
        _config_pkg.__path__ = []
        sys.modules["niblit_core.config"] = _config_pkg
        
        # Load the actual niblit_core.config.paths module into the namespace
        _paths_path = Path(__file__).resolve().parent / "config" / "paths.py"
        _paths_spec = importlib.util.spec_from_file_location("niblit_core.config.paths", _paths_path)
        if _paths_spec is not None and _paths_spec.loader is not None:
            _paths_module = importlib.util.module_from_spec(_paths_spec)
            _paths_module.__package__ = "niblit_core.config"
            sys.modules["niblit_core.config.paths"] = _paths_module
            _paths_spec.loader.exec_module(_paths_module)
        
        # Now load niblit_core.py using the ACTUAL module name 'niblit_core'
        # This ensures class.__module__ matches what's in sys.modules
        spec = importlib.util.spec_from_file_location("niblit_core", _LEGACY_PATH)
        if spec is None or spec.loader is None:
            raise ImportError(f"Unable to load niblit_core legacy module at {_LEGACY_PATH}")
        
        module = importlib.util.module_from_spec(spec)
        module.__package__ = "niblit_core"
        sys.modules["niblit_core"] = module  # Replace placeholder with real module
        spec.loader.exec_module(module)
        
        _LEGACY_MODULE = module
    return _LEGACY_MODULE


def __getattr__(name: str) -> Any:
    return getattr(_load_legacy_module(), name)


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(dir(_load_legacy_module())))


# Explicit package exports for compatibility with imports such as
# `from niblit_core import NiblitCore`.
# Note: Lazy loading is used to avoid circular import issues with dataclass decorators
# in Python 3.14. NiblitCore is accessed via __getattr__ above.
__all__ = ["NiblitCore", "NiblitConfig"]
