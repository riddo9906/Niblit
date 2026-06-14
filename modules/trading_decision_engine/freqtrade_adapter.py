#!/usr/bin/env python3
"""modules/trading_decision_engine/freqtrade_adapter.py

FreqtradeAdapter — converts :class:`TradingDecision` objects into
Freqtrade-compatible strategy signals.

Output signal map
-----------------
+----------------+-------+---------+----------+----------+
| TradingDecision| enter | enter   | exit     | exit     |
| action         | _long | _short  | _long    | _short   |
+================+=======+=========+==========+==========+
| ``"buy"``      | True  | False   | False    | False    |
| ``"sell"``     | False | True    | True     | False    |
| ``"hold"``     | False | False   | False    | False    |
+----------------+-------+---------+----------+----------+

All signals include:
- ``confidence``  — decision confidence in [0, 1]
- ``reason``      — ordered reasoning-trace snippets (up to 10)
- ``metadata``    — engine diagnostics dict

Usage::

    from modules.trading_decision_engine import FreqtradeAdapter, NiblitDecisionEngine

    engine = NiblitDecisionEngine(qdrant_manager, memory_graph, router)
    adapter = FreqtradeAdapter()

    decision = engine.decide("BTC breakout above 70k", "BTC/USDT")
    signal = adapter.to_freqtrade_signal(decision)
    # signal["enter_long"] -> True/False
"""

from __future__ import annotations

import logging
from typing import Any

log = logging.getLogger("FreqtradeAdapter")


class FreqtradeAdapter:
    """Converts :class:`~modules.trading_decision_engine.TradingDecision`
    objects into Freqtrade strategy-compatible signal dicts.

    The output dict maps directly to Freqtrade's ``populate_entry_trend``
    and ``populate_exit_trend`` column naming convention:

    ``enter_long``  — True when a long-entry (buy) is signalled.
    ``enter_short`` — True when a short-entry (sell) is signalled.
    ``exit_long``   — True when an open long position should be exited.
    ``exit_short``  — True when an open short position should be exited.

    Exit logic
    ----------
    A ``"sell"`` action simultaneously sets ``enter_short = True`` and
    ``exit_long = True`` because in most Freqtrade strategies a bearish
    signal means both: open a short *and* close any open long.

    A ``"buy"`` action sets ``exit_short = True`` (close any open short)
    in addition to ``enter_long = True``.
    """

    def to_freqtrade_signal(self, decision: Any) -> dict[str, Any]:
        """Convert a :class:`TradingDecision` to a Freqtrade signal dict.

        Parameters
        ----------
        decision:
            A :class:`~modules.trading_decision_engine.TradingDecision`
            instance (or any object with ``action``, ``confidence``,
            ``reasoning``, and ``metadata`` attributes).

        Returns
        -------
        dict with keys:
            ``enter_long``, ``enter_short``, ``exit_long``, ``exit_short``,
            ``confidence``, ``reason``, ``metadata``.
        """
        action: str = getattr(decision, "action", "hold")
        confidence: float = float(getattr(decision, "confidence", 0.0))
        reasoning: list[str] = list(getattr(decision, "reasoning", []))
        metadata: dict[str, Any] = dict(getattr(decision, "metadata", {}))

        enter_long = action == "buy"
        enter_short = action == "sell"
        exit_long = action == "sell"
        exit_short = action == "buy"

        signal: dict[str, Any] = {
            "enter_long": enter_long,
            "enter_short": enter_short,
            "exit_long": exit_long,
            "exit_short": exit_short,
            "confidence": round(confidence, 4),
            "reason": reasoning[:10],
            "metadata": metadata,
        }

        log.debug(
            "[FreqtradeAdapter] action=%s enter_long=%s enter_short=%s "
            "exit_long=%s exit_short=%s confidence=%.4f",
            action, enter_long, enter_short, exit_long, exit_short, confidence,
        )

        return signal

    def to_freqtrade_signal_bulk(self, decisions: list[Any]) -> list[dict[str, Any]]:
        """Convert a list of :class:`TradingDecision` objects in bulk.

        Parameters
        ----------
        decisions:
            Iterable of :class:`TradingDecision` instances.

        Returns
        -------
        List of signal dicts in the same order as *decisions*.
        """
        return [self.to_freqtrade_signal(d) for d in decisions]
