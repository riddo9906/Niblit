#!/usr/bin/env python3
"""
modules/lean_algo_manager.py — Niblit ↔ QuantConnect LEAN Algorithms Manager.

Bridges Niblit's TradingBrain decisions and the niblit-lean-algos repo so
that:

1. **Signal publishing** — Niblit's TradingBrain.cycle() result is written
   to ``/tmp/niblit_lean_signal.json`` every ``signal_interval_secs``
   seconds.  The Niblit AI Master algorithm (20_niblit_ai_master) reads
   this file directly without any Python import.

2. **Algorithm deployment** — All algorithms in the ``niblit-lean-algos/``
   repo can be deployed to QuantConnect Cloud via the existing
   :class:`~modules.lean_deploy_engine.LeanDeployEngine` REST client.

3. **Result ingestion** — After a live or backtest run, the algorithm's
   performance JSON (written to ``/tmp/niblit_lean_results.json`` by
   ``20_niblit_ai_master``) is read back, stored in KnowledgeDB, and
   fed to the TradingBrain for learning.

4. **Autonomous monitoring** — A background daemon thread polls live
   algorithm status every ``monitor_interval_secs`` and pushes updates
   to the notification queue.

This module is **additive** — it does not modify LeanDeployEngine,
TradingBrain, or any other existing module.

Configuration (env vars or niblit_params.json)
----------------------------------------------
    QC_USER_ID           — QuantConnect user ID (also used by LeanDeployEngine)
    QC_API_CRED          — QuantConnect API token
    NIBLIT_SIGNAL_FILE   — Path for the signal JSON (default: /tmp/niblit_lean_signal.json)
    NIBLIT_RESULTS_FILE  — Path for the results JSON (default: /tmp/niblit_lean_results.json)
    NIBLIT_LEAN_ALGOS    — Path to the niblit-lean-algos directory
                           (default: auto-detect sibling of Niblit root)
    NIBLIT_ALGO_MODE     — "paper" or "live" (default: paper)

Usage
-----
    # From niblit_core._init_optional_services:
    from modules.lean_algo_manager import get_lean_algo_manager
    self.lean_algo_manager = get_lean_algo_manager(
        trading_brain=self.trading_brain,
        lean_deploy_engine=self.lean_deploy_engine,
        knowledge_db=self.memory,
    )

    # Start signal publishing loop:
    self.lean_algo_manager.start()

    # Niblit router commands:
    lean algo status
    lean algo deploy-all [--dry-run]
    lean algo signal
    lean algo results
    lean algo projects
    lean algo start <project_id>      ← start live practice on paper brokerage
    lean algo stop  <project_id>
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

log = logging.getLogger("LeanAlgoManager")

# ── optional parameter manager ────────────────────────────────────────────────
try:
    from modules.parameter_manager import parameter_manager as _pm
except ImportError:
    _pm = None  # type: ignore[assignment]

# ── notification queue ────────────────────────────────────────────────────────
try:
    from core.notification_queue import notif_queue as _notif_queue
except ImportError:
    class _NopQueue:  # type: ignore[no-redef]
        def push(self, msg: str) -> None: pass
    _notif_queue = _NopQueue()  # type: ignore[assignment]

# ── EventBus integration ──────────────────────────────────────────────────────
# Event types for the unified Niblit feedback loop (KRN layer).
# These let NET-layer trading signals flow through the kernel EventBus so that
# INT, LRN, and MEM layers can react without direct cross-layer calls.
EVT_TRADING_SIGNAL  = "trading.signal"
EVT_TRADING_RESULTS = "trading.results"


def _emit_trading_event(event_type: str, payload: Dict[str, Any]) -> None:
    """Emit a trading event to the CognitiveGraphKernel EventBus (best-effort).

    This closes the NET → KRN → INT/LRN feedback arc: every published
    Niblit signal and every ingested LEAN result becomes a first-class
    kernel event, allowing all layers to observe and react via their
    normal EventBus subscriptions rather than polling external files.
    """
    try:
        from modules.niblit_cognitive_graph_kernel import (
            Event,
            get_cognitive_graph_kernel,
        )
        kernel = get_cognitive_graph_kernel()
        kernel.bus.emit(Event(
            type=event_type,
            payload=payload,
            source="lean_algo_manager",
            priority=2.0,
        ))
    except Exception:  # pragma: no cover – kernel may not be running
        pass

# ─────────────────────────────────────────────────────────────────────────────
# Paths
# ─────────────────────────────────────────────────────────────────────────────

_REPO_ROOT = Path(__file__).resolve().parent.parent
_DEFAULT_ALGOS_DIR = _REPO_ROOT / "niblit-lean-algos"

_DEFAULT_SIGNAL_FILE = Path(
    os.environ.get("NIBLIT_SIGNAL_FILE",
                   os.path.join(os.environ.get("TMPDIR", "/tmp"), "niblit_lean_signal.json"))
)
_DEFAULT_RESULTS_FILE = Path(
    os.environ.get("NIBLIT_RESULTS_FILE",
                   os.path.join(os.environ.get("TMPDIR", "/tmp"), "niblit_lean_results.json"))
)

# ─────────────────────────────────────────────────────────────────────────────
# Singleton
# ─────────────────────────────────────────────────────────────────────────────

_instance: Optional["LeanAlgoManager"] = None
_lock = threading.Lock()


def get_lean_algo_manager(
    trading_brain: Optional[Any] = None,
    lean_deploy_engine: Optional[Any] = None,
    knowledge_db: Optional[Any] = None,
) -> "LeanAlgoManager":
    """Return the singleton LeanAlgoManager, creating it if needed."""
    global _instance
    with _lock:
        if _instance is None:
            _instance = LeanAlgoManager(
                trading_brain=trading_brain,
                lean_deploy_engine=lean_deploy_engine,
                knowledge_db=knowledge_db,
            )
        else:
            # Inject components if they were unavailable at first creation
            if trading_brain    and not _instance.trading_brain:
                _instance.trading_brain    = trading_brain
            if lean_deploy_engine and not _instance.lean_deploy_engine:
                _instance.lean_deploy_engine = lean_deploy_engine
            if knowledge_db     and not _instance.knowledge_db:
                _instance.knowledge_db     = knowledge_db
    return _instance


# ─────────────────────────────────────────────────────────────────────────────
# Manager
# ─────────────────────────────────────────────────────────────────────────────

class LeanAlgoManager:
    """Bridges Niblit's TradingBrain with the niblit-lean-algos LEAN algorithms.

    Parameters
    ----------
    trading_brain:
        Niblit's TradingBrain instance — used to read the latest market
        signal every ``signal_interval_secs``.
    lean_deploy_engine:
        Niblit's LeanDeployEngine — used to create/compile/list QC projects.
    knowledge_db:
        KnowledgeDB — algorithm results are stored here for ALE/reflection.
    signal_interval_secs:
        How often to refresh the signal file (default: 60 s).
    monitor_interval_secs:
        How often to poll live algorithm status (default: 120 s).
    """

    def __init__(
        self,
        trading_brain: Optional[Any] = None,
        lean_deploy_engine: Optional[Any] = None,
        knowledge_db: Optional[Any] = None,
        signal_interval_secs: int = 60,
        monitor_interval_secs: int = 120,
    ) -> None:
        self.trading_brain       = trading_brain
        self.lean_deploy_engine  = lean_deploy_engine
        self.knowledge_db        = knowledge_db
        self.signal_interval_secs   = signal_interval_secs
        self.monitor_interval_secs  = monitor_interval_secs

        self.signal_file  = _DEFAULT_SIGNAL_FILE
        self.results_file = _DEFAULT_RESULTS_FILE
        self.algos_dir    = Path(
            os.environ.get("NIBLIT_LEAN_ALGOS", str(_DEFAULT_ALGOS_DIR))
        )

        self._stop_event    = threading.Event()
        self._signal_thread: Optional[threading.Thread] = None
        self._monitor_thread: Optional[threading.Thread] = None

        self._last_signal:  Optional[Dict[str, Any]] = None
        self._live_projects: List[Dict[str, Any]] = []
        self._deployed_ids:  Dict[str, int] = {}  # algo_name → projectId

        # Load previously deployed project IDs if available
        self._load_deployed_ids()

        log.info("[LeanAlgoManager] Initialized — algos_dir=%s", self.algos_dir)

    # ── lifecycle ─────────────────────────────────────────────────────────────

    def start(self) -> str:
        """Start background signal publishing and live monitoring threads."""
        self._stop_event.clear()

        if self._signal_thread is None or not self._signal_thread.is_alive():
            self._signal_thread = threading.Thread(
                target=self._signal_loop,
                name="NiblitLeanSignalLoop",
                daemon=True,
            )
            self._signal_thread.start()
            log.info("[LeanAlgoManager] Signal publishing loop started (every %ds)",
                     self.signal_interval_secs)

        if self._monitor_thread is None or not self._monitor_thread.is_alive():
            self._monitor_thread = threading.Thread(
                target=self._monitor_loop,
                name="NiblitLeanMonitorLoop",
                daemon=True,
            )
            self._monitor_thread.start()
            log.info("[LeanAlgoManager] Live monitoring loop started (every %ds)",
                     self.monitor_interval_secs)

        return "✅ LeanAlgoManager started — signal publishing + live monitoring active."

    def stop(self) -> str:
        """Signal both background threads to stop."""
        self._stop_event.set()
        return "🛑 LeanAlgoManager stop requested."

    # ── signal publishing ─────────────────────────────────────────────────────

    def _signal_loop(self) -> None:
        """Background loop: read TradingBrain → write signal file."""
        while not self._stop_event.is_set():
            try:
                self._publish_signal()
            except Exception as exc:
                log.debug("[LeanAlgoManager] Signal publish error: %s", exc)
            self._stop_event.wait(self.signal_interval_secs)

    def _publish_signal(self) -> None:
        """Read TradingBrain signal and write to signal file."""
        if not self.trading_brain:
            return

        try:
            decision = self.trading_brain.cycle()
        except Exception as exc:
            log.debug("[LeanAlgoManager] TradingBrain.cycle() failed: %s", exc)
            return

        if not isinstance(decision, str):
            decision = str(decision)

        # Build the full signal payload
        signal_data: Dict[str, Any] = {
            "signal":    decision.upper().strip(),
            "timestamp": int(time.time()),
            "confidence": self._estimate_confidence(decision),
            "regime":    self._estimate_regime(),
            "risk_pct":  0.02,
            "indicators": self._collect_indicators(),
        }
        self._last_signal = signal_data
        self._write_json(self.signal_file, signal_data)
        # Publish into the unified Kernel EventBus so other layers can react
        _emit_trading_event(EVT_TRADING_SIGNAL, signal_data)
        log.debug("[LeanAlgoManager] Signal published: %s (conf=%.2f)",
                  decision, signal_data["confidence"])

    def _estimate_confidence(self, decision: str) -> float:
        """Return a confidence score (0-1) based on TradingBrain internals."""
        if not self.trading_brain:
            return 0.5
        try:
            # Use RL policy confidence if available
            rl = getattr(self.trading_brain, "rl_policy", None)
            if rl and hasattr(rl, "last_probabilities"):
                probs = rl.last_probabilities
                if probs:
                    return float(max(probs.values()))
        except Exception:
            pass
        return {"BUY": 0.70, "SELL": 0.70, "HOLD": 0.55}.get(decision.upper(), 0.5)

    def _estimate_regime(self) -> str:
        """Infer market regime from TradingBrain state."""
        if not self.trading_brain:
            return "ranging"
        try:
            sv = getattr(self.trading_brain, "_last_state_vector", None) or []
            if len(sv) >= 3:
                # sv[2] is typically ema_ratio: >1 = bull, <1 = bear
                ratio = float(sv[2]) if sv[2] != 0 else 1.0
                if ratio > 1.005:
                    return "bullish"
                if ratio < 0.995:
                    return "bearish"
        except Exception:
            pass
        return "ranging"

    def _collect_indicators(self) -> Dict[str, float]:
        """Collect indicator values from TradingBrain's last state."""
        if not self.trading_brain:
            return {}
        try:
            sv = getattr(self.trading_brain, "_last_state_vector", None) or []
            keys = ["rsi", "macd", "ema_ratio", "atr_norm", "volume_ratio",
                    "bb_pct", "momentum", "volatility"]
            return {k: round(float(v), 6) for k, v in zip(keys, sv) if v is not None}
        except Exception:
            return {}

    # ── live monitoring ───────────────────────────────────────────────────────

    def _monitor_loop(self) -> None:
        """Background loop: poll live algorithm status."""
        while not self._stop_event.is_set():
            try:
                self._check_live_algorithms()
                self._ingest_results()
            except Exception as exc:
                log.debug("[LeanAlgoManager] Monitor error: %s", exc)
            self._stop_event.wait(self.monitor_interval_secs)

    def _check_live_algorithms(self) -> None:
        """Poll QC API for live algorithm statuses."""
        engine = self.lean_deploy_engine
        if not engine or not getattr(engine, "_has_credentials", lambda: False)():
            return
        try:
            data = engine._api("GET", "live/read", None)
            lives = data.get("liveAlgorithms", [])
            running = [a for a in lives if a.get("status") == "Running"]
            if running:
                log.debug("[LeanAlgoManager] %d live algo(s) running", len(running))
                _notif_queue.push(f"[LeanAlgo] {len(running)} live algorithm(s) running on QC")
        except Exception as exc:
            log.debug("[LeanAlgoManager] Live poll failed: %s", exc)

    def _ingest_results(self) -> None:
        """Read results JSON written by 20_niblit_ai_master and store in KB."""
        if not self.results_file.exists():
            return
        try:
            data = json.loads(self.results_file.read_text())
            ts = data.get("timestamp", 0)
            # Only ingest if results are recent (last 5 minutes)
            if time.time() - float(ts) > 300:
                return

            summary = (
                f"LEAN AI Master — "
                f"PnL={data.get('total_pnl', 0):.2f}  "
                f"Trades={data.get('total_trades', 0)}  "
                f"WinRate={data.get('win_rate', 0):.1%}"
            )
            _notif_queue.push(f"[LeanAlgo] {summary}")
            log.info("[LeanAlgoManager] Ingested results: %s", summary)

            # Emit into the unified Kernel EventBus so LRN/INT layers can learn
            _emit_trading_event(EVT_TRADING_RESULTS, data)

            # Store in knowledge DB
            if self.knowledge_db and hasattr(self.knowledge_db, "add_fact"):
                try:
                    self.knowledge_db.add_fact(
                        f"lean_algo_results:{int(time.time())}",
                        json.dumps(data),
                        tags=["lean", "trading", "results"],
                    )
                except Exception:
                    pass
        except Exception as exc:
            log.debug("[LeanAlgoManager] Results ingest failed: %s", exc)

    # ── deployment helpers ────────────────────────────────────────────────────

    def deploy_all(self, dry_run: bool = False) -> str:
        """Deploy all algorithms in the niblit-lean-algos repo to QC Cloud."""
        engine = self.lean_deploy_engine
        if not engine:
            return "[LeanAlgoManager] LeanDeployEngine not available"
        if not getattr(engine, "_has_credentials", lambda: False)():
            return "[LeanAlgoManager] QC credentials not set (QC_USER_ID + QC_API_CRED)"

        algos_dir = self.algos_dir / "algorithms"
        if not algos_dir.exists():
            return f"[LeanAlgoManager] Algorithms directory not found: {algos_dir}"

        algo_dirs = sorted(
            d for d in algos_dir.iterdir()
            if d.is_dir() and (d / "main.py").exists()
        )

        if not algo_dirs:
            return "[LeanAlgoManager] No algorithm files found"

        results = []
        for d in algo_dirs:
            name = f"niblit-{d.name}"
            main_py = d / "main.py"
            content = main_py.read_text(encoding="utf-8")

            if dry_run:
                results.append(f"  [DRY] Would deploy: {name}")
                continue

            # Create + upload + compile
            r = engine._api("POST", "projects/create", {"name": name, "language": "Py"})
            if "error" in r:
                results.append(f"  ❌ {name}: {r['error']}")
                continue
            project_id = r.get("projects", [{}])[0].get("projectId")
            if not project_id:
                results.append(f"  ❌ {name}: no projectId returned")
                continue

            r2 = engine._api(
                "POST", "files/create",
                {"projectId": project_id, "name": "main.py", "content": content}
            )
            if "error" in r2:
                results.append(f"  ❌ {name}: upload failed: {r2['error']}")
                continue

            self._deployed_ids[d.name] = project_id
            results.append(f"  ✅ {name} → projectId={project_id}")
            time.sleep(2)

        self._save_deployed_ids()
        header = f"Deployed {len([r for r in results if '✅' in r])}/{len(algo_dirs)} algorithms:"
        return header + "\n" + "\n".join(results)

    def start_live(self, project_id: int, brokerage: str = "PaperBrokerage") -> str:
        """Start live trading for a project on the specified brokerage."""
        engine = self.lean_deploy_engine
        if not engine:
            return "[LeanAlgoManager] LeanDeployEngine not available"
        if not getattr(engine, "_has_credentials", lambda: False)():
            return "[LeanAlgoManager] QC credentials not set"
        r = engine._api("POST", "live/create", {
            "projectId": project_id,
            "compileId": "",
            "nodeId": "",
            "brokerageSettings": {"id": brokerage},
            "versionId": -1,
        })
        if "error" in r:
            return f"[LeanAlgoManager] Live start failed: {r['error']}"
        deploy_id = r.get("liveAlgorithm", {}).get("deployId", "?")
        return f"✅ Live algorithm started — deployId={deploy_id}"

    # ── status ────────────────────────────────────────────────────────────────

    def status(self) -> str:
        """Return a human-readable status summary."""
        signal_ok = self._last_signal is not None
        signal_age = (
            int(time.time() - float(self._last_signal.get("timestamp", 0)))
            if self._last_signal else -1
        )
        loop_running = bool(self._signal_thread and self._signal_thread.is_alive())
        deployed_count = len(self._deployed_ids)

        lines = [
            "=== LeanAlgoManager ===",
            f"  Signal loop:       {'✅ running' if loop_running else '⚠️  stopped'}",
            f"  Last signal:       {self._last_signal.get('signal','—') if signal_ok else '—'}",
            f"  Signal age:        {signal_age}s" if signal_age >= 0 else "  Signal age:        —",
            f"  Signal file:       {self.signal_file}",
            f"  Results file:      {self.results_file}",
            f"  Algos directory:   {self.algos_dir}",
            f"  Deployed projects: {deployed_count}",
            f"  TradingBrain:      {'✅' if self.trading_brain else '⚠️  not connected'}",
            f"  LeanDeployEngine:  {'✅' if self.lean_deploy_engine else '⚠️  not connected'}",
        ]
        if self._deployed_ids:
            lines.append("\n  Deployed project IDs:")
            for name, pid in list(self._deployed_ids.items())[:10]:
                lines.append(f"    [{pid}] {name}")

        lines += [
            "",
            "  Commands:",
            "    lean algo status",
            "    lean algo signal              — Show current Niblit signal",
            "    lean algo deploy-all          — Deploy all algorithms to QC",
            "    lean algo deploy-all dry-run  — Preview deployment plan",
            "    lean algo projects            — List deployed project IDs",
            "    lean algo start <project_id>  — Start live practice trading",
            "    lean algo stop  <project_id>  — Stop live algorithm",
            "    lean algo results             — Show latest AI Master results",
        ]
        return "\n".join(lines)

    def show_signal(self) -> str:
        """Return a formatted current signal string."""
        if not self._last_signal:
            return "No signal published yet. Start TradingBrain first: trading start"
        s = self._last_signal
        ts = datetime.fromtimestamp(float(s.get("timestamp", 0)), tz=timezone.utc)
        inds = s.get("indicators", {})
        lines = [
            f"📡 Niblit LEAN Signal [{ts.strftime('%H:%M:%S UTC')}]",
            f"  Signal:     {s.get('signal', '—')}",
            f"  Confidence: {float(s.get('confidence', 0)):.1%}",
            f"  Regime:     {s.get('regime', '—')}",
            f"  Risk %:     {float(s.get('risk_pct', 0)):.1%}",
        ]
        if inds:
            lines.append("  Indicators:")
            for k, v in list(inds.items())[:6]:
                lines.append(f"    {k}: {v:.4f}")
        return "\n".join(lines)

    def show_results(self) -> str:
        """Return the latest AI Master performance results."""
        if not self.results_file.exists():
            return "No results yet — AI Master algorithm hasn't written back results."
        try:
            data = json.loads(self.results_file.read_text())
            lines = [
                "📊 Niblit AI Master Results:",
                f"  Total PnL:   {data.get('total_pnl', 0):.2f}",
                f"  Total Trades:{data.get('total_trades', 0)}",
                f"  Win Rate:    {float(data.get('win_rate', 0)):.1%}",
                f"  Portfolio:   {data.get('portfolio_value', 0):.2f}",
                f"  Last update: {data.get('last_updated', '—')}",
            ]
            return "\n".join(lines)
        except Exception as exc:
            return f"[LeanAlgoManager] Failed to read results: {exc}"

    def list_projects(self) -> str:
        """List all locally tracked deployed project IDs."""
        if not self._deployed_ids:
            return "No deployed projects tracked. Run 'lean algo deploy-all' first."
        lines = ["Deployed project IDs:"]
        for name, pid in self._deployed_ids.items():
            lines.append(f"  [{pid}] {name}")
        return "\n".join(lines)

    # ── persistence ───────────────────────────────────────────────────────────

    def _deployed_ids_file(self) -> Path:
        return _REPO_ROOT / "niblit_lean_deployed_projects.json"

    def _load_deployed_ids(self) -> None:
        f = self._deployed_ids_file()
        if f.exists():
            try:
                self._deployed_ids = json.loads(f.read_text())
            except Exception:
                pass

    def _save_deployed_ids(self) -> None:
        try:
            self._deployed_ids_file().write_text(json.dumps(self._deployed_ids, indent=2))
        except Exception:
            pass

    # ── utilities ─────────────────────────────────────────────────────────────

    @staticmethod
    def _write_json(path: Path, data: Dict[str, Any]) -> None:
        """Atomically write JSON to a file (write to tmp then rename)."""
        tmp = path.with_suffix(".tmp")
        try:
            tmp.write_text(json.dumps(data, indent=2))
            tmp.rename(path)
        except Exception as exc:
            log.debug("[LeanAlgoManager] JSON write failed %s: %s", path, exc)


if __name__ == "__main__":
    print('Running lean_algo_manager.py')
