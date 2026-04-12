#!/usr/bin/env python3
"""
modules/trading_adapter.py — Trading Brain Adapter
===================================================
Wraps the :class:`~modules.trading_brain.TradingBrain` (Autonomous
Trading Brain + LEAN + Kelly sizing) so the
:class:`~modules.niblit_cognitive_graph_kernel.CognitiveGraphKernel`
can execute **one** trading cycle per FortressCycle tick.

This engine is orchestrated by CognitiveGraphKernel via adapters.
Do not start a standalone infinite loop here.
"""
from __future__ import annotations

import logging
import time
from typing import Any, Dict, Optional

log = logging.getLogger(__name__)


def get_market_state(universe_id: str) -> Dict[str, Any]:
    """
    Fetch a lightweight snapshot of the current market state for *universe_id*.

    Returns a dict with ``symbol``, ``latest_price``, ``timestamp``,
    ``available`` bool, and any error message.
    """
    start = time.time()
    try:
        from modules.trading_brain import get_trading_brain
        brain = get_trading_brain()
        snapshot = {}
        if hasattr(brain, "get_market_snapshot"):
            snapshot = brain.get_market_snapshot()
        elif hasattr(brain, "_fetch_market_data"):
            raw = brain._fetch_market_data()  # noqa: SLF001
            if raw:
                snapshot = {"raw_length": len(raw)}
        return {
            "available": True,
            "universe_id": universe_id,
            "elapsed_secs": round(time.time() - start, 2),
            **snapshot,
        }
    except ImportError:
        return {"available": False, "universe_id": universe_id, "error": "TradingBrain not available"}
    except Exception as exc:  # noqa: BLE001
        return {"available": False, "universe_id": universe_id, "error": str(exc)[:200]}


def execute_trading_plan(
    universe_id: str,
    step_timeout: float = 90.0,
) -> Dict[str, Any]:
    """
    Execute **one** full trading cycle (observe → engineer → decide) for
    *universe_id* via ``TradingBrain.cycle()``.

    Returns a result dict with ``success``, ``decision``, ``elapsed_secs``,
    ``error``.
    """
    start = time.time()
    try:
        from modules.trading_brain import get_trading_brain
        brain = get_trading_brain()

        decision: Optional[str] = None
        import threading
        box: Dict[str, Any] = {}

        def _run() -> None:
            try:
                box["decision"] = brain.cycle()
            except Exception as exc:  # noqa: BLE001
                box["error"] = str(exc)

        t = threading.Thread(target=_run, daemon=True)
        t.start()
        t.join(timeout=step_timeout)

        if "decision" in box:
            decision = box["decision"]
        elif "error" in box:
            return {
                "success": False,
                "universe_id": universe_id,
                "decision": "HOLD",
                "elapsed_secs": round(time.time() - start, 2),
                "error": box["error"][:200],
            }
        else:
            return {
                "success": False,
                "universe_id": universe_id,
                "decision": "HOLD",
                "elapsed_secs": round(time.time() - start, 2),
                "error": "timeout",
            }

        return {
            "success": True,
            "universe_id": universe_id,
            "decision": decision,
            "elapsed_secs": round(time.time() - start, 2),
            "error": None,
        }
    except ImportError:
        return {
            "success": False,
            "universe_id": universe_id,
            "decision": "HOLD",
            "elapsed_secs": round(time.time() - start, 2),
            "error": "TradingBrain not available",
        }
    except Exception as exc:  # noqa: BLE001
        log.debug("[trading_adapter] error: %s", exc)
        return {
            "success": False,
            "universe_id": universe_id,
            "decision": "HOLD",
            "elapsed_secs": round(time.time() - start, 2),
            "error": str(exc)[:200],
        }
