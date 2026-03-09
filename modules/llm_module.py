#!/usr/bin/env python3
# modules/llm_module.py
"""
Hugging Face LLM adapter using InferenceClient (modern API).
Provides:
 - HFLLMAdapter.is_online()
 - HFLLMAdapter.query_llm(messages, model=None, max_tokens=300)
"""
import os
from dotenv import load_dotenv

load_dotenv()

HF_TOKEN = os.environ.get("HF_TOKEN", "") or os.environ.get("HUGGINGFACE_TOKEN", "")

try:
    from huggingface_hub import InferenceClient
    HF_CLIENT_AVAILABLE = True
except Exception:
    InferenceClient = None
    HF_CLIENT_AVAILABLE = False

DEFAULT_MODEL = "moonshotai/Kimi-K2-Instruct-0905"

class HFLLMAdapter:
    def __init__(self, model: str = DEFAULT_MODEL):
        self.model = model
        self.api_key = HF_TOKEN
        self.client = None
        if HF_CLIENT_AVAILABLE and self.api_key:
            try:
                self.client = InferenceClient(api_key=self.api_key)
            except Exception:
                self.client = None

    def is_online(self) -> bool:
        # Simple check: client present and api_key present
        return bool(self.client and self.api_key)

    def query_llm(self, messages, model: str = None, max_tokens: int = 300):
        """
        messages: list[{"role": "...", "content": "..."}]
        Returns the assistant reply as a string or an error string.
        """
        if model is None:
            model = self.model
        if not self.client:
            return "[HF ERROR] InferenceClient unavailable or HF_TOKEN not set."
        try:
            resp = self.client.chat.completions.create(
                model=model,
                messages=messages,
                max_tokens=max_tokens,
            )
            # Try extract human-friendly text
            try:
                # resp.choices[0].message may be a dict or object
                choice = resp.choices[0]
                msg = getattr(choice, "message", None) or (choice.get("message") if isinstance(choice, dict) else None)
                # msg could be object with .content or dict with "content"
                if isinstance(msg, dict):
                    content = msg.get("content") or msg.get("content_text") or str(msg)
                else:
                    content = getattr(msg, "content", None) or str(msg)
            except Exception:
                # fallback to stringifying resp
                content = str(resp)
            return content
        except Exception as e:
            return f"[HF ERROR] {e}"
if __name__ == "__main__":
    print('Running llm_module.py')
