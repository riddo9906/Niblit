# modules/llm_module.py

import os
import time
import requests

HF_API_URL = "https://router.huggingface.co/v1/chat/completions"

class HFLLMAdapter:
    def __init__(self):
        # Try reading from environment
        self.api_key = os.environ.get("HF_TOKEN")

        # Hardcoded fallback (your key)
        if not self.api_key:
            self.api_key = ""

        self.model = "moonshotai/Kimi-K2-Instruct-0905"

    # ---------------------------
    # CHECK IF HF IS ONLINE
    # ---------------------------
    def is_online(self):
        try:
            r = requests.get("https://huggingface.co", timeout=3)
            return r.status_code == 200
        except Exception:
            return False

    # ---------------------------
    # SEND MESSAGE TO HF LLM
    # ---------------------------
    def query_llm(self, messages, model=None, max_tokens=300):
        if not model:
            model = self.model

        payload = {
            "model": model,
            "messages": messages,
            "max_tokens": max_tokens,
        }

        headers = {
            "Authorization": f"Bearer {self.api_key}"
        }

        try:
            r = requests.post(HF_API_URL, json=payload, headers=headers, timeout=20)
            r.raise_for_status()
            data = r.json()

            # HF-compatible output
            return data["choices"][0]["message"]["content"]

        except Exception as e:
            return f"[HF ERROR] {str(e)}"
