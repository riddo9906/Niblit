#!/usr/bin/env python3
"""
modules/ruflo_adapter.py — HTTP adapter for Ruflo-backed inference in Niblit.

Ruflo currently presents itself primarily as a TypeScript CLI/MCP orchestration
platform rather than as a Python SDK. Niblit therefore integrates Ruflo through
an HTTP bridge that can target either:

* an OpenAI-compatible chat completions endpoint exposed behind a Ruflo stack
* a generic Ruflo HTTP endpoint that accepts prompt/system/max_tokens JSON

The adapter degrades gracefully: when the URL is unset or the response cannot be
parsed into plain text, ``None`` is returned so callers can fall back.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any

import requests

log = logging.getLogger("RufloAdapter")

_DEFAULT_CHAT_PATH = "/v1/chat/completions"
_DEFAULT_TIMEOUT = 60
_DEFAULT_API_FORMAT = "openai"
_DEFAULT_MAX_TOKENS = int(
    os.getenv("NIBLIT_PROVIDER_MAX_TOKENS", os.getenv("NIBLIT_LOCAL_MAX_NEW", "512"))
)


def _normalize_url(value: str) -> str:
    """Return a normalized base URL or endpoint with no trailing slash."""
    return (value or "").strip().rstrip("/")


class RufloAdapter:
    """Thin HTTP client for Ruflo-backed inference."""

    def __init__(
        self,
        api_url: str | None = None,
        api_key: str | None = None,
        model: str | None = None,
        timeout: int | None = None,
        api_format: str | None = None,
        chat_path: str | None = None,
    ) -> None:
        self.api_url = _normalize_url(api_url if api_url is not None else os.getenv("RUFLO_API_URL", ""))
        self.api_key = api_key if api_key is not None else os.getenv("RUFLO_API_KEY", "")
        self.model = model if model is not None else os.getenv("RUFLO_MODEL", "")
        self.timeout = int(
            timeout if timeout is not None else os.getenv("RUFLO_TIMEOUT", str(_DEFAULT_TIMEOUT))
        )
        self.api_format = (
            api_format if api_format is not None else os.getenv("RUFLO_API_FORMAT", _DEFAULT_API_FORMAT)
        ).strip().lower()
        self.chat_path = (chat_path if chat_path is not None else os.getenv("RUFLO_CHAT_PATH", _DEFAULT_CHAT_PATH)).strip()

    def is_available(self) -> bool:
        """Return True when a Ruflo API URL is configured."""
        return bool(self.api_url)

    def generate(
        self,
        prompt: str,
        system: str = "",
        max_tokens: int = _DEFAULT_MAX_TOKENS,
    ) -> str | None:
        """Send a generation request and return plain text on success."""
        if not self.is_available():
            return None

        payload = self._build_payload(prompt=prompt, system=system, max_tokens=max_tokens)
        headers = self._build_headers()
        endpoint = self._resolve_endpoint()

        try:
            response = requests.post(
                endpoint,
                headers=headers,
                json=payload,
                timeout=self.timeout,
            )
            response.raise_for_status()
            return self._extract_text(response)
        except Exception as exc:
            log.debug("[Ruflo] request failed: %s", exc)
            return None

    def _resolve_endpoint(self) -> str:
        """Resolve the endpoint URL for the configured API format."""
        if self.api_format == "openai":
            if self.api_url.endswith("/chat/completions"):
                return self.api_url
            if self.chat_path.startswith(("http://", "https://")):
                return _normalize_url(self.chat_path)
            if self.chat_path.startswith("/"):
                return f"{self.api_url}{self.chat_path}"
            return f"{self.api_url}/{self.chat_path}"
        return self.api_url

    def _build_headers(self) -> dict[str, str]:
        """Build HTTP headers for the Ruflo request."""
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    def _build_payload(self, prompt: str, system: str, max_tokens: int) -> dict[str, Any]:
        """Build a request payload matching the configured Ruflo API format."""
        if self.api_format == "openai":
            messages = []
            if system.strip():
                messages.append({"role": "system", "content": system})
            messages.append({"role": "user", "content": prompt})

            payload: dict[str, Any] = {
                "messages": messages,
                "max_tokens": max_tokens,
            }
            if self.model:
                payload["model"] = self.model
            return payload

        payload = {
            "prompt": prompt,
            "system": system,
            "max_tokens": max_tokens,
        }
        if self.model:
            payload["model"] = self.model
        return payload

    def _extract_text(self, response: requests.Response) -> str | None:
        """Normalize multiple likely Ruflo response shapes into plain text."""
        try:
            data = response.json()
        except ValueError:
            text = response.text.strip()
            return text or None

        content = self._extract_from_payload(data)
        return content.strip() if isinstance(content, str) and content.strip() else None

    def _extract_from_payload(self, payload: Any) -> str | None:
        """Recursively extract text from OpenAI-style or generic JSON payloads."""
        if isinstance(payload, str):
            return payload

        if isinstance(payload, list):
            parts = [part for item in payload if (part := self._extract_from_payload(item))]
            return "\n".join(parts) if parts else None

        if not isinstance(payload, dict):
            return None

        choices = payload.get("choices")
        if isinstance(choices, list) and choices:
            message = choices[0].get("message") if isinstance(choices[0], dict) else None
            if isinstance(message, dict):
                content = message.get("content")
                extracted = self._extract_from_payload(content)
                if extracted:
                    return extracted
            text = choices[0].get("text") if isinstance(choices[0], dict) else None
            if isinstance(text, str) and text.strip():
                return text

        for key in ("response", "output", "text", "content", "message", "result", "answer"):
            if key in payload:
                extracted = self._extract_from_payload(payload[key])
                if extracted:
                    return extracted

        for key in ("data",):
            if key in payload:
                extracted = self._extract_from_payload(payload[key])
                if extracted:
                    return extracted

        return None


if __name__ == "__main__":
    print(json.dumps({"available": RufloAdapter().is_available()}))
