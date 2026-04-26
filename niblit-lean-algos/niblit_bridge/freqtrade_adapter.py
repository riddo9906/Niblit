"""
niblit_bridge/freqtrade_adapter.py — HTTP adapter that calls Niblit's
/trade/signal endpoint from inside a Freqtrade strategy.

This module is intentionally lightweight:
  • stdlib only (urllib.request) for the HTTP call so it works without
    installing requests / httpx inside the Freqtrade venv.
  • A requests-based helper is also provided and used when requests is
    available, for better timeout and retry handling.
  • Falls back to "hold" on ANY error so a Freqtrade backtest/dryrun never
    crashes because of a Niblit connectivity issue.

Usage inside a Freqtrade strategy
──────────────────────────────────
    from niblit_bridge.freqtrade_adapter import NiblitHTTPAdapter

    class MyStrategy(IStrategy):
        def __init__(self, config):
            super().__init__(config)
            self._niblit = NiblitHTTPAdapter()   # reads NIBLIT_API_URL

        def populate_entry_trend(self, dataframe, metadata):
            pair = metadata["pair"]
            signal = self._niblit.get_signal(pair, dataframe)
            if signal == "buy":
                dataframe.loc[dataframe.index[-1], "enter_long"] = 1
            return dataframe

        def populate_exit_trend(self, dataframe, metadata):
            pair = metadata["pair"]
            signal = self._niblit.get_signal(pair, dataframe)
            if signal == "sell":
                dataframe.loc[dataframe.index[-1], "exit_long"] = 1
            return dataframe

Environment variables
─────────────────────
  NIBLIT_API_URL          Base URL of the Niblit service (default: http://127.0.0.1:8000)
  NIBLIT_API_KEY          Optional X-API-Key header value
  NIBLIT_SIGNAL_TIMEOUT   HTTP timeout in seconds (default: 5)
  NIBLIT_SIGNAL_RETRIES   Number of retry attempts on failure (default: 2)
"""

from __future__ import annotations

import json
import logging
import os
import time
import urllib.error
import urllib.request
from typing import Any, Dict, List, Optional

log = logging.getLogger("NiblitHTTPAdapter")

_DEFAULT_API_URL = "http://127.0.0.1:8000"
_DEFAULT_TIMEOUT = 5
_DEFAULT_RETRIES = 2

# Try to import requests for better HTTP handling; fall back to urllib.
try:
    import requests as _requests
    _REQUESTS_AVAILABLE = True
except ImportError:
    _requests = None  # type: ignore[assignment]
    _REQUESTS_AVAILABLE = False


class NiblitHTTPAdapter:
    """Calls Niblit's /trade/signal endpoint and returns buy/sell/hold.

    Parameters
    ----------
    api_url:
        Base URL of the Niblit service.  Defaults to the ``NIBLIT_API_URL``
        environment variable, or ``http://127.0.0.1:8000``.
    api_key:
        Optional API key sent as ``X-API-Key`` header.  Defaults to the
        ``NIBLIT_API_KEY`` environment variable.
    timeout:
        HTTP request timeout in seconds.  Defaults to ``NIBLIT_SIGNAL_TIMEOUT``
        env var, or 5 seconds.
    retries:
        Number of retry attempts when the request fails.  Defaults to
        ``NIBLIT_SIGNAL_RETRIES`` env var, or 2.
    """

    def __init__(
        self,
        api_url: Optional[str] = None,
        api_key: Optional[str] = None,
        timeout: Optional[int] = None,
        retries: Optional[int] = None,
    ) -> None:
        self.api_url: str = (
            api_url
            or os.environ.get("NIBLIT_API_URL", _DEFAULT_API_URL)
        ).rstrip("/")
        self.api_key: Optional[str] = api_key or os.environ.get("NIBLIT_API_KEY") or None
        self.timeout: int = int(
            timeout if timeout is not None
            else os.environ.get("NIBLIT_SIGNAL_TIMEOUT", _DEFAULT_TIMEOUT)
        )
        self.retries: int = int(
            retries if retries is not None
            else os.environ.get("NIBLIT_SIGNAL_RETRIES", _DEFAULT_RETRIES)
        )
        self._signal_url = f"{self.api_url}/trade/signal"
        self._feedback_url = f"{self.api_url}/trade/feedback"

    # ── public API ────────────────────────────────────────────────────────────

    def get_signal(
        self,
        pair: str,
        dataframe: Any = None,
        timeframe: str = "1h",
        features: Optional[Dict[str, float]] = None,
    ) -> str:
        """Return Niblit's trading recommendation: "buy", "sell", or "hold".

        Parameters
        ----------
        pair:
            Trading pair string, e.g. ``"BTC/USDT"``.
        dataframe:
            Optional pandas DataFrame with OHLCV + indicator columns.  The
            last row is extracted and sent as ``last_candle``.
        timeframe:
            Candle timeframe string passed to Niblit.
        features:
            Additional feature dict merged into the request payload.

        Returns
        -------
        str
            ``"buy"``, ``"sell"``, or ``"hold"``.  Always returns ``"hold"``
            on any error so the calling strategy can proceed safely.
        """
        result = self.get_signal_with_meta(pair, dataframe, timeframe, features)
        return result.get("action", "hold")

    def get_signal_with_meta(
        self,
        pair: str,
        dataframe: Any = None,
        timeframe: str = "1h",
        features: Optional[Dict[str, float]] = None,
    ) -> Dict[str, Any]:
        """Return Niblit's full signal response including confidence and reasoning.

        This is the richer version of :meth:`get_signal` that exposes the full
        JSON response from ``POST /trade/signal``, including ``confidence``,
        ``metadata.reason``, ``metadata.win_rate``, and ``metadata.sample_size``.

        Returns a dict with at least ``action`` (``"buy"``/``"sell"``/``"hold"``)
        and ``confidence`` (float 0–1).  Returns a safe fallback dict on any error.
        """
        payload: Dict[str, Any] = {
            "pair": pair,
            "timeframe": timeframe,
        }

        # Extract last candle from dataframe if provided
        if dataframe is not None:
            try:
                last = dataframe.iloc[-1]
                candle: Dict[str, float] = {}
                for col in ("open", "high", "low", "close", "volume",
                            "rsi", "macd", "macdsignal", "macdhist",
                            "ema_fast", "ema_slow", "atr", "bb_upper",
                            "bb_lower", "bb_mid"):
                    if col in last.index:
                        val = last[col]
                        try:
                            candle[col] = float(val)
                        except (TypeError, ValueError):
                            pass
                if candle:
                    payload["last_candle"] = candle
            except Exception as exc:
                log.debug("Failed to extract last candle: %s", exc)

        if features:
            payload["features"] = features

        for attempt in range(max(1, self.retries)):
            try:
                resp = self._post(self._signal_url, payload)
                action = resp.get("action", "hold")
                if action not in ("buy", "sell", "hold"):
                    action = "hold"
                confidence = float(resp.get("confidence", 0.5))
                log.info(
                    "[NiblitHTTPAdapter] signal for %s: %s (confidence=%.2f, n=%d)",
                    pair, action, confidence,
                    resp.get("metadata", {}).get("sample_size", 0) if isinstance(resp.get("metadata"), dict) else 0,
                )
                return {"action": action, "confidence": confidence, "metadata": resp.get("metadata", {})}
            except Exception as exc:
                log.warning(
                    "[NiblitHTTPAdapter] /trade/signal attempt %d/%d failed: %s",
                    attempt + 1, self.retries, exc,
                )
                if attempt < self.retries - 1:
                    time.sleep(0.5)

        log.warning(
            "[NiblitHTTPAdapter] All retries exhausted for %s — falling back to 'hold'", pair
        )
        return {"action": "hold", "confidence": 0.5, "metadata": {}}

    def send_feedback(
        self,
        pair: str,
        action: str,
        outcome: str,
        pnl_pct: Optional[float] = None,
        features: Optional[Dict[str, float]] = None,
        timeframe: str = "1h",
    ) -> bool:
        """Send trade outcome feedback to Niblit's /trade/feedback endpoint.

        Parameters
        ----------
        pair:
            Trading pair, e.g. ``"BTC/USDT"``.
        action:
            The action that was executed: ``"buy"`` / ``"sell"`` / ``"hold"``.
        outcome:
            Trade result: ``"profit"`` / ``"loss"`` / ``"neutral"``.
        pnl_pct:
            Optional percentage P&L (e.g. ``2.5`` for +2.5%).
        features:
            Optional snapshot of indicator values at trade time.  When provided,
            these are stored in the KB so Niblit can learn from the pattern.
        timeframe:
            Candle timeframe for KB pattern bucketing.

        Returns
        -------
        bool
            True if Niblit accepted the feedback, False on any error.
        """
        payload: Dict[str, Any] = {
            "pair": pair,
            "action": action,
            "outcome": outcome,
            "timeframe": timeframe,
        }
        if pnl_pct is not None:
            payload["pnl_pct"] = pnl_pct
        if features:
            payload["features"] = features

        return self._call_feedback(payload)

    def is_available(self) -> bool:
        """Return True if the Niblit service appears reachable."""
        try:
            health_url = f"{self.api_url}/health"
            if _REQUESTS_AVAILABLE:
                resp = _requests.get(health_url, timeout=self.timeout)
                return resp.status_code < 500
            req = urllib.request.Request(health_url)
            with urllib.request.urlopen(req, timeout=self.timeout):
                return True
        except Exception:
            return False

    # ── internal helpers ──────────────────────────────────────────────────────

    def _call_feedback(self, payload: Dict[str, Any]) -> bool:
        """POST to /trade/feedback; return True on success."""
        try:
            self._post(self._feedback_url, payload)
            return True
        except Exception as exc:
            log.warning("[NiblitHTTPAdapter] /trade/feedback error: %s", exc)
            return False

    def _post(self, url: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Perform an HTTP POST with JSON body.  Returns parsed response dict."""
        body = json.dumps(payload).encode("utf-8")
        headers: Dict[str, str] = {"Content-Type": "application/json"}
        if self.api_key:
            headers["X-API-Key"] = self.api_key

        if _REQUESTS_AVAILABLE:
            resp = _requests.post(url, data=body, headers=headers, timeout=self.timeout)
            resp.raise_for_status()
            return resp.json()

        req = urllib.request.Request(url, data=body, headers=headers, method="POST")
        with urllib.request.urlopen(req, timeout=self.timeout) as resp:
            raw = resp.read().decode("utf-8")
        return json.loads(raw)


if __name__ == "__main__":
    print("Running freqtrade_adapter.py")
