# modules/llm_adapter.py
import os
import sys
import time

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MODULES_DIR = os.path.join(BASE_DIR, "modules")
if MODULES_DIR not in sys.path:
    sys.path.insert(0, MODULES_DIR)

from modules.llm_module import HFLLMAdapter

class LLMAdapter:
    def __init__(self, db):
        self.db = db
        self.provider = HFLLMAdapter()

        # Prevents first-call AttributeError
        self._last_check = 0
        self._last_result = False

    def is_available(self):
        try:
            if time.time() - self._last_check < 10:
                return self._last_result

            ok = self.provider.is_online()
            self._last_check = time.time()
            self._last_result = ok
            return ok
        except Exception:
            return False

    def query(self, prompt, context=None, max_tokens=300, model=None):
        messages = [
            {"role": "system", "content": "You are Niblit — a concise, helpful assistant."}
        ]

        if context:
            for it in context[-10:]:
                messages.append({
                    "role": it.get("role", "user"),
                    "content": it.get("text", "")
                })

        messages.append({"role": "user", "content": prompt})

        return self.provider.query_llm(messages, model=model, max_tokens=max_tokens)
