import importlib.util
import os
import sys
from pathlib import Path


def _candidate_modules_dirs() -> list[Path]:
    base_dir = Path(__file__).resolve().parent
    candidates = [base_dir / "modules"]
    if base_dir.name == "Niblit":
        candidates.append(base_dir / "modules")
    else:
        candidates.append(base_dir.parent / "Niblit" / "modules")
    return [path for path in candidates if path.exists()]


def load_modules():
    modules_dirs = _candidate_modules_dirs()
    if not modules_dirs:
        print("No modules directory found.")
        return

    for base_dir in modules_dirs:
        if str(base_dir.parent) not in sys.path:
            sys.path.insert(0, str(base_dir.parent))

    for modules_dir in modules_dirs:
        for file in sorted(os.listdir(modules_dir)):
            if not file.endswith(".py"):
                continue
            name = file[:-3]
            # Skip modules that are already loaded under either naming convention
            # (modules.X imported by niblit_core, or X imported standalone).
            # Re-executing an already-imported module wastes time and can cause
            # blocking side-effects (e.g. re-opening SQLite connections or
            # re-downloading ML models that are already in memory).
            if name in sys.modules or f"modules.{name}" in sys.modules:
                continue
            path = os.path.join(modules_dir, file)
            spec = importlib.util.spec_from_file_location(name, path)
            if spec is None or spec.loader is None:
                print(f"Failed to load module: {file} (could not create module spec)")
                continue
            module = importlib.util.module_from_spec(spec)
            # Register in sys.modules *before* exec_module so that typing.get_type_hints()
            # (called by @dataclass when 'from __future__ import annotations' is active)
            # can resolve the module's __dict__ instead of receiving None.
            sys.modules[name] = module
            try:
                spec.loader.exec_module(module)
            except Exception as e:
                del sys.modules[name]
                print(f"Failed to load module: {file} ({e})")
                continue
            print(f"Loaded module: {file}")


if __name__ == "__main__":
    load_modules()
