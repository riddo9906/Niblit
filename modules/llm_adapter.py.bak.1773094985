#!/usr/bin/env python3
# modules/llm_adapter.py
# NiblitOS v6 — Moonshot (HF Router) + Safe Local Fallback

import os
import requests


HF_ROUTER_URL = "https://router.huggingface.co/v1/chat/completions"
HF_TOKEN = os.getenv("HF_TOKEN", None)


class LLMAdapter:

    def __init__(self):
        self.model = "moonshotai/Kimi-K2-Instruct-0905:groq"

    # -------------------------
    # Query Moonshot via HF Router
    # -------------------------
    def query_moonshot(self, prompt):

        if not HF_TOKEN:
            return None

        try:
            headers = {
                "Authorization": f"Bearer {HF_TOKEN}",
                "Content-Type": "application/json"
            }

            payload = {
                "model": self.model,
                "messages": [
                    {"role": "user", "content": prompt}
                ],
                "max_tokens": 500
            }

            res = requests.post(
                HF_ROUTER_URL,
                headers=headers,
                json=payload,
                timeout=20
            )

            if res.status_code == 200:
                data = res.json()
                return data["choices"][0]["message"]["content"]

            return None

        except Exception:
            return None

    # -------------------------
    # Offline fallback
    # -------------------------
    def query_local(self, prompt):
        return f"[Local Fallback] {prompt}"

    # -------------------------
    # Auto-select
    # -------------------------
    def query(self, prompt, mode="general"):

        # Try Moonshot first
        out = self.query_moonshot(prompt)
        if out:
            return out

        # Safe fallback
        return self.query_local(prompt)


# Export instance
llm = LLMAdapter()

def query(prompt, mode="general"):
    return llm.query(prompt, mode)


if __name__ == "__main__":
    print("Running llm_adapter.py")
