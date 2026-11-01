#!/usr/bin/env python3
"""
OpenAI Responses adapter for Niblit, preserving its query/code interfaces.

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
import re
import time
from typing import Any, Dict, List, Optional

import requests

log = logging.getLogger("OpenAIAdapter")

_OPENAI_CHAT_URL = "https://api.openai.com/v1/chat/completions"
_OPENAI_RESPONSES_URL = "https://api.openai.com/v1/responses"
_DEFAULT_MODEL = "gpt-4o-mini"
_DEFAULT_MAX_TOKENS = 800


class OpenAIAdapter:
    """
    Responses API client with an explicit legacy Chat Completions mode.

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
        *,
        api_mode: str | None = None,
        max_retries: int = 0,
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
        self.timeout = max(1, min(float(timeout), 180))
        self.api_mode = api_mode or os.getenv("OPENAI_API_MODE", "responses")
        if self.api_mode not in {"responses", "chat_completions"}:
            raise ValueError("OPENAI_API_MODE must be responses or chat_completions")
        self.max_retries = max(0, min(int(max_retries), 2))
        self.last_error = None
        self.last_response = None

    # ── public helpers ────────────────────────────────────────────────────────

    def is_available(self) -> bool:
        """Configuration only; a completed request establishes actual access."""
        return bool(self.api_key.strip())

    # ── core methods ──────────────────────────────────────────────────────────

    def _error(self, code, message, status=None, request_id=None):
        self.last_error = {"code": code, "message": message, "status_code": status, "request_id": request_id}
        log.warning("[OpenAI] %s (HTTP %s)", code, status or "n/a")
        return None

    def complete(self, messages, max_tokens=_DEFAULT_MAX_TOKENS, temperature=None):
        """Normalize Responses output without executing tools or changing models.

        No prompts/keys/raw provider errors are logged. Responses storage is
        disabled; Niblit's own conversation store remains authoritative.
        """
        self.last_error = self.last_response = None
        if not self.is_available():
            return self._error("key_missing", "Set OPENAI_API_KEY in the private server environment.")
        if not isinstance(max_tokens, int) or isinstance(max_tokens, bool) or not 1 <= max_tokens <= 32768:
            return self._error("invalid_limit", "Output token limit must be between 1 and 32768.")
        if not isinstance(messages, list) or not messages or any(not isinstance(m, dict) or m.get("role") not in {"system", "developer", "user", "assistant"} or not isinstance(m.get("content"), str) for m in messages):
            return self._error("invalid_messages", "Only text conversation messages are supported; tools require the governed runtime.")
        if temperature is not None and (not isinstance(temperature, (float, int)) or not 0 <= temperature <= 2):
            return self._error("invalid_temperature", "Temperature must be between 0 and 2.")
        payload = {"model": self.model, "store": False}
        normalized = [{"role": m["role"], "content": m["content"]} for m in messages]
        if self.api_mode == "responses":
            endpoint = _OPENAI_RESPONSES_URL
            payload.update(input=normalized, max_output_tokens=max_tokens)
            if self.model.startswith('gpt-6'):
                effort = os.getenv('OPENAI_REASONING_EFFORT', 'low')
                if effort not in ('low', 'medium', 'high', 'xhigh', 'max'):
                    return self._error('invalid_reasoning_effort', 'OPENAI_REASONING_EFFORT is invalid.')
                payload['reasoning'] = {'effort': effort}
        else:
            endpoint = _OPENAI_CHAT_URL
            payload.update(messages=normalized, max_completion_tokens=max_tokens)
        if temperature is not None and not self.model.startswith('gpt-6'):
            payload["temperature"] = temperature
        budget = None
        if os.getenv('OPENAI_BUDGET_ENFORCE', '1') != '0':
            from modules.openai_budget import OpenAIBudget, BudgetError
            budget = OpenAIBudget()
            try:
                preview = budget.preview(self.model, normalized, max_tokens)
                payload['max_output_tokens' if self.api_mode == 'responses' else 'max_completion_tokens'] = preview['max_output_tokens']
            except BudgetError as exc:
                return self._error('budget_blocked', str(exc))
        attempts = 0
        temperature_retry = False
        while True:
            reservation = None
            if budget:
                try:
                    reservation, _ = budget.reserve(self.model, normalized, max_tokens)
                except Exception as exc:
                    from modules.openai_budget import BudgetError
                    return self._error('budget_blocked', str(exc) if isinstance(exc, BudgetError) else 'The local API budget ledger is unavailable; no paid request was sent.')
            try:
                resp = requests.post(endpoint, headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}, json=payload, timeout=(5, self.timeout), allow_redirects=False)
            except requests.Timeout:
                if budget: budget.settle(reservation, uncertain=True)
                return self._error("timeout", "OpenAI timed out. The request was not automatically resubmitted.")
            except Exception:
                if budget: budget.settle(reservation, uncertain=True)
                return self._error("connection_error", "Could not reach OpenAI. Check the internet connection.")
            request_id = resp.headers.get("x-request-id", "")
            request_id = request_id[:128] if isinstance(request_id, str) and re.fullmatch(r"[A-Za-z0-9_-]*", request_id) else None
            try:
                data = resp.json()
            except Exception:
                if budget: budget.settle(reservation, uncertain=True)
                return self._error("invalid_response", "OpenAI returned an unreadable response.", request_id=request_id)
            if not isinstance(data, dict):
                if budget: budget.settle(reservation, uncertain=True)
                return self._error("invalid_response", "OpenAI returned an unexpected response format.", request_id=request_id)
            usage = data.get('usage') or None
            if self.api_mode == 'chat_completions' and isinstance(usage, dict):
                usage = {'input_tokens': usage.get('prompt_tokens', 0), 'output_tokens': usage.get('completion_tokens', 0),
                         'input_tokens_details': usage.get('prompt_tokens_details', {})}
            cost = budget.settle(reservation, usage, uncertain=200 <= resp.status_code < 300 or resp.status_code >= 500) if budget else None
            if not 200 <= resp.status_code < 300:
                error = data.get("error") or {}
                code = error.get("code") if isinstance(error, dict) else None
                param = error.get("param") if isinstance(error, dict) else None
                if resp.status_code == 400 and param == "temperature" and "temperature" in payload and not temperature_retry:
                    payload.pop("temperature"); temperature_retry = True
                    continue
                if resp.status_code in {429, 500, 502, 503, 504} and code != "insufficient_quota" and attempts < self.max_retries:
                    attempts += 1; time.sleep(0.5 * attempts)
                    continue
                if resp.status_code == 401:
                    return self._error("authentication_failed", "OpenAI rejected the key. Check the API key and project.", 401, request_id)
                if code in {"insufficient_quota", "billing_hard_limit_reached", "usage_limit_exceeded", "billing_not_active", "credit_balance_exhausted"}:
                    return self._error("quota_exhausted", "OpenAI API quota or billing credit is exhausted. API-key usage is separate from ChatGPT subscription usage.", resp.status_code, request_id)
                if resp.status_code in {403, 404}:
                    return self._error("model_access_denied", "The configured model or project is not available to this API key.", resp.status_code, request_id)
                return self._error("rate_limited" if resp.status_code == 429 else "provider_error", "OpenAI rejected the request or is temporarily unavailable. Check the configured model and API account.", resp.status_code, request_id)
            if data.get("status") in {"failed", "cancelled", "incomplete", "queued", "in_progress"} or data.get("error"):
                return self._error("response_not_completed", "OpenAI did not complete the response. The output budget may be too small for reasoning.", request_id=request_id)
            texts, refusal = [], False
            if self.api_mode == "responses":
                if not isinstance(data.get("output", []), list):
                    return self._error("invalid_response", "OpenAI returned an unexpected output format.", request_id=request_id)
                for item in data.get("output", []):
                    if not isinstance(item, dict):
                        continue
                    if item.get("type") != "message":
                        continue
                    for content in item.get("content", []):
                        if not isinstance(content, dict):
                            continue
                        if content.get("type") == "output_text" and isinstance(content.get("text"), str):
                            texts.append(content["text"])
                        elif content.get("type") == "refusal" and isinstance(content.get("refusal"), str):
                            texts.append(content["refusal"]); refusal = True
            else:
                text = (data.get("choices") or [{}])[0].get("message", {}).get("content")
                if isinstance(text, str): texts.append(text)
            answer = "\n".join(texts).strip()
            if not answer:
                return self._error("empty_response", "OpenAI returned no displayable text. No tool call was executed.", request_id=request_id)
            result = {"text": answer, "model": data.get("model") or self.model, "response_id": data.get("id"), "request_id": request_id, "usage": data.get("usage", {}), "refusal": refusal, "api_mode": self.api_mode, 'estimated_cost_usd': cost}
            self.last_response = {k: v for k, v in result.items() if k != "text"}
            return result

    def query(self, messages, max_tokens=_DEFAULT_MAX_TOKENS, temperature=None):
        result = self.complete(messages, max_tokens=max_tokens, temperature=temperature)
        return result["text"] if result else None

    def generate(self, prompt, system="", max_tokens=_DEFAULT_MAX_TOKENS):
        messages = ([{"role": "system", "content": system}] if system else []) + [{"role": "user", "content": prompt}]
        return self.query(messages, max_tokens=max_tokens)

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
