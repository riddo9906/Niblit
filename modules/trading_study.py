#!/usr/bin/env python3
"""
modules/trading_study.py — Trading Study, Reflection & Metacognition Engine.

Provides :class:`TradingStudy`, Niblit's dedicated cognitive layer for learning
from live and backtested trades.  It works alongside the existing
:class:`~modules.reflect.ReflectModule` by adding trading-domain-specific
study methods, metacognition (thinking about its own trading logic), and
brain-training hooks that improve Niblit's future trading decisions.

Design goals
------------
* **Purely additive** — does not modify TradingBrain, LeanEngine, or ReflectModule.
* **Study** — ingests trade logs, order events, and LEAN backtest metrics into
  structured KB entries so the next reflection cycle has richer context.
* **Reflect** — produces post-trade narratives that analyse what worked and
  what didn't, stored under ``trading_study:`` keys.
* **Metacognition** — maintains a running self-assessment of Niblit's trading
  competence, confidence, and blind spots.  Accessible via ``trading study meta``.
* **Brain training** — periodically feeds study insights to BrainTrainer /
  BackgroundTrainer so weights are updated in the direction of profitable
  behaviour.
* **LEAN integration** — can import backtest result dicts from LeanEngine and
  LeanDeployEngine and turn them into study sessions.
* **Market-provider integration** — can snapshot current market state via
  MarketDataProviders for context-enriched reflections.
"""

from __future__ import annotations

import json
import logging
import threading
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

log = logging.getLogger("TradingStudy")

# ── notification queue ────────────────────────────────────────────────────────
try:
    from core.notification_queue import notif_queue as _notif_queue
except ImportError:
    class _NopQueue:
        def push(self, msg: str) -> None:
            pass
    _notif_queue = _NopQueue()  # type: ignore[assignment]

# Maximum characters stored per study entry
_MAX_STUDY_TEXT = 800
# Minimum gap (seconds) between auto-study cycles
_AUTO_STUDY_INTERVAL_SECS = 300


class TradingStudy:
    """Cognitive trading study, reflection, and metacognition for Niblit.

    Parameters
    ----------
    knowledge_db:       KnowledgeDB / NiblitMemory for storing study results.
    trading_brain:      TradingBrain for reading live cycle data.
    lean_engine:        LeanEngine for reading backtest results.
    lean_deploy_engine: LeanDeployEngine for reading live QC algorithm data.
    market_data:        MarketDataProviders for market context snapshots.
    brain_trainer:      BackgroundTrainer for feeding study insights as training.
    reflect_module:     Existing ReflectModule (for cross-module synergy).
    llm:                Optional LLM adapter for richer narrative generation.
    """

    def __init__(
        self,
        knowledge_db: Optional[Any] = None,
        trading_brain: Optional[Any] = None,
        lean_engine: Optional[Any] = None,
        lean_deploy_engine: Optional[Any] = None,
        market_data: Optional[Any] = None,
        brain_trainer: Optional[Any] = None,
        reflect_module: Optional[Any] = None,
        llm: Optional[Any] = None,
    ) -> None:
        self._kb = knowledge_db
        self._brain = trading_brain
        self._lean = lean_engine
        self._deploy = lean_deploy_engine
        self._market = market_data
        self._trainer = brain_trainer
        self._reflect = reflect_module
        self._llm = llm

        # In-memory trade journal
        self._trade_journal: List[Dict[str, Any]] = []
        self._journal_lock = threading.Lock()

        # Metacognition state
        self._meta: Dict[str, Any] = {
            "total_study_sessions": 0,
            "profitable_trades_observed": 0,
            "loss_trades_observed": 0,
            "known_patterns": [],
            "blind_spots": [],
            "confidence": 0.5,
            "last_study_ts": 0.0,
        }
        self._meta_lock = threading.Lock()

        # Auto-study thread
        self._auto_study_running = False
        self._auto_study_thread: Optional[threading.Thread] = None

        log.info("[TradingStudy] Initialized")

    # ─────────────────────────────────────────────────────── status ──────────

    def status(self) -> str:
        with self._meta_lock:
            m = dict(self._meta)
        with self._journal_lock:
            jlen = len(self._trade_journal)
        lines = [
            "=== Trading Study Engine ===",
            f"  Study sessions:     {m['total_study_sessions']}",
            f"  Trade journal:      {jlen} entries",
            f"  Profitable trades:  {m['profitable_trades_observed']}",
            f"  Loss trades:        {m['loss_trades_observed']}",
            f"  Confidence:         {m['confidence']:.2f}",
            f"  Auto-study:         {'running' if self._auto_study_running else 'stopped'}",
            f"  Known patterns:     {len(m['known_patterns'])}",
            f"  Blind spots noted:  {len(m['blind_spots'])}",
        ]
        if m["last_study_ts"]:
            last = datetime.fromtimestamp(m["last_study_ts"], tz=timezone.utc).isoformat()
            lines.append(f"  Last study:         {last}")
        return "\n".join(lines)

    # ─────────────────────────────────────────────────── trade journal ────────

    def log_trade(
        self,
        symbol: str,
        side: str,
        price: float,
        qty: float,
        pnl: Optional[float] = None,
        source: str = "trading_brain",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Record a trade in the in-memory journal and KB.

        *pnl* > 0 = profitable, < 0 = loss.
        """
        entry: Dict[str, Any] = {
            "symbol": symbol,
            "side": side,
            "price": price,
            "qty": qty,
            "pnl": pnl,
            "source": source,
            "ts": time.time(),
            "metadata": metadata or {},
        }
        with self._journal_lock:
            self._trade_journal.append(entry)
        if pnl is not None:
            with self._meta_lock:
                if pnl > 0:
                    self._meta["profitable_trades_observed"] += 1
                else:
                    self._meta["loss_trades_observed"] += 1
                self._update_confidence()
        key = f"trading_study:trade:{symbol}:{int(entry['ts'])}"
        self._store_in_kb(
            key,
            f"Trade: {side} {qty} {symbol} @ {price} pnl={pnl} source={source}",
            tags=["trade", "trading_study", symbol.lower()],
        )
        return f"✅ Trade logged: {side} {qty} {symbol} @ {price}"

    def _update_confidence(self) -> None:
        """Update self-confidence metric based on win/loss ratio."""
        total = self._meta["profitable_trades_observed"] + self._meta["loss_trades_observed"]
        if total == 0:
            return
        win_rate = self._meta["profitable_trades_observed"] / total
        # Smooth toward win_rate
        self._meta["confidence"] = 0.7 * self._meta["confidence"] + 0.3 * win_rate

    # ─────────────────────────────────────────────────────── study ────────────

    def study_last_trade_brain_cycle(self) -> str:
        """Study the most recent TradingBrain cycle result.

        Reads brain.cycle_history or brain.status() and generates a study entry.
        """
        if self._brain is None:
            return "[TradingStudy] TradingBrain not wired"
        try:
            brain_status = self._brain.status()
            decision = brain_status.get("last_decision", "unknown")
            price = brain_status.get("last_price", 0.0)
            symbol = brain_status.get("symbol", "?")
            ts = brain_status.get("last_cycle_ts", 0)
            text = (
                f"TradingBrain cycle study: symbol={symbol} "
                f"decision={decision} price={price} ts={ts}"
            )
            narrative = self._enrich_with_llm(
                "Reflect on this TradingBrain cycle result and identify any patterns "
                "or areas for improvement: " + text
            )
            key = f"trading_study:brain_cycle:{int(time.time())}"
            self._store_in_kb(key, narrative or text, tags=["trading_study", "brain_cycle"])
            self._increment_sessions()
            return f"✅ Studied TradingBrain cycle: {text[:200]}"
        except Exception as exc:
            return f"[TradingStudy] study_last_trade_brain_cycle error: {exc}"

    def study_lean_backtest(
        self,
        project_name: str,
        metrics: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Study LEAN backtest results, extract patterns, store insights.

        If *metrics* is None, tries to read from LeanEngine's optimal params.
        """
        if metrics is None and self._lean is not None:
            params_entry = self._lean.get_optimal_params(project_name)
            if params_entry:
                metrics = params_entry
        if not metrics:
            return f"[TradingStudy] No backtest metrics for '{project_name}'"

        score = metrics.get("score")
        metric_name = metrics.get("metric", "Sharpe Ratio")
        params = metrics.get("params", {})
        text = (
            f"LEAN backtest study '{project_name}': "
            f"best {metric_name}={score} with params={params}"
        )
        # Pattern extraction
        pattern = self._extract_pattern(params, score)
        if pattern:
            with self._meta_lock:
                if pattern not in self._meta["known_patterns"]:
                    self._meta["known_patterns"].append(pattern)
        narrative = self._enrich_with_llm(
            "Analyse this backtest result and suggest strategy improvements: " + text
        )
        key = f"trading_study:lean_backtest:{project_name}:{int(time.time())}"
        self._store_in_kb(key, narrative or text, tags=["trading_study", "lean", "backtest"])
        # Feed to brain trainer
        self._train_on_insight(narrative or text)
        self._increment_sessions()
        return f"✅ Studied LEAN backtest '{project_name}': {text[:200]}"

    def study_live_algorithm(
        self,
        deploy_id: str,
        status_text: str,
    ) -> str:
        """Study a live QuantConnect algorithm status update.

        Called by LeanDeployEngine monitors and the reflection engine.
        """
        key = f"trading_study:live_algo:{deploy_id}:{int(time.time())}"
        text = f"Live algorithm {deploy_id}: {status_text}"
        narrative = self._enrich_with_llm(
            "Analyse this live algorithm status and identify risk or opportunity: " + text[:300]
        )
        self._store_in_kb(
            key, narrative or text,
            tags=["trading_study", "live", "quantconnect", deploy_id[:16]],
        )
        self._train_on_insight(narrative or text)
        self._increment_sessions()
        return f"✅ Studied live algorithm {deploy_id}"

    def study_market_snapshot(
        self,
        symbols: Optional[List[str]] = None,
    ) -> str:
        """Fetch current market data via MarketDataProviders and study it.

        Stores a snapshot + analysis in KB and triggers brain training.
        """
        if self._market is None:
            return "[TradingStudy] MarketDataProviders not wired"
        overview = self._market.market_overview(symbols)
        key = f"trading_study:market_snapshot:{int(time.time())}"
        text = f"Market snapshot study:\n{overview}"
        narrative = self._enrich_with_llm(
            "Study this market snapshot and identify trading opportunities or risks: " + overview[:400]
        )
        self._store_in_kb(key, narrative or text, tags=["trading_study", "market_snapshot"])
        self._train_on_insight(narrative or text)
        self._increment_sessions()
        return f"✅ Market snapshot studied\n{overview}"

    def deep_study_session(self) -> str:
        """Run a full study session: brain cycle + market + lean backtests.

        Called autonomously by the ALE engine or manually via CLI.
        """
        results = []
        # 1. Brain cycle
        results.append(self.study_last_trade_brain_cycle())
        # 2. Market snapshot
        if self._market is not None:
            results.append(self.study_market_snapshot())
        # 3. LEAN backtest projects
        if self._lean is not None:
            projects = self._lean.list_projects()
            if isinstance(projects, list):
                for p in projects[:3]:
                    results.append(
                        self.study_lean_backtest(p.get("name", "?"))
                    )
        # 4. Metacognition check
        results.append(self.metacognition_check())
        summary = f"Deep study session complete ({len(results)} studies)."
        _notif_queue.push(f"[TradingStudy] {summary}")
        return summary + "\n" + "\n".join(results)

    # ─────────────────────────────────────────────────── metacognition ────────

    def metacognition_check(self) -> str:
        """Self-assessment of trading competence and reasoning quality.

        Compares win/loss rates, identifies potential blind spots, and
        updates the metacognition state.
        """
        with self._meta_lock:
            m = dict(self._meta)

        total = m["profitable_trades_observed"] + m["loss_trades_observed"]
        win_rate = m["profitable_trades_observed"] / total if total > 0 else None
        confidence = m["confidence"]

        blind_spots = []
        if win_rate is not None:
            if win_rate < 0.4:
                blind_spots.append("Low win rate — consider tighter entry criteria")
            if win_rate > 0.8 and total < 20:
                blind_spots.append("High win rate with small sample — could be overfitting")
        if len(m["known_patterns"]) == 0:
            blind_spots.append("No recognized patterns yet — needs more data")

        # Update blind spots
        with self._meta_lock:
            for bs in blind_spots:
                if bs not in self._meta["blind_spots"]:
                    self._meta["blind_spots"].append(bs)

        text = (
            f"Metacognition check:\n"
            f"  Confidence:      {confidence:.2f}\n"
            f"  Win rate:        {f'{win_rate*100:.1f}%' if win_rate is not None else 'n/a'} "
            f"({m['profitable_trades_observed']}W / {m['loss_trades_observed']}L)\n"
            f"  Known patterns:  {m['known_patterns'][:3]}\n"
            f"  Blind spots:     {blind_spots or 'none detected'}"
        )
        key = f"trading_study:metacognition:{int(time.time())}"
        self._store_in_kb(key, text, tags=["trading_study", "metacognition"])
        return text

    # ─────────────────────────────────────────────────── reflect on lean live ──

    def reflect_on_lean_live(
        self,
        deploy_id: str,
        status_text: str,
    ) -> str:
        """Reflection hook called by LeanDeployEngine monitor threads.

        Cross-module: also invokes existing ReflectModule if available.
        """
        study_result = self.study_live_algorithm(deploy_id, status_text)
        # Also route through ReflectModule for unified KB storage
        if self._reflect is not None:
            try:
                entry_text = f"live_algorithm:{deploy_id}:{status_text[:200]}"
                self._reflect.collect_and_summarize([entry_text], "trading_live")
            except Exception as exc:
                log.debug("[TradingStudy] reflect_module.collect_and_summarize: %s", exc)
        return study_result

    # ─────────────────────────────────────────────────── auto-study ──────────

    def start_auto_study(self, interval_secs: int = _AUTO_STUDY_INTERVAL_SECS) -> str:
        """Start a background auto-study thread."""
        if self._auto_study_running:
            return "⚠️  Auto-study already running"
        self._auto_study_running = True

        def _loop() -> None:
            log.info("[TradingStudy] Auto-study started (interval=%ss)", interval_secs)
            while self._auto_study_running:
                try:
                    self.study_last_trade_brain_cycle()
                    if self._market is not None:
                        self.study_market_snapshot()
                except Exception as exc:
                    log.debug("[TradingStudy] auto-study error: %s", exc)
                time.sleep(interval_secs)

        self._auto_study_thread = threading.Thread(
            target=_loop, daemon=True, name="TradingStudyAutoStudy"
        )
        self._auto_study_thread.start()
        return f"✅ Auto-study started (interval={interval_secs}s)"

    def stop_auto_study(self) -> str:
        """Stop the background auto-study thread."""
        self._auto_study_running = False
        return "✅ Auto-study stopped"

    # ─────────────────────────────────────────────────── journal analysis ────

    def analyse_journal(self, last_n: int = 50) -> str:
        """Produce a statistical analysis of the last *n* journal entries."""
        with self._journal_lock:
            entries = list(self._trade_journal[-last_n:])
        if not entries:
            return "[TradingStudy] Trade journal is empty"

        total = len(entries)
        pnl_values = [e["pnl"] for e in entries if e.get("pnl") is not None]
        wins = sum(1 for p in pnl_values if p > 0)
        losses = sum(1 for p in pnl_values if p < 0)
        gross_profit = sum(p for p in pnl_values if p > 0)
        gross_loss = sum(p for p in pnl_values if p < 0)
        net = gross_profit + gross_loss
        win_rate = wins / len(pnl_values) if pnl_values else 0.0
        avg_win = gross_profit / wins if wins else 0.0
        avg_loss = gross_loss / losses if losses else 0.0

        symbols = {}
        for e in entries:
            s = e.get("symbol", "?")
            symbols[s] = symbols.get(s, 0) + 1
        top_symbols = sorted(symbols, key=symbols.get, reverse=True)[:5]

        lines = [
            f"Trade Journal Analysis (last {total} trades):",
            f"  Total trades:   {total}",
            f"  Win rate:       {win_rate*100:.1f}% ({wins}W / {losses}L)",
            f"  Net PnL:        {net:.4f}",
            f"  Avg win:        {avg_win:.4f}",
            f"  Avg loss:       {avg_loss:.4f}",
            f"  Top symbols:    {top_symbols}",
        ]
        result = "\n".join(lines)
        key = f"trading_study:journal_analysis:{int(time.time())}"
        self._store_in_kb(key, result, tags=["trading_study", "journal"])
        return result

    # ─────────────────────────────────────────────────── helpers ─────────────

    def _extract_pattern(
        self,
        params: Dict[str, Any],
        score: Optional[float],
    ) -> Optional[str]:
        """Heuristic pattern extraction from backtest parameters."""
        if not params or score is None:
            return None
        fast = params.get("fast_period", params.get("fast", None))
        slow = params.get("slow_period", params.get("slow", None))
        if fast and slow and fast != 0:
            ratio = slow / fast
            if score > 1.0:
                return f"EMA ratio {fast}/{slow} (≈{ratio:.1f}x) → Sharpe>{score:.1f}"
        return None

    def _enrich_with_llm(self, prompt: str) -> Optional[str]:
        """Generate a narrative via LLM if available, else return None."""
        if self._llm is None:
            return None
        try:
            if hasattr(self._llm, "generate_code"):
                return self._llm.generate_code(prompt)[:_MAX_STUDY_TEXT]
            if hasattr(self._llm, "chat"):
                return self._llm.chat(prompt)[:_MAX_STUDY_TEXT]
        except Exception as exc:
            log.debug("[TradingStudy] LLM enrich error: %s", exc)
        return None

    def _train_on_insight(self, text: str) -> None:
        """Feed a study insight to BrainTrainer / BackgroundTrainer."""
        if self._trainer is None:
            return
        try:
            if hasattr(self._trainer, "ingest_research"):
                self._trainer.ingest_research(text, source="trading_study")
        except Exception as exc:
            log.debug("[TradingStudy] brain_trainer.ingest_research: %s", exc)

    def _store_in_kb(
        self,
        key: str,
        text: str,
        tags: Optional[List[str]] = None,
    ) -> None:
        """Store a text entry in the KnowledgeDB."""
        if self._kb is None:
            return
        try:
            self._kb.store(key, text[:_MAX_STUDY_TEXT], tags=tags or ["trading_study"])
        except Exception:
            pass

    def _increment_sessions(self) -> None:
        with self._meta_lock:
            self._meta["total_study_sessions"] += 1
            self._meta["last_study_ts"] = time.time()

    def export_journal(self, last_n: int = 100, indent: int = 2) -> str:
        """Return the trade journal as a JSON string.

        Serialises the most recent *last_n* journal entries so they can be
        saved to disk, sent over HTTP, or imported by external analysis tools.
        """
        with self._trade_lock:
            entries = list(self._journal[-last_n:])
        return json.dumps(entries, indent=indent, default=str)


# ─────────────────────────────────────────────────────────────────────────────
# Singleton
# ─────────────────────────────────────────────────────────────────────────────

_trading_study: Optional[TradingStudy] = None


def get_trading_study(**kwargs: Any) -> TradingStudy:
    """Return the global :class:`TradingStudy` singleton."""
    global _trading_study
    if _trading_study is None:
        _trading_study = TradingStudy(**kwargs)
    return _trading_study
