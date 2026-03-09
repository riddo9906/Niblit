#!/usr/bin/env python3
# Niblit I/O Interface

import sys
from datetime import datetime

class NiblitIO:
    @staticmethod
    def timestamp():
        return datetime.now().strftime("[%Y-%m-%d %H:%M:%S]")

    @staticmethod
    def out(message):
        print(f"{NiblitIO.timestamp()} {message}")

    @staticmethod
    def error(message):
        print(f"{NiblitIO.timestamp()} ERROR: {message}", file=sys.stderr)

    @staticmethod
    def prompt(msg="> "):
        try:
            return input(msg)
        except Exception:
            return None

# Test
if __name__ == "__main__":
    NiblitIO.out("Niblit IO initialized.")
