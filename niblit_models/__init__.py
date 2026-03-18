# niblit_models/__init__.py
"""
niblit_models — Niblit LLM adapter package.

Provides thin, dependency-safe wrappers around external LLM providers so they
can be used interchangeably throughout the Niblit pipeline.

Available adapters
------------------
ClaudeEngine  — Anthropic Claude via :class:`~modules.anthropic_adapter.AnthropicAdapter`.
"""

from niblit_models.claude_engine import ClaudeEngine

__all__ = ["ClaudeEngine"]
