#!/usr/bin/env python3
# modules/llm_module.py
"""
Hugging Face LLM adapter using InferenceClient (modern API).
Provides:
 - HFLLMAdapter.is_online()
 - HFLLMAdapter.query_llm(messages, model=None, max_tokens=300)
 - HFLLMAdapter.generate_code(language, purpose, context, max_tokens=800)
"""
import os
import re

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass  # python-dotenv not installed; rely on os.environ

HF_TOKEN = os.environ.get("HF_TOKEN", "") or os.environ.get("HUGGINGFACE_TOKEN", "")

try:
    from huggingface_hub import InferenceClient
    HF_CLIENT_AVAILABLE = True
except Exception:
    InferenceClient = None
    HF_CLIENT_AVAILABLE = False

DEFAULT_MODEL = "moonshotai/Kimi-K2-Instruct-0905"
# Maximum characters of research context forwarded to the LLM in generate_code().
_MAX_CONTEXT_LENGTH: int = 600


def _strip_code_fences(text: str) -> str:
    """Remove markdown code fences (```...```) wrapping generated code."""
    text = text.strip()
    # Remove opening fence: ```python, ```bash, ``` etc.
    text = re.sub(r"^```[a-zA-Z]*\n?", "", text, flags=re.MULTILINE)
    # Remove closing fence
    text = re.sub(r"^```\s*$", "", text, flags=re.MULTILINE)
    return text.strip()


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

    def generate_code(self, language: str, purpose: str, context: str = "", max_tokens: int = 800) -> str:
        """Generate real, executable code using the LLM.

        Args:
            language:   Target programming language (e.g. "python", "bash").
            purpose:    Short description of what the code should do.
            context:    Optional research context to inform the implementation.
            max_tokens: Maximum tokens for the LLM response.

        Returns:
            Generated source code as a string, or empty string on failure.
        """
        system_prompt = (
            f"You are an expert {language} programmer. "
            f"Write real, executable {language} code. "
            "Return ONLY the code itself — no explanations, no markdown fences, "
            "no preamble. The code must be complete and runnable."
        )
        user_prompt = f"Write {language} code that: {purpose}"
        if context:
            user_prompt += (
                f"\n\nUse the following research context to inform the implementation:\n"
                f"{context[:_MAX_CONTEXT_LENGTH]}"
            )
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]
        raw = self.query_llm(messages, max_tokens=max_tokens)
        if not raw or raw.startswith("[HF ERROR]"):
            return ""
        return _strip_code_fences(raw).strip()

if __name__ == "__main__":
    print('Running llm_module.py')
