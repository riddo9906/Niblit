#!/usr/bin/env python3
"""
HFBrain — Unified Stateful LLM Brain for Niblit
Integrated with KnowledgeDB / MemoryManager
Author: Riyaad Behardien
"""

import os
import requests

class HFBrain:
    """
    HuggingFace Router LLM interface for Niblit.
    Fully stateful via unified memory DB.
    Supports runtime enable/disable toggle.
    """

    def __init__(self, db):
        self.db = db

        # KEEP YOUR MODEL
        self.model = "moonshotai/Kimi-K2-Instruct-0905"

        self.enabled = True

        # Use the HF_API_KEY environment variable
        self.token = os.getenv("HF_API_KEY")

        if not self.token:
            print("[HFBrain Warning] HF_API_KEY not set, HFBrain disabled")
            self.enabled = False

        # HuggingFace router endpoint
        self.url = f"https://router.huggingface.co/v1/chat/completions"

    # -------------------------
    # Toggle control
    # -------------------------
    def enable(self):
        self.enabled = True

    def disable(self):
        self.enabled = False

    def is_enabled(self):
        return self.enabled and self.token is not None

    # -------------------------
    # Context assembly
    # -------------------------
    def _build_context(self, user_prompt: str):
        messages = []

        try:
            recent = self.db.recent_interactions(15)
            for entry in recent:
                role = entry.get("role", "user")
                text = entry.get("text", "")
                messages.append({
                    "role": role if role in ("user", "assistant") else "user",
                    "content": text
                })
        except Exception:
            pass

        messages.append({
            "role": "user",
            "content": user_prompt
        })

        return messages

    # -------------------------
    # Local fallback
    # -------------------------
    def _fallback(self, prompt: str):
        return f"[HFBrain Disabled] {prompt}"

    # -------------------------
    # Single query
    # -------------------------
    def ask_single(self, prompt: str) -> str:
        if not self.is_enabled():
            return self._fallback(prompt)

        try:
            messages = self._build_context(prompt)

            headers = {
                "Authorization": f"Bearer {self.token}",
                "Content-Type": "application/json",
            }

            payload = {
                "model": self.model,
                "messages": messages,
                "temperature": 0.7,
                "max_tokens": 350
            }

            r = requests.post(
                self.url,
                headers=headers,
                json=payload,
                timeout=90
            )

            if r.status_code != 200:
                return f"[HFBrain HTTP {r.status_code}] {r.text}"

            data = r.json()
            response = data["choices"][0]["message"]["content"].strip()

            if response:
                self.db.add_interaction("user", prompt)
                self.db.add_interaction("assistant", response)

                # Optional context hook
                if hasattr(self.db, "add_hf_context"):
                    self.db.add_hf_context(response)

            return response

        except Exception as e:
            return f"[HFBrain Error] {e}"


if __name__ == "__main__":
    print("HFBrain requires unified DB. Do not run standalone.")
