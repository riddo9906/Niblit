"""
modules/trade_kb_learner.py — KB-based Trading Pattern Learner for Niblit.

This module enriches Niblit's trading signals by:
  1. Storing indicator-pattern → signal → outcome tuples in the knowledge base
     so Niblit accumulates a trade memory over time.
  2. Computing a historical win-rate for indicator conditions similar to the
     current candle, and using it to boost or reduce signal confidence.
  3. Exposing a human-readable summary of what Niblit has learned about
     market conditions (e.g. "RSI < 30 after a BUY → 72% win rate over 18 trades").

Design
------
* Pure KB-driven — no ML deps required (works in android profile).
* Thread-safe via a per-instance lock.
* Gracefully no-ops when no knowledge DB is wired in.
* All stored keys use the ``trading_pattern:`` prefix so they can be easily
  filtered and audited in the KB.

Usage
-----
    from modules.trade_kb_learner import TradeKBLearner

    learner = TradeKBLearner(knowledge_db=core.db)

    # Enrich an outbound signal with KB history
    enriched = learner.enrich_signal("BTC/USDT", "1h", features, raw_action, raw_confidence)
    # -> {"action": "buy", "confidence": 0.72, "reason": "...", "win_rate": 0.72, "sample_size": 18}

    # Record outcome after a trade closes
    learner.record_outcome("BTC/USDT", "1h", features, action="buy", outcome="profit", pnl_pct=2.3)
"""
from __future__ import annotations

import json
import logging
import math
import threading
import time
from typing import Any, Dict, List, Optional

log = logging.getLogger("TradeKBLearner")

# Precision for bucketing continuous indicator values so similar candles share keys.
_RSI_BUCKET_SIZE   = 5    # e.g. RSI 32 → bucket "30"
_MACD_SIGN         = True  # only store sign (+/-/0), not magnitude
# Minimum samples needed before KB history overrides raw signal confidence.
_MIN_SAMPLES_TO_TRUST = 5
# Maximum number of pattern entries to inspect when building a win-rate estimate.
_MAX_PATTERN_SCAN  = 200
# Maximum length of the stored reasoning text in KB entries.
_MAX_REASON_TEXT   = 400

# Category tag used for all KB entries written by this module.
_KB_CATEGORY = "trade_pattern"


def _bucket_rsi(rsi: Optional[float]) -> str:
    if rsi is None or not math.isfinite(rsi):
        return "?"
    b = int(rsi // _RSI_BUCKET_SIZE) * _RSI_BUCKET_SIZE
    return str(b)


def _macd_sign(macd: Optional[float]) -> str:
    if macd is None or not math.isfinite(macd):
        return "?"
    if macd > 0:
        return "+"
    if macd < 0:
        return "-"
    return "0"


def _ema_trend(ema_fast: Optional[float], ema_slow: Optional[float]) -> str:
    if ema_fast is None or ema_slow is None:
        return "?"
    if ema_fast > ema_slow:
        return "bull"
    if ema_fast < ema_slow:
        return "bear"
    return "flat"


def _pattern_key(pair: str, timeframe: str, features: Dict[str, float]) -> str:
    """Build a compact, human-readable pattern key from indicator features."""
    rsi_b = _bucket_rsi(features.get("rsi"))
    macd_s = _macd_sign(features.get("macd"))
    ema_t = _ema_trend(features.get("ema_fast"), features.get("ema_slow"))
    safe_pair = pair.replace("/", "_").lower()
    return f"trading_pattern:{safe_pair}:{timeframe}:rsi{rsi_b}:macd{macd_s}:ema{ema_t}"


class TradeKBLearner:
    """Learns trading patterns from historical signals and their outcomes.

    Parameters
    ----------
    knowledge_db:
        A KnowledgeDB / NiblitMemory instance.  When ``None``, all operations
        degrade gracefully to no-ops.
    """

    def __init__(self, knowledge_db: Optional[Any] = None) -> None:
        self._db = knowledge_db
        self._lock = threading.Lock()
        log.debug("[TradeKBLearner] Initialised (db=%s)", "yes" if knowledge_db else "no")

    # ─────────────────────────────────────────────── public API ──────────────

    def enrich_signal(
        self,
        pair: str,
        timeframe: str,
        features: Dict[str, float],
        raw_action: str,
        raw_confidence: float,
    ) -> Dict[str, Any]:
        """Enrich a raw signal with KB-derived historical win-rate.

        Returns a dict with keys:
          action, confidence, reason, win_rate, sample_size, source.
        """
        if self._db is None:
            return self._plain(raw_action, raw_confidence, "no_db")

        key = _pattern_key(pair, timeframe, features)
        win_rate, sample_size, recent_actions = self._compute_win_rate(key)

        if sample_size < _MIN_SAMPLES_TO_TRUST:
            reason = (
                f"Pattern '{key}' has only {sample_size} samples — "
                "using raw signal; more trade history needed."
            )
            return self._plain(raw_action, raw_confidence, reason)

        # Blend raw confidence with historical win rate:
        # more samples → stronger pull toward historical truth.
        blend_weight = min(0.8, sample_size / 50.0)
        blended_conf = (1 - blend_weight) * raw_confidence + blend_weight * win_rate
        blended_conf = round(max(0.0, min(1.0, blended_conf)), 4)

        # Determine KB-suggested action from win rate direction.
        if win_rate >= 0.60:
            kb_action = "buy"
        elif win_rate <= 0.40:
            kb_action = "sell"
        else:
            kb_action = "hold"

        # Take the KB action when the sample size is large enough to trust.
        action = kb_action if sample_size >= _MIN_SAMPLES_TO_TRUST * 2 else raw_action

        rsi_desc = f"RSI≈{_bucket_rsi(features.get('rsi'))}"
        macd_desc = f"MACD{'positive' if _macd_sign(features.get('macd')) == '+' else 'negative'}"
        ema_desc = f"EMA-trend={_ema_trend(features.get('ema_fast'), features.get('ema_slow'))}"
        reason = (
            f"KB history: {sample_size} trades at {rsi_desc}, {macd_desc}, {ema_desc} "
            f"→ win-rate={win_rate:.0%}. "
            f"Raw={raw_action}({raw_confidence:.2f}), KB suggests {kb_action}. "
            f"Blended confidence={blended_conf:.2f}."
        )[:_MAX_REASON_TEXT]

        log.info(
            "[TradeKBLearner] %s/%s %s → %s (conf %.2f→%.2f, win_rate=%.0%%, n=%d)",
            pair, timeframe, raw_action, action, raw_confidence, blended_conf,
            win_rate * 100, sample_size,
        )

        return {
            "action": action,
            "confidence": blended_conf,
            "reason": reason,
            "win_rate": win_rate,
            "sample_size": sample_size,
            "source": "trade_kb_learner",
        }

    def record_outcome(
        self,
        pair: str,
        timeframe: str,
        features: Dict[str, float],
        action: str,
        outcome: str,
        pnl_pct: Optional[float] = None,
    ) -> None:
        """Store a trade outcome so future signals can learn from it.

        Parameters
        ----------
        pair:      Trading pair, e.g. ``"BTC/USDT"``.
        timeframe: Candle timeframe, e.g. ``"1h"``.
        features:  Indicator snapshot at signal time.
        action:    The signal that was acted on: ``"buy"`` / ``"sell"`` / ``"hold"``.
        outcome:   Trade result: ``"profit"`` / ``"loss"`` / ``"neutral"``.
        pnl_pct:   Optional P&L percentage (positive = profit).
        """
        if self._db is None:
            return

        key = _pattern_key(pair, timeframe, features)
        win = 1 if outcome == "profit" else 0
        ts = int(time.time())
        entry_key = f"{key}:{ts}"
        entry_val = json.dumps({
            "ts": ts,
            "pair": pair,
            "timeframe": timeframe,
            "action": action,
            "outcome": outcome,
            "win": win,
            "pnl_pct": pnl_pct,
            "rsi": features.get("rsi"),
            "macd_sign": _macd_sign(features.get("macd")),
            "ema_trend": _ema_trend(features.get("ema_fast"), features.get("ema_slow")),
        })
        try:
            with self._lock:
                self._db.store(key=entry_key, value=entry_val, category=_KB_CATEGORY)
            log.debug(
                "[TradeKBLearner] Stored outcome: %s → %s (%s) pnl=%s",
                entry_key, action, outcome, pnl_pct,
            )
        except Exception as exc:
            log.warning("[TradeKBLearner] record_outcome store error: %s", exc)

    def summarize(self, pair: Optional[str] = None, limit: int = 20) -> str:
        """Return a human-readable summary of learned trading patterns.

        Parameters
        ----------
        pair:  Filter to a specific pair (e.g. ``"BTC/USDT"``).  When ``None``
               all pairs are included.
        limit: Maximum number of pattern buckets to list.
        """
        if self._db is None:
            return "[TradeKBLearner] No knowledge DB wired — no patterns stored."

        try:
            prefix = "trading_pattern:"
            if pair:
                prefix += pair.replace("/", "_").lower() + ":"
            facts = self._db.list_facts(limit=_MAX_PATTERN_SCAN)
        except Exception as exc:
            return f"[TradeKBLearner] KB query error: {exc}"

        # Group by pattern key (strip the trailing timestamp component).
        buckets: Dict[str, List[Dict]] = {}
        for fact in facts:
            key = fact.get("key", "")
            if not key.startswith(prefix):
                continue
            parts = key.rsplit(":", 1)
            if len(parts) == 2:
                bucket = parts[0]
            else:
                bucket = key
            try:
                entry = json.loads(fact.get("value", "{}"))
            except Exception:
                continue
            if isinstance(entry, dict) and "win" in entry:
                buckets.setdefault(bucket, []).append(entry)

        if not buckets:
            return "[TradeKBLearner] No trading patterns stored yet."

        lines = ["=== Niblit Trading Pattern Memory ==="]
        count = 0
        for bucket, entries in sorted(buckets.items(), key=lambda x: -len(x[1])):
            if count >= limit:
                break
            wins = sum(e["win"] for e in entries)
            n = len(entries)
            wr = wins / n if n else 0.0
            # Extract indicator summary from the last entry.
            last = entries[-1]
            rsi = _bucket_rsi(last.get("rsi"))
            macd_s = last.get("macd_sign", "?")
            ema_t = last.get("ema_trend", "?")
            pair_str = last.get("pair", "?")
            tf_str = last.get("timeframe", "?")
            lines.append(
                f"  {pair_str}/{tf_str} RSI≈{rsi} MACD{macd_s} EMA={ema_t}: "
                f"{wins}/{n} wins ({wr:.0%} win-rate)"
            )
            count += 1

        if len(buckets) > limit:
            lines.append(f"  … and {len(buckets) - limit} more patterns.")
        return "\n".join(lines)

    # ─────────────────────────────────────────────── internals ───────────────

    def _compute_win_rate(self, key: str):
        """Return (win_rate, sample_size, recent_actions) for a pattern key."""
        try:
            facts = self._db.list_facts(limit=_MAX_PATTERN_SCAN)
        except Exception:
            return 0.5, 0, []

        wins = 0
        total = 0
        recent_actions: List[str] = []
        for fact in facts:
            fkey = fact.get("key", "")
            if not fkey.startswith(key + ":"):
                continue
            try:
                entry = json.loads(fact.get("value", "{}"))
            except Exception:
                continue
            if not isinstance(entry, dict) or "win" not in entry:
                continue
            wins += entry["win"]
            total += 1
            recent_actions.append(entry.get("action", "?"))

        if total == 0:
            return 0.5, 0, []
        return wins / total, total, recent_actions[-5:]

    @staticmethod
    def _plain(action: str, confidence: float, reason: str) -> Dict[str, Any]:
        return {
            "action": action,
            "confidence": confidence,
            "reason": reason,
            "win_rate": None,
            "sample_size": 0,
            "source": "raw",
        }


if __name__ == "__main__":
    print('Running trade_kb_learner.py')
