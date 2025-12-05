# modules/hf_adapter.py
import os
import logging
import requests
import time

log = logging.getLogger("HFAdapter")

HF_ROUTER = "https://router.huggingface.co/v1/chat/completions"
DEFAULT_MODEL = "openai/gpt-oss-20b:groq"

class HFAdapter:
    def __init__(self, db=None):
        self.db = db
        self.api_key = os.environ.get("HF_TOKEN") or os.environ.get("HUGGINGFACE_TOKEN")
        self._last_check = 0
        self._last_result = False

    def is_online(self, timeout=4):
        """Lightweight check: attempt a small request to the router with a harmless message."""
        now = time.time()
        if now - self._last_check < 8:
            return self._last_result
        self._last_check = now
        if not self.api_key:
            log.debug("[HFAdapter] No HF_TOKEN found.")
            self._last_result = False
            return False

        headers = {"Authorization": f"Bearer {self.api_key}"}
        payload = {
            "model": DEFAULT_MODEL,
            "messages": [{"role": "user", "content": "ping"}],
            "max_tokens": 1
        }
        try:
            r = requests.post(HF_ROUTER, headers=headers, json=payload, timeout=timeout)
            # 401 means token invalid; treat as offline but surface reason
            if r.status_code == 200:
                self._last_result = True
            else:
                log.debug(f"[HFAdapter] is_online status {r.status_code}: {r.text[:200]}")
                self._last_result = False
        except Exception as e:
            log.debug(f"[HFAdapter] is_online check failed: {e}")
            self._last_result = False
        return self._last_result

    def query(self, prompt, context=None, max_tokens=300, model=DEFAULT_MODEL):
        """Send chat-style request to the Hugging Face Router endpoint. Returns text or error string."""
        if not self.api_key:
            return "[HFAdapter] No HF_TOKEN set in environment."

        headers = {"Authorization": f"Bearer {self.api_key}"}
        messages = []
        if context:
            # context expected as a list of dicts with 'role' and 'text' or 'content'
            for it in (context or [])[-10:]:
                role = it.get("role", "user")
                content = it.get("text") or it.get("content") or ""
                messages.append({"role": role, "content": content})
        messages.append({"role": "user", "content": prompt})

        payload = {"model": model, "messages": messages, "max_tokens": max_tokens}
        try:
            r = requests.post(HF_ROUTER, headers=headers, json=payload, timeout=30)
            r.raise_for_status()
            data = r.json()
            # robust extraction
            choice = data.get("choices") and data["choices"][0]
            if choice and isinstance(choice.get("message"), dict):
                text = choice["message"].get("content", "")
            else:
                # fallback to stringified output if schema differs
                text = data.get("error") or str(data)
            # save to DB if available
            if self.db and hasattr(self.db, "add_entry"):
                try:
                    self.db.add_entry(prompt, text)
                except Exception:
                    pass
            return text
        except requests.HTTPError as he:
            log.error(f"[HFAdapter] HTTP error: {he} - {getattr(he, 'response', None)}")
            return f"[HFAdapter] HTTP error: {he}"
        except Exception as e:
            log.error(f"[HFAdapter] query failed: {e}")
            return f"[HFAdapter] Error: {e}"
