#!/usr/bin/env python3
# Niblit Environment Module

import platform
import os

class NiblitEnv:
    def __init__(self):
        self.info = {
            "os": platform.system(),
            "os_release": platform.release(),
            "architecture": platform.machine(),
            "python": platform.python_version(),
            "cwd": os.getcwd(),
            "home": os.path.expanduser("~")
        }

    def get_info(self):
        return self.info

    def ensure_dir(self, path):
        if not os.path.exists(path):
            os.makedirs(path)
        return os.path.exists(path)

# Test
if __name__ == "__main__":
    env = NiblitEnv()
    print(env.get_info())
