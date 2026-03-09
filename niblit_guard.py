#!/usr/bin/env python3
# Niblit Safety & Validation Layer

import re
from niblit_io import NiblitIO

class NiblitGuard:
    SAFE_COMMANDS = [
        "help", "clear", "memory", "status", "learn", "tasks",
        "run", "stop", "hf", "identity", "system"
    ]

    BLOCKED_PATTERNS = [
        r"rm -rf",
        r"shutdown",
        r"format",
        r":\/\/",
    ]

    def sanitize(self, text):
        """Remove invalid characters & normalize whitespace."""
        if not text:
            return ""
        cleaned = re.sub(r"[^a-zA-Z0-9 .,\-_!?@/]", "", text)
        return cleaned.strip()

    def validate_command(self, cmd):
        """Check for malicious or invalid ops."""
        for pattern in self.BLOCKED_PATTERNS:
            if re.search(pattern, cmd):
                NiblitIO.error("Blocked dangerous command!")
                return False

        if cmd.split(" ")[0] not in self.SAFE_COMMANDS:
            NiblitIO.error(f"Unknown or unsafe command: {cmd}")
            return False

        return True

# Test
if __name__ == "__main__":
    g = NiblitGuard()
    print(g.validate_command("help"))
    print(g.validate_command("rm -rf /"))
