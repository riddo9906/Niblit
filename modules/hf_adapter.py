import os
import logging
import requests
import time
from dotenv import load_dotenv

load_dotenv()

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
        now = time.time()
        if now - self._last_check < 8:
            return self._last_result
        self._last_check = now
        if not self.api_key:
            log.debug("[HFAdapter] No HF_TOKEN found.")
            self._last_result = False
            return False

        headers = {"Authorization": f"Bearer {self.api_key}"}
        payload = {"model": DEFAULT_MODEL, "messages":[{"role":"user","content":"ping"}], "max_tokens":1}

        try:
            r = requests.post(HF_ROUTER, headers=headers, json=payload, timeout=timeout)
            self._last_result = r.status_code == 200
        except Exception as e:
            log.debug(f"[HFAdapter] is_online failed: {e}")
            self._last_result = False
        return self._last_result

    def query(self, prompt, context=None, max_tokens=300, model=DEFAULT_MODEL):
        if not self.api_key:
            return "[HFAdapter] No HF_TOKEN set in environment."

        headers = {"Authorization": f"Bearer {self.api_key}"}
        messages = []

        if context:
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
            choice = data.get("choices") and data["choices"][0]
            text = choice.get("message", {}).get("content", "") if choice else str(data.get("error", str(data)))
            if self.db and hasattr(self.db, "add_entry"):
                try:
                    self.db.add_entry(prompt, text)
                except:
                    pass
            return text
        except requests.HTTPError as he:
            log.error(f"[HFAdapter] HTTP error: {he}")
            return f"[HFAdapter] HTTP error: {he}"
        except Exception as e:
            log.error(f"[HFAdapter] query failed: {e}")
            return f"[HFAdapter] Error: {e}"
