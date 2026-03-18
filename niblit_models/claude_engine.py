#!/usr/bin/env python3
"""
niblit_models/claude_engine.py — Anthropic Claude integration for Niblit.

Wraps :class:`~modules.anthropic_adapter.AnthropicAdapter` with:
  - Context injection from Qdrant / SemanticAgent results
  - Structured prompt building (system + context + user query)
  - Agent-compatible response format
  - Graceful degradation when the API key is absent

Activation::

    ANTHROPIC_API_KEY=sk-ant-...            # Required
    ANTHROPIC_MODEL=claude-3-haiku-20240307 # Optional (default)

Usage::

    from niblit_models.claude_engine import ClaudeEngine
    engine = ClaudeEngine()
    response = engine.generate("What is asyncio?", context=[
        {"text": "asyncio is a Python library for async I/O", "score": 0.9}
    ])
"""

import logging
import os
from typing import Any, Dict, List, Optional

logger = logging.getLogger("Niblit.ClaudeEngine")

_DEFAULT_MODEL = os.getenv("ANTHROPIC_MODEL", "claude-3-haiku-20240307")
_DEFAULT_MAX_TOKENS = 1000
_SYSTEM_PROMPT = (
    "You are Niblit, an advanced autonomous AI system. "
    "Use the provided context to answer accurately and technically. "
    "When context is available, ground your answer in it. "
    "Be precise, concise, and helpful."
)


class ClaudeEngine:
    """
    Niblit's Claude LLM engine with context-injection support.

    Designed to receive Qdrant retrieval results as *context* and inject
    them into the prompt so that Claude can ground its responses in Niblit's
    accumulated knowledge base.

    Args:
        api_key:    Anthropic API key.  Falls back to ``ANTHROPIC_API_KEY`` env var.
        model:      Model name.  Falls back to ``ANTHROPIC_MODEL`` env var.
        max_tokens: Default maximum tokens in the completion.
        timeout:    HTTP request timeout passed to the underlying adapter.
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
        max_tokens: int = _DEFAULT_MAX_TOKENS,
        timeout: int = 30,
    ) -> None:
        self._api_key = api_key or os.getenv("ANTHROPIC_API_KEY", "")
        self._model = model or _DEFAULT_MODEL
        self._max_tokens = max_tokens
        self._timeout = timeout
        self._adapter: Optional[Any] = None
        self._adapter_initialised = False

    # ── lazy init ─────────────────────────────────────────────────────────────

    def _get_adapter(self) -> Optional[Any]:
        """Lazily initialise the AnthropicAdapter."""
        if self._adapter_initialised:
            return self._adapter
        self._adapter_initialised = True
        try:
            from modules.anthropic_adapter import AnthropicAdapter  # type: ignore[import]
            self._adapter = AnthropicAdapter(
                api_key=self._api_key or None,
                model=self._model,
                timeout=self._timeout,
            )
            if self._adapter.is_available():
                logger.info("[ClaudeEngine] Anthropic adapter ready (model=%s)", self._model)
            else:
                logger.debug("[ClaudeEngine] ANTHROPIC_API_KEY not set — Claude disabled")
        except Exception as exc:
            logger.debug("[ClaudeEngine] AnthropicAdapter unavailable: %s", exc)
            self._adapter = None
        return self._adapter

    # ── public helpers ────────────────────────────────────────────────────────

    def is_available(self) -> bool:
        """Return True when an Anthropic API key is configured."""
        adapter = self._get_adapter()
        return adapter is not None and adapter.is_available()

    # ── core generation ───────────────────────────────────────────────────────

    def generate(
        self,
        query: str,
        context: Optional[List[Dict[str, Any]]] = None,
        max_tokens: Optional[int] = None,
        system: str = "",
    ) -> str:
        """
        Generate a response for *query*, optionally grounded in *context*.

        Args:
            query:      The user's question or task description.
            context:    List of ``{"text": str, "score": float, ...}`` dicts
                        returned by :meth:`~niblit_agents.semantic_agent.SemanticAgent.retrieve_context`.
                        When provided, the snippets are injected into the prompt.
            max_tokens: Override the default token budget.
            system:     Custom system prompt (falls back to Niblit default).

        Returns:
            The assistant's response string, or an empty string on failure.
        """
        adapter = self._get_adapter()
        if adapter is None or not adapter.is_available():
            return ""

        context_text = _format_context(context)

        prompt_parts = []
        if context_text:
            prompt_parts.append(f"Context:\n{context_text}")
        prompt_parts.append(f"User Query:\n{query}")
        prompt_parts.append("Provide a precise and technical answer.")
        user_message = "\n\n".join(prompt_parts)

        result = adapter.query(
            messages=[{"role": "user", "content": user_message}],
            system=system or _SYSTEM_PROMPT,
            max_tokens=max_tokens or self._max_tokens,
        )
        return result or ""

    def generate_code(
        self,
        language: str,
        purpose: str,
        context: Optional[List[Dict[str, Any]]] = None,
        max_tokens: Optional[int] = None,
    ) -> str:
        """
        Generate code using Claude, optionally informed by semantic context.

        Args:
            language:   Target programming language.
            purpose:    Description of what the code should do.
            context:    Qdrant retrieval results for additional grounding.
            max_tokens: Override the default token budget.

        Returns:
            Generated code string, or empty string on failure.
        """
        adapter = self._get_adapter()
        if adapter is None or not adapter.is_available():
            return ""

        context_str = _format_context(context)
        return adapter.generate_code(
            language=language,
            purpose=purpose,
            context=context_str,
            max_tokens=max_tokens or self._max_tokens,
        )


# ── helpers ───────────────────────────────────────────────────────────────────

def _format_context(context: Optional[List[Dict[str, Any]]]) -> str:
    """Format a list of retrieval results as a readable context block."""
    if not context:
        return ""
    lines = []
    for item in context:
        text = item.get("text", "")
        if text:
            lines.append(f"- {text[:400]}")
    return "\n".join(lines)


if __name__ == "__main__":
    engine = ClaudeEngine()
    print(f"ClaudeEngine available: {engine.is_available()}")
    if engine.is_available():
        response = engine.generate(
            "What is Python asyncio?",
            context=[{"text": "asyncio provides a framework for async I/O"}],
        )
        print(f"Response: {response[:200]}")
