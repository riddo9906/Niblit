#!/usr/bin/env python3
# Niblit System Manager

import os
from niblit_env import NiblitEnv
from niblit_memory import NiblitMemory
from niblit_io import NiblitIO

class NiblitManager:
    REQUIRED_MODULES = [
        "niblit_core.py",
        "niblit_identity.py",
        "niblit_memory.py",
        "niblit_actions.py",
        "niblit_brain.py",
        "niblit_io.py",
        "niblit_env.py",
        "niblit_hf.py",
        "niblit_manager.py"
    ]

    def __init__(self):
        self.env = NiblitEnv()
        self.memory = NiblitMemory()

    def validate_structure(self):
        missing = []
        for mod in self.REQUIRED_MODULES:
            if not os.path.exists(os.path.join(os.getcwd(), mod)):
                missing.append(mod)

        if missing:
            NiblitIO.error("Missing modules: " + ", ".join(missing))
            return False

        NiblitIO.out("All modules valid.")
        return True

    def startup(self):
        NiblitIO.out("Niblit Manager initializing...")
        ok = self.validate_structure()
        if ok:
            self.memory.log_event("Niblit system boot successful")
            NiblitIO.out("System ready.")
        return ok

# Test
if __name__ == "__main__":
    manager = NiblitManager()
    manager.startup()
