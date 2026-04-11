import os
import sys
import importlib.util

def load_modules():
    modules_dir = os.path.join(os.getcwd(), "modules")
    if not os.path.exists(modules_dir):
        print("No modules directory found.")
        return

    for file in os.listdir(modules_dir):
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
