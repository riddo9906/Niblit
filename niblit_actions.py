#!/usr/bin/env python3
"""Niblit Action Module – file I/O, shell execution, and directory listing."""

import subprocess
import os
from niblit_memory import MemoryManager


class NiblitActions:
    """Provides file I/O, shell execution, and directory listing actions."""

    def __init__(self):
        self.memory = MemoryManager()

    def run_shell(self, command):
        """Executes safe shell commands."""
        try:
            output = subprocess.check_output(command, shell=True, stderr=subprocess.STDOUT)
            result = output.decode()
            self.memory.log_event(f"Shell executed: {command}")
            return result
        except Exception as e:
            return f"Error: {e}"

    def read_file(self, path):
        """Read and return the text contents of the file at *path*."""
        if not os.path.exists(path):
            return "File does not exist."
        with open(path, "r", encoding="utf-8") as f:
            return f.read()

    def write_file(self, path, content):
        """Write *content* to the file at *path* and log the event."""
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
        self.memory.log_event(f"Wrote file: {path}")
        return "Write OK"

    def list_directory(self, path="."):
        """Return a list of filenames in the directory at *path*."""
        try:
            return os.listdir(path)
        except Exception as e:
            return str(e)

# Test
if __name__ == "__main__":
    act = NiblitActions()
    print(act.list_directory())
