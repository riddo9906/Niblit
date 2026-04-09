#!/usr/bin/env python3
"""
GitHub Models client for Niblit.

Provides a slim, production-ready wrapper around the GitHub Models API so
Niblit's bots can offload heavy natural-language reasoning and code suggestions
without adding any external dependencies (uses stdlib ``urllib`` only).

Key goals:
  * Zero extra dependencies — only Python stdlib.
  * Env-based configuration, consistent with Niblit's GitHub REST clients.
  * JSON-in / JSON-out: callers pass structured payloads, get structured
    responses back, not raw prompts.
  * Safe-by-default: advisory outputs only (no direct code writes).
  * Graceful fallback: all public helpers return empty/stub results instead
    of raising exceptions, so bots stay functional when the model is
    unavailable.

Environment variables:
    GITHUB_MODELS_TOKEN      Token for GitHub Models API.  Falls back to
                             GITHUB_TOKEN if not set.
    NIBLIT_GH_MODEL_NAME     Default model name (e.g. ``gpt-4.1-mini``).
    NIBLIT_GH_MODEL_MAX_TOKENS
                             Default max_tokens for responses (int).
    NIBLIT_GH_MODEL_BASE_URL
                             Override base URL if GitHub updates the endpoint.
    USE_GH_MODEL_REPORTS     Set to ``true`` to enable model-enhanced sections
                             across all bots.  Defaults to ``false``.
"""

from __future__ import annotations

import json
import logging
import os
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

DEFAULT_MODEL: str = os.environ.get("NIBLIT_GH_MODEL_NAME", "gpt-4.1-mini")
DEFAULT_MAX_TOKENS: int = int(os.environ.get("NIBLIT_GH_MODEL_MAX_TOKENS", "1024"))
DEFAULT_BASE_URL: str = os.environ.get(
    "NIBLIT_GH_MODEL_BASE_URL",
    "https://models.github.ai/v1",
)

# Honour GITHUB_MODELS_TOKEN first; fall back to the general GITHUB_TOKEN.
MODELS_TOKEN: str = (
    os.environ.get("GITHUB_MODELS_TOKEN", "")
    or os.environ.get("GITHUB_TOKEN", "")
)

# Global on/off switch — bots check this before calling the client.
USE_GH_MODEL_REPORTS: bool = (
    os.environ.get("USE_GH_MODEL_REPORTS", "false").lower() == "true"
)


@dataclass
class ModelConfig:
    """Runtime configuration for a GitHubModelsClient instance."""

    model: str = field(default_factory=lambda: DEFAULT_MODEL)
    max_tokens: int = field(default_factory=lambda: DEFAULT_MAX_TOKENS)
    temperature: float = 0.2
    timeout: int = 60  # seconds


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------


class GitHubModelsClient:
    """Thin, stdlib-only wrapper around the GitHub Models chat-completions API."""

    def __init__(
        self,
        config: Optional[ModelConfig] = None,
        base_url: str = DEFAULT_BASE_URL,
        token: Optional[str] = None,
    ) -> None:
        self.config = config or ModelConfig()
        self.base_url = base_url.rstrip("/")
        self.token = token or MODELS_TOKEN
        if not self.token:
            log.warning(
                "[GitHubModelsClient] No GITHUB_MODELS_TOKEN or GITHUB_TOKEN set. "
                "Model calls will fail until configured."
            )

    # ------------------------------------------------------------------
    # Core request helper
    # ------------------------------------------------------------------

    def _request(
        self,
        messages: List[Dict[str, str]],
        model: Optional[str] = None,
        max_tokens: Optional[int] = None,
        temperature: Optional[float] = None,
        extra: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Send a chat-completions request to the GitHub Models API.

        Returns the parsed JSON response dict.
        Raises ``RuntimeError`` on configuration or HTTP errors.
        """
        if not self.token:
            raise RuntimeError(
                "GitHub Models token not configured. "
                "Set GITHUB_MODELS_TOKEN or GITHUB_TOKEN."
            )

        url = f"{self.base_url}/chat/completions"
        payload: Dict[str, Any] = {
            "model": model or self.config.model,
            "messages": messages,
            "max_tokens": (
                max_tokens if max_tokens is not None else self.config.max_tokens
            ),
            "temperature": (
                temperature if temperature is not None else self.config.temperature
            ),
        }
        if extra:
            payload.update(extra)

        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers = {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

        req = urllib.request.Request(url, data=body, headers=headers, method="POST")
        t0 = time.time()
        try:
            with urllib.request.urlopen(req, timeout=self.config.timeout) as resp:
                elapsed = time.time() - t0
                raw = resp.read().decode("utf-8", errors="replace")
                log.debug(
                    "[GitHubModelsClient] %s %.2fs HTTP 2xx",
                    payload.get("model"),
                    elapsed,
                )
        except urllib.error.HTTPError as exc:
            elapsed = time.time() - t0
            snippet = exc.read().decode("utf-8", errors="replace")[:500]
            raise RuntimeError(
                f"GitHub Models API error {exc.code}: {snippet}"
            ) from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"GitHub Models request failed: {exc}") from exc

        try:
            return json.loads(raw)
        except json.JSONDecodeError as exc:
            raise RuntimeError(
                "Failed to decode GitHub Models JSON response"
            ) from exc

    # ------------------------------------------------------------------
    # High-level helpers for Niblit use-cases
    # ------------------------------------------------------------------

    def summarise_repos(
        self,
        topic: str,
        repos: List[Dict[str, Any]],
        knowledge: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Summarise a batch of GitHub repos for research bots.

        Args:
            topic:     Original research topic (e.g. ``'ai operating system'``).
            repos:     List of repo-metadata dicts (full_name, stars, language,
                       topics, description, readme snippet, top_files, patterns…).
            knowledge: Optional knowledge-layer context (known_repos, past_topics,
                       insights…).

        Returns:
            Markdown-formatted summary string, or empty string on failure.
        """
        system_msg: Dict[str, str] = {
            "role": "system",
            "content": (
                "You are Niblit's research analyst. Given metadata about multiple "
                "GitHub repositories and optional knowledge-layer context, you must "
                "produce a clear, concise, and actionable Markdown report."
            ),
        }
        user_payload = {
            "topic": topic,
            "repos": repos,
            "knowledge": knowledge or {},
            "instructions": [
                "Summarise the most interesting repos in 1-3 paragraphs each.",
                "Highlight common patterns and notable outliers.",
                "Explain why these repos matter for Niblit's goals.",
                "Propose concrete next steps (what to explore, track, or build).",
            ],
        }
        user_msg: Dict[str, str] = {
            "role": "user",
            "content": json.dumps(user_payload, ensure_ascii=False),
        }
        resp = self._request([system_msg, user_msg])
        return self._extract_text(resp)

    def analyse_trading_strategies(
        self,
        repos: List[Dict[str, Any]],
        knowledge: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Analyse trading-related repos and return structured strategy cards.

        Each repo dict should contain fields already computed by
        ``ai_trading_bot.py`` (indicators, platforms, risk hints, etc.).

        Returns a dict with a ``strategies`` list, where each entry has::

            {
              "repo": "owner/name",
              "style": "trend-following | mean-reversion | arbitrage | ml-based",
              "risk_level": "low | medium | high",
              "key_signals": [...],
              "risk_controls": [...],
              "missing_controls": [...],
              "summary": "plain-English explanation"
            }

        Returns ``{"strategies": []}`` on failure.
        """
        system_msg: Dict[str, str] = {
            "role": "system",
            "content": (
                "You are a quantitative trading analyst helping the Niblit project. "
                "You receive structured summaries of trading-related GitHub repos and "
                "must infer their strategy style, risk level, key signals, and risk "
                "controls. Always respond with valid JSON."
            ),
        }
        user_payload = {
            "repos": repos,
            "knowledge": knowledge or {},
            "output_schema": {
                "strategies": [
                    {
                        "repo": "owner/name",
                        "style": "string",
                        "risk_level": "low|medium|high",
                        "key_signals": ["string"],
                        "risk_controls": ["string"],
                        "missing_controls": ["string"],
                        "summary": "string",
                    }
                ]
            },
        }
        user_msg: Dict[str, str] = {
            "role": "user",
            "content": json.dumps(user_payload, ensure_ascii=False),
        }
        resp = self._request(
            [system_msg, user_msg],
            extra={"response_format": {"type": "json_object"}},
        )
        text = self._extract_text(resp)
        try:
            return json.loads(text)
        except (json.JSONDecodeError, ValueError):
            log.warning(
                "[GitHubModelsClient] Trading analysis returned non-JSON; wrapping."
            )
            return {"raw": text}

    def generate_refactor_recipes(
        self,
        language: str,
        technique: str,
        examples: List[Dict[str, Any]],
        target_snippets: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        """Turn raw refactoring examples into general recipes + Niblit suggestions.

        Args:
            language:        Programming language (e.g. ``'python'``).
            technique:       High-level technique name (e.g. ``'list_comprehension'``).
            examples:        Snippets from ``github_code_search.find_refactoring_patterns``.
            target_snippets: Optional Niblit snippets to generate advice for::

                                 [{"file": "modules/github_sync.py", "code": "…"}]

        Returns::

            {
              "recipe": {
                  "language": "...",
                  "technique": "...",
                  "description": "...",
                  "before_example": "...",
                  "after_example": "...",
                  "pitfalls": ["..."],
              },
              "suggestions": [
                  {
                    "file": "path",
                    "summary": "plain-English description",
                    "pseudo_patch": "diff-style or bullet list"
                  },
              ]
            }

        Returns ``{}`` on failure.
        """
        system_msg: Dict[str, str] = {
            "role": "system",
            "content": (
                "You are a senior software engineer helping the Niblit project "
                "synthesize refactoring recipes from real GitHub examples. "
                "You must output VALID JSON only, following the given schema."
            ),
        }
        user_payload = {
            "language": language,
            "technique": technique,
            "examples": examples,
            "targets": target_snippets or [],
            "output_schema": {
                "recipe": {
                    "language": "string",
                    "technique": "string",
                    "description": "string",
                    "before_example": "string",
                    "after_example": "string",
                    "pitfalls": ["string"],
                },
                "suggestions": [
                    {
                        "file": "string",
                        "summary": "string",
                        "pseudo_patch": "string",
                    }
                ],
            },
        }
        user_msg: Dict[str, str] = {
            "role": "user",
            "content": json.dumps(user_payload, ensure_ascii=False),
        }
        resp = self._request(
            [system_msg, user_msg],
            extra={"response_format": {"type": "json_object"}},
        )
        text = self._extract_text(resp)
        try:
            return json.loads(text)
        except (json.JSONDecodeError, ValueError):
            log.warning(
                "[GitHubModelsClient] Refactor recipe returned non-JSON; wrapping."
            )
            return {"raw": text}

    def suggest_bot_improvements(
        self,
        bot_name: str,
        code_snippets: List[Dict[str, str]],
        niblit_goals: Optional[str] = None,
    ) -> str:
        """Critique and suggest improvements for a Niblit bot/module.

        Args:
            bot_name:      Human-readable name of the bot being analysed.
            code_snippets: List of ``{"file": "…", "code": "…"}`` dicts.
            niblit_goals:  Optional short description of Niblit's goals/constraints.

        Returns:
            Markdown-formatted improvement suggestions, or empty string on failure.
        """
        system_msg: Dict[str, str] = {
            "role": "system",
            "content": (
                "You are an experienced software architect reviewing an autonomous "
                "AI bot (part of the Niblit project). Provide clear, actionable "
                "Markdown suggestions for architectural cleanup, prompt improvements, "
                "and new capabilities. Be concise and prioritise by impact."
            ),
        }
        user_payload = {
            "bot_name": bot_name,
            "niblit_goals": niblit_goals or "Autonomous AI OS with self-improving capabilities",
            "code_snippets": code_snippets,
            "instructions": [
                "Identify architectural issues: separation of concerns, duplicate helpers.",
                "Suggest prompt/report template improvements (clearer headings, checklists).",
                "Propose new bots, phases, or capabilities.",
                "Keep each suggestion short (1-3 lines) and actionable.",
            ],
        }
        user_msg: Dict[str, str] = {
            "role": "user",
            "content": json.dumps(user_payload, ensure_ascii=False),
        }
        resp = self._request([system_msg, user_msg])
        return self._extract_text(resp)

    # ------------------------------------------------------------------
    # Utility
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_text(resp: Dict[str, Any]) -> str:
        """Extract the primary content string from a chat-completions response."""
        try:
            choices = resp.get("choices") or []
            if not choices:
                return ""
            msg = choices[0].get("message") or {}
            return msg.get("content", "") or ""
        except Exception:  # noqa: BLE001
            return ""

    def log_usage(self, resp: Dict[str, Any]) -> None:
        """Log token usage from a raw API response (for rate-limit monitoring)."""
        usage = resp.get("usage") or {}
        if usage:
            log.info(
                "[GitHubModelsClient] Token usage — prompt: %s, completion: %s, total: %s",
                usage.get("prompt_tokens", "?"),
                usage.get("completion_tokens", "?"),
                usage.get("total_tokens", "?"),
            )


# ---------------------------------------------------------------------------
# Singleton convenience
# ---------------------------------------------------------------------------

_client: Optional[GitHubModelsClient] = None


def get_github_models_client() -> GitHubModelsClient:
    """Return a module-level singleton GitHubModelsClient."""
    global _client  # noqa: PLW0603
    if _client is None:
        _client = GitHubModelsClient()
    return _client


if __name__ == "__main__":
    print('Running github_models_client.py')
