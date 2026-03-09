#!/usr/bin/env python3
# Niblit Self-Learning System

from niblit_io import NiblitIO
import re

class NiblitLearning:
    def __init__(self, memory):
        self.memory = memory

    def process_interaction(self, user_message, ai_response):
        """Analyze patterns & store them."""
        if not user_message:
            return

        # Basic text normalization
        cleaned = user_message.lower().strip()

        # Track sentiment-like signals (lightweight)
        positivity = len(re.findall(r"\b(good|great|awesome|thanks)\b", cleaned))
        negativity = len(re.findall(r"\b(bad|angry|sad|tired|pain)\b", cleaned))

        data = {
            "raw": user_message,
            "normalized": cleaned,
            "positivity": positivity,
            "negativity": negativity,
            "response": ai_response
        }

        self.memory.store_learning(data)
        NiblitIO.out("Learning module updated patterns.")

    def evolve(self):
        """Simple pattern evolution loop."""
        log = self.memory.get_learning_log()

        if not log:
            return None

        # Build dynamic preference weights
        pref = {
            "positive_bias": sum([d["positivity"] for d in log]),
            "negative_bias": sum([d["negativity"] for d in log]),
            "interactions": len(log)
        }

        self.memory.store_preferences(pref)
        return pref

# Direct test
if __name__ == "__main__":
    from niblit_memory import NiblitMemory
    mem = NiblitMemory()
    L = NiblitLearning(mem)
    L.process_interaction("This is good", "I’m glad.")
    print(L.evolve())
