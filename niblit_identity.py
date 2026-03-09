#!/usr/bin/env python3
# Niblit Identity Verification Engine

import os

KEY_FILE = "axiom_identity.key"
EXPECTED_KEY = "RIYAAD_AXIOM_001"

class NiblitIdentity:
    def __init__(self):
        self.valid = False
        self.identity = "Niblit v1 Autonomous Runtime"

    def verify(self):
        """Check identity key."""
        if not os.path.exists(KEY_FILE):
            self.valid = False
            return False

        with open(KEY_FILE, "r") as f:
            data = f.read().strip()

        if data == EXPECTED_KEY:
            self.valid = True
            return True

        self.valid = False
        return False

    def status(self):
        return {
            "identity": self.identity,
            "verified": self.valid
        }

# Test
if __name__ == "__main__":
    I = NiblitIdentity()
    print("Verified:", I.verify())
    print(I.status())
