"""
niblit_bridge/connector.py — File-based Niblit ↔ LEAN signal bridge.

This module is intentionally dependency-free (stdlib only) so it can
run both inside a QuantConnect Cloud algorithm container and in a local
LEAN environment without any pip installs.

Signal file format (written by Niblit's modules/lean_algo_manager.py):

    {
        "signal":      "BUY" | "SELL" | "HOLD",
        "confidence":  0.0 – 1.0,
        "symbol":      "BTCUSDT",
        "price":       65432.10,
        "timestamp":   1713100000,
        "indicators": {
            "rsi": 45.2,
            "macd": 0.003,
            "ema_fast": 65000.0,
            "ema_slow": 64000.0,
            "atr": 800.0,
            "volume_ratio": 1.2
        },
        "regime":      "bullish" | "bearish" | "ranging",
        "risk_pct":    0.02
    }

The LEAN algorithm reads this file in on_data() and combines the
external signal with its own technical indicators.
"""

from __future__ import annotations

import json
import os
import time
from typing import Any, Dict, Optional


# Default path — overridden by env var NIBLIT_SIGNAL_FILE
_DEFAULT_SIGNAL_FILE = os.environ.get(
    "NIBLIT_SIGNAL_FILE",
    os.path.join(os.environ.get("TMPDIR", "/tmp"), "niblit_lean_signal.json"),
)

# Maximum age (seconds) before a signal is considered stale
_MAX_SIGNAL_AGE_SECS: int = int(os.environ.get("NIBLIT_SIGNAL_MAX_AGE", "300"))


class NiblitBridge:
    """Reads Niblit TradingBrain signals from a shared JSON sidecar file.

    Each LEAN algorithm instantiates one NiblitBridge in ``initialize``
    and calls ``get_signal()`` in ``on_data`` to optionally incorporate
    Niblit's AI decisions alongside the algorithm's own indicators.

    Parameters
    ----------
    signal_file:
        Path to the JSON signal file.  Defaults to the value of the
        ``NIBLIT_SIGNAL_FILE`` environment variable, or
        ``/tmp/niblit_lean_signal.json``.
    max_age_secs:
        Signals older than this (by ``timestamp`` field) are ignored.
    """

    def __init__(
        self,
        signal_file: str = _DEFAULT_SIGNAL_FILE,
        max_age_secs: int = _MAX_SIGNAL_AGE_SECS,
    ) -> None:
        self.signal_file = signal_file
        self.max_age_secs = max_age_secs
        self._last_signal: Optional[Dict[str, Any]] = None
        self._last_read: float = 0.0

    def get_signal(self) -> Optional[str]:
        """Return the current Niblit signal: "BUY", "SELL", "HOLD", or None.

        Returns None when:
        - The signal file does not exist.
        - The file cannot be parsed.
        - The signal is stale (older than max_age_secs).
        """
        data = self._read()
        if data is None:
            return None
        return data.get("signal")

    def get_full(self) -> Optional[Dict[str, Any]]:
        """Return the full signal payload dict, or None if unavailable."""
        return self._read()

    def get_confidence(self) -> float:
        """Return the signal confidence (0–1), defaulting to 0.5."""
        data = self._read()
        if data is None:
            return 0.5
        return float(data.get("confidence", 0.5))

    def get_risk_pct(self, default: float = 0.02) -> float:
        """Return Niblit's suggested position size as a fraction of equity."""
        data = self._read()
        if data is None:
            return default
        return float(data.get("risk_pct", default))

    def get_regime(self) -> str:
        """Return market regime: "bullish", "bearish", or "ranging"."""
        data = self._read()
        if data is None:
            return "ranging"
        return str(data.get("regime", "ranging"))

    def get_indicator(self, name: str, default: Optional[float] = None) -> Optional[float]:
        """Return a specific indicator value from Niblit's signal payload."""
        data = self._read()
        if data is None:
            return default
        indicators = data.get("indicators", {})
        val = indicators.get(name)
        return float(val) if val is not None else default

    def is_available(self) -> bool:
        """Return True if a fresh signal file exists and is readable."""
        return self._read() is not None

    # ── internal ──────────────────────────────────────────────────────────────

    def _read(self) -> Optional[Dict[str, Any]]:
        """Read and validate the signal file, with a 5-second cache."""
        now = time.time()
        # Cache for 5 seconds to avoid repeated disk reads per bar
        if now - self._last_read < 5.0 and self._last_signal is not None:
            return self._last_signal

        self._last_read = now
        try:
            if not os.path.isfile(self.signal_file):
                return None
            with open(self.signal_file, "r") as fh:
                data: Dict[str, Any] = json.load(fh)
        except (OSError, ValueError, json.JSONDecodeError):
            return None

        # Staleness check
        ts = data.get("timestamp", 0)
        if ts and (now - float(ts)) > self.max_age_secs:
            return None

        self._last_signal = data
        return data
