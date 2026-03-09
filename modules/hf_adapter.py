#!/usr/bin/env python3
# modules/hf_adapter.py
"""
HFAdapter: higher-level adapter used by niblit_core.
Uses huggingface_hub.InferenceClient where available.
Maintains previous HFAdapter.is_online() and .query() signatures.
"""
import os
import logging
import time
from dotenv import load_dotenv

load_dotenv()

log = logging.getLogger("HFAdapter")
try:
    from huggingface_hub import InferenceClient
    HF_CLIENT_AVAILABLE = True
except Exception:
    InferenceClient = None
    HF_CLIENT_AVAILABLE = False

HF_TOKEN = os.environ.get("HF_TOKEN") or os.environ.get("HUGGINGFACE_TOKEN", "")
DEFAULT_MODEL = "moonshotai/Kimi-K2-Instruct-0905"

class HFAdapter:
    def __init__(self, db=None):
        self.db = db
        self.api_key = HF_TOKEN
        self._last_check = 0
        self._last_result = False
        self.client = None
        if HF_CLIENT_AVAILABLE and self.api_key:
            try:
                self.client = InferenceClient(api_key=self.api_key)
            except Exception as e:
                log.debug(f"[HFAdapter] InferenceClient init failed: {e}")
                self.client = None

    def is_online(self, timeout: int = 4) -> bool:
        now = time.time()
        if now - self._last_check < 8:
            return self._last_result
        self._last_check = now

        if not self.api_key or not self.client:
            log.debug("[HFAdapter] No HF_TOKEN or client.")
            self._last_result = False
            return False

        # lightweight "ping" via a tiny chat call
        try:
            resp = self.client.chat.completions.create(
                model=DEFAULT_MODEL,
                messages=[{"role":"user","content":"ping"}],
                max_tokens=1,
            )
            # if response is returned without exception, consider online
            self._last_result = True
        except Exception as e:
            log.debug(f"[HFAdapter] is_online failed: {e}")
            self._last_result = False
        return self._last_result

    def query(self, prompt, context=None, max_tokens: int = 300, model: str = DEFAULT_MODEL):
        if not self.api_key or not self.client:
            return "[HFAdapter] No HF_TOKEN set or client unavailable."

        messages = []
        # preserve previous behaviour: build messages from context if present
        if context:
            for it in (context or [])[-10:]:
                role = it.get("role", "user") if isinstance(it, dict) else getattr(it, "role", "user")
                content = it.get("text") or it.get("content") or ""
                messages.append({"role": role, "content": content})
        # append user prompt
        messages.append({"role": "user", "content": prompt})

        try:
            resp = self.client.chat.completions.create(
                model=model,
                messages=messages,
                max_tokens=max_tokens,
            )
            # extract reply
            try:
                choice = resp.choices[0]
                msg = getattr(choice, "message", None) or (choice.get("message") if isinstance(choice, dict) else None)
                if isinstance(msg, dict):
                    text = msg.get("content") or str(msg)
                else:
                    text = getattr(msg, "content", None) or str(msg)
            except Exception:
                text = str(resp)
            # optional: persist to DB if available
            if self.db and hasattr(self.db, "add_entry"):
                try:
                    self.db.add_entry(prompt, text)
                except Exception:
                    pass
            return text
        except Exception as e:
            log.error(f"[HFAdapter] query failed: {e}")
            return f"[HFAdapter] Error: {e}"
if __name__ == "__main__":
    print('Running hf_adapter.py')
