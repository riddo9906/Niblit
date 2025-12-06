import os
import requests
from dotenv import load_dotenv

load_dotenv()  # Load .env automatically

HF_API_URL = "https://router.huggingface.co/v1/chat/completions"

class HFLLMAdapter:
    """
    Hugging Face LLM Adapter
    Uses .env HF_TOKEN and supports offline fallback.
    """
    def __init__(self):
        self.api_key = os.environ.get("HF_TOKEN", "")
        self.model = "moonshotai/Kimi-K2-Instruct-0905"

    # ---------------------------
    # CHECK ONLINE STATUS
    # ---------------------------
    def is_online(self):
        if not self.api_key:
            return False
        try:
            r = requests.get("https://huggingface.co", timeout=3)
            return r.status_code == 200
        except Exception:
            return False

    # ---------------------------
    # QUERY LLM
    # ---------------------------
    def query_llm(self, messages, model=None, max_tokens=300):
        if not model:
            model = self.model
        if not self.api_key:
            return "[HF ERROR] No API token set."

        payload = {"model": model, "messages": messages, "max_tokens": max_tokens}
        headers = {"Authorization": f"Bearer {self.api_key}"}

        try:
            r = requests.post(HF_API_URL, json=payload, headers=headers, timeout=20)
            r.raise_for_status()
            data = r.json()
            return data["choices"][0]["message"]["content"]
        except Exception as e:
            return f"[HF ERROR] {str(e)}"
