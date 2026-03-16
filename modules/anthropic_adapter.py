#!/usr/bin/env python3
"""
modules/anthropic_adapter.py — Anthropic Claude LLM adapter for Niblit.

Follows the same interface contract as HFLLMAdapter and OpenAIAdapter so it
can be used as a drop-in alternative in the autonomous learning pipeline.

Activation::

    ANTHROPIC_API_KEY=sk-ant-...            # Required — set in .env
    ANTHROPIC_MODEL=claude-3-haiku-20240307 # Optional

Degrades gracefully when the key is absent or the request fails.
"""

import logging
import os
from typing import Any, Dict, List, Optional

import requests

log = logging.getLogger("AnthropicAdapter")

_ANTHROPIC_MESSAGES_URL = "https://api.anthropic.com/v1/messages"
_ANTHROPIC_API_VERSION = "2023-06-01"
_DEFAULT_MODEL = "claude-3-haiku-20240307"
_DEFAULT_MAX_TOKENS = 800


class AnthropicAdapter:
    """
    Thin wrapper around the Anthropic Messages API.

    Args:
        api_key:  Anthropic API key. Falls back to ``ANTHROPIC_API_KEY`` env var.
        model:    Model name. Falls back to ``ANTHROPIC_MODEL`` env var, then
                  ``claude-3-haiku-20240307``.
        timeout:  HTTP request timeout in seconds.
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
        timeout: int = 30,
    ) -> None:
        self.api_key: str = (
            api_key if api_key is not None else os.getenv("ANTHROPIC_API_KEY", "")
        )
        self.model: str = (
            model
            if model is not None
            else os.getenv("ANTHROPIC_MODEL", _DEFAULT_MODEL)
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
        system: str = "",
        max_tokens: int = _DEFAULT_MAX_TOKENS,
    ) -> Optional[str]:
        """
        Send a messages request and return the assistant reply.

        Args:
            messages:   List of ``{"role": ..., "content": ...}`` dicts.
            system:     Optional system prompt string.
            max_tokens: Maximum tokens in the completion.

        Returns:
            The assistant text, or ``None`` on failure.
        """
        if not self.is_available():
            return None

        payload: Dict[str, Any] = {
            "model": self.model,
            "max_tokens": max_tokens,
            "messages": messages,
        }
        if system:
            payload["system"] = system

        headers = {
            "x-api-key": self.api_key,
            "anthropic-version": _ANTHROPIC_API_VERSION,
            "content-type": "application/json",
        }

        try:
            resp = requests.post(
                _ANTHROPIC_MESSAGES_URL,
                headers=headers,
                json=payload,
                timeout=self.timeout,
            )
            resp.raise_for_status()
            data = resp.json()
            # Response: {"content": [{"type": "text", "text": "..."}], ...}
            content = data.get("content") or []
            for block in content:
                if isinstance(block, dict) and block.get("type") == "text":
                    return block.get("text", "")
            return None
        except Exception as exc:
            log.debug("[Anthropic] query failed: %s", exc)
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

        Matches the ``HFLLMAdapter.generate_code()`` signature.

        Returns:
            Generated code string, or empty string on failure.
        """
        system_prompt = (
            f"You are an expert {language} programmer. "
            "Write clean, functional, well-commented code. "
            "Return ONLY the code, no explanations."
        )
        user_parts = [f"Language: {language}", f"Task: {purpose}"]
        if context:
            user_parts.append(f"Context:\n{context[:600]}")
        user_msg = "\n\n".join(user_parts)

        result = self.query(
            messages=[{"role": "user", "content": user_msg}],
            system=system_prompt,
            max_tokens=max_tokens,
        )
        return result or ""
