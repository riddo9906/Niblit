import os
import importlib.util

def load_modules():
    modules_dir = os.path.join(os.getcwd(), "modules")
    if not os.path.exists(modules_dir):
        print("No modules directory found.")
        return

    for file in os.listdir(modules_dir):
        if file.endswith(".py"):
            path = os.path.join(modules_dir, file)
            spec = importlib.util.spec_from_file_location(file[:-3], path)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            print(f"Loaded module: {file}")

if __name__ == "__main__":
    load_modules()
