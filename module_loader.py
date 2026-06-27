import importlib.util
import os
import sys
from pathlib import Path
from typing import Dict, List


def get_repo_root() -> Path:
    """Resolve the authoritative repository root from this loader's location."""
    current = Path(__file__).resolve().parent
    if (current / "module_loader.py").exists() and (current / "modules").exists():
        return current
    if (current.parent / "Niblit" / "module_loader.py").exists():
        return current.parent / "Niblit"
    return current


def _candidate_modules_dirs() -> list[Path]:
    repo_root = get_repo_root()
    candidates = [repo_root / "modules"]
    if repo_root.name != "Niblit":
        candidates.append(repo_root.parent / "Niblit" / "modules")
    return [path for path in candidates if path.exists()]


def _ensure_repo_paths(repo_root: Path, modules_dirs: List[Path]) -> None:
    for path in [repo_root, *modules_dirs]:
        path_str = str(path)
        if path_str not in sys.path:
            sys.path.insert(0, path_str)


def load_modules() -> Dict[str, List[str]]:
    repo_root = get_repo_root()
    modules_dirs = _candidate_modules_dirs()
    if not modules_dirs:
        print("No modules directory found.")
        return {"loaded": [], "failed": []}

    _ensure_repo_paths(repo_root, modules_dirs)

    loaded: List[str] = []
    failed: List[str] = []
    for modules_dir in modules_dirs:
        for file in sorted(modules_dir.glob("*.py")):
            if file.name == "__init__.py":
                continue
            name = file.stem
            package_name = f"modules.{name}"
            if package_name in sys.modules or name in sys.modules:
                continue
            path = str(file)
            spec = importlib.util.spec_from_file_location(package_name, path)
            if spec is None or spec.loader is None:
                failed.append(file.name)
                print(f"Failed to load module: {file.name} (could not create module spec)")
                continue
            module = importlib.util.module_from_spec(spec)
            # Register in sys.modules *before* exec_module so that typing.get_type_hints()
            # (called by @dataclass when 'from __future__ import annotations' is active)
            # can resolve the module's __dict__ instead of receiving None.
            sys.modules[package_name] = module
            sys.modules.setdefault(name, module)
            try:
                spec.loader.exec_module(module)
            except Exception as exc:
                sys.modules.pop(package_name, None)
                sys.modules.pop(name, None)
                failed.append(file.name)
                print(f"Failed to load module: {file.name} ({exc})")
                continue
            loaded.append(file.name)
            print(f"Loaded module: {file.name}")

    return {"loaded": loaded, "failed": failed}


if __name__ == "__main__":
    load_modules()
