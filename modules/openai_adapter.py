#!/usr/bin/env python3
"""
modules/openai_adapter.py — OpenAI LLM adapter for Niblit.

Follows the same interface contract as HFLLMAdapter so that it can be used
as a drop-in alternative in the autonomous learning pipeline.

Activation::

    OPENAI_API_KEY=sk-...       # Required — set in .env
    OPENAI_MODEL=gpt-4o-mini    # Optional — default gpt-4o-mini

The adapter degrades gracefully: if the key is absent or the request fails,
None / empty string is returned and the caller falls back to the next adapter.
"""

import logging
import os
from typing import Any, Dict, List, Optional

import requests

log = logging.getLogger("OpenAIAdapter")

_OPENAI_CHAT_URL = "https://api.openai.com/v1/chat/completions"
_DEFAULT_MODEL = "gpt-4o-mini"
_DEFAULT_MAX_TOKENS = 800


class OpenAIAdapter:
    """
    Thin wrapper around the OpenAI Chat Completions API.

    Args:
        api_key:   OpenAI API key. Falls back to ``OPENAI_API_KEY`` env var.
        model:     Model name. Falls back to ``OPENAI_MODEL`` env var, then
                   ``gpt-4o-mini``.
        timeout:   HTTP request timeout in seconds.
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
        timeout: int = 30,
    ) -> None:
        # None → read from env; "" → explicitly empty (no fallback)
        self.api_key: str = (
            api_key if api_key is not None else os.getenv("OPENAI_API_KEY", "")
        )
        self.model: str = (
            model
            if model is not None
            else os.getenv("OPENAI_MODEL", _DEFAULT_MODEL)
        )
        self.timeout = timeout

    # ── public helpers ────────────────────────────────────────────────────────

    def is_available(self) -> bool:
        """Return True when an API key is configured."""
        return bool(self.api_key)

    # ── core methods ──────────────────────────────────────────────────────────

    def query(
        self,
        messages: List[Dict[str, str]],
        max_tokens: int = _DEFAULT_MAX_TOKENS,
        temperature: float = 0.7,
    ) -> Optional[str]:
        """
        Send a chat-completions request and return the assistant reply.

        Args:
            messages:   List of ``{"role": ..., "content": ...}`` dicts.
            max_tokens: Maximum tokens in the completion.
            temperature: Sampling temperature.

        Returns:
            The assistant message text, or ``None`` on failure.
        """
        if not self.is_available():
            return None

        payload: Dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        try:
            resp = requests.post(
                _OPENAI_CHAT_URL,
                headers=headers,
                json=payload,
                timeout=self.timeout,
            )
            resp.raise_for_status()
            data = resp.json()
            return data["choices"][0]["message"]["content"]
        except Exception as exc:
            log.debug("[OpenAI] query failed: %s", exc)
            return None

    def query_llm(
        self,
        messages: List[Dict[str, str]],
        max_tokens: int = _DEFAULT_MAX_TOKENS,
    ) -> Optional[str]:
        """Alias used by modules that call the HFLLMAdapter interface."""
        return self.query(messages, max_tokens=max_tokens)

    def generate_code(
        self,
        language: str,
        purpose: str,
        context: str = "",
        max_tokens: int = _DEFAULT_MAX_TOKENS,
    ) -> str:
        """
        Generate code for the given language and purpose.

        Matches the ``HFLLMAdapter.generate_code()`` signature so the two
        adapters are interchangeable in the code-generation pipeline.

        Returns:
            Generated code string, or empty string on failure.
        """
        system_msg = (
            f"You are an expert {language} programmer. "
            "Write clean, functional, well-commented code. "
            "Return ONLY the code, no explanations."
        )
        user_parts = [f"Language: {language}", f"Task: {purpose}"]
        if context:
            user_parts.append(f"Context:\n{context[:600]}")
        user_msg = "\n\n".join(user_parts)

        result = self.query(
            messages=[
                {"role": "system", "content": system_msg},
                {"role": "user", "content": user_msg},
            ],
            max_tokens=max_tokens,
        )
        return result or ""


if __name__ == "__main__":
    print('Running openai_adapter.py')
