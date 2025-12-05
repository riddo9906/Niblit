# local_llm_adapter.py -- call local inference server
import requests, time

class LocalLLMAdapter:
    def __init__(self, base_url="http://127.0.0.1:8000"):
        self.base_url = base_url.rstrip("/")
        self._last_check = 0
        self._last_result = False

    def is_available(self):
        now = time.time()
        if now - self._last_check < 5:
            return self._last_result
        try:
            r = requests.get(self.base_url + "/health", timeout=2)
            ok = r.status_code == 200
        except Exception:
            ok = False
        self._last_check = now
        self._last_result = ok
        return ok

    def query(self, prompt, context=None, max_tokens=256, model=None):
        payload = {"prompt": prompt, "max_tokens": max_tokens}
        if context:
            payload["context"] = context
        try:
            r = requests.post(self.base_url + "/complete", json=payload, timeout=30)
            r.raise_for_status()
            data = r.json()
            return data.get("text") or data.get("completion") or ""
        except Exception as e:
            return f"[LOCAL-LLM ERROR] {e}"
