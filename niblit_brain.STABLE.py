#!/usr/bin/env python3
import os
import datetime
import requests

HF_MODEL = "mistralai/Mistral-7B-Instruct-v0.3"
HF_API_URL = "https://api-inference.huggingface.co/models/" + HF_MODEL


class NiblitBrain:
    def __init__(self, memory):
        self.memory = memory

        # Load or initialize preferences
        prefs = self.memory.get_preferences()
        if not prefs:
            prefs = {
                "tone": "neutral",
                "interaction_style": "casual"
            }
            self.memory.store_preferences(prefs)

        self.preferences = prefs

    # ──────────────────────────────────────────
    # LEARNING
    # ──────────────────────────────────────────
    def learn(self, user_input):
        record = {
            "time": datetime.datetime.utcnow().isoformat(),
            "input": user_input
        }

        self.memory.store_learning(record)

        # Simple adaptive behavior
        text = user_input.lower()
        if text in ["hi", "hello", "hey"]:
            self.preferences["tone"] = "friendly"
        elif "angry" in text or "frustrated" in text:
            self.preferences["tone"] = "calm"

        self.memory.store_preferences(self.preferences)

    # ──────────────────────────────────────────
    # HUGGINGFACE INFERENCE
    # ──────────────────────────────────────────
    def hf_generate(self, prompt):
        token = os.getenv("HF_TOKEN")
        if not token:
            return None

        headers = {"Authorization": f"Bearer {token}"}
        payload = {
            "inputs": prompt,
            "parameters": {
                "max_new_tokens": 120,
                "temperature": 0.7
            }
        }

        try:
            r = requests.post(HF_API_URL, json=payload, headers=headers, timeout=30)
            if r.status_code == 200:
                data = r.json()
                if isinstance(data, list) and "generated_text" in data[0]:
                    return data[0]["generated_text"]
        except Exception:
            return None

        return None

    # ──────────────────────────────────────────
    # LOCAL RESPONSE
    # ──────────────────────────────────────────
    def local_generate(self, user_input):
        tone = self.preferences.get("tone", "neutral")

        if tone == "friendly":
            return f"🙂 Hey — I’m listening. You said: '{user_input}'"
        elif tone == "calm":
            return f"🧘 Let’s slow this down. Tell me more."
        else:
            return f"[neutral] I hear you: '{user_input}'."

    # ──────────────────────────────────────────
    # THINK LOOP
    # ──────────────────────────────────────────
    def think(self, user_input):
        self.learn(user_input)

        # Try HF first
        hf = self.hf_generate(user_input)
        if hf:
            return hf.strip()

        return self.local_generate(user_input)


if __name__ == "__main__":
    print('Running niblit_brain.STABLE.py')
