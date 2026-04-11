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
        module = importlib.util.module_from_spec(spec)
        try:
            spec.loader.exec_module(module)
        except Exception as e:
            print(f"Failed to load module: {file} ({e})")
            continue
        print(f"Loaded module: {file}")

if __name__ == "__main__":
    load_modules()
