#!/usr/bin/env python3
# HuggingFace Integration Module for Niblit

import os
import requests
from niblit_memory import MemoryManager

class NiblitHF:
    def __init__(self):
        self.token = os.getenv("HF_TOKEN")
        self.memory = MemoryManager()
        self.api = "https://api-inference.huggingface.co/models"

    def query_model(self, model, payload):
        if not self.token:
            return "HF_TOKEN is not set."

        headers = {"Authorization": f"Bearer {self.token}"}

        try:
            response = requests.post(f"{self.api}/{model}", headers=headers, json=payload)
            self.memory.log_event(f"HF query to {model}")
            return response.json()
        except Exception as e:
            return {"error": str(e)}

    def text_gen(self, model, prompt):
        return self.query_model(model, {"inputs": prompt})

# Test
if __name__ == "__main__":
    hf = NiblitHF()
    print("HF token detected:", bool(hf.token))
