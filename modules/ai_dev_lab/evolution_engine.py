#!/usr/bin/env python3
"""
modules/ai_dev_lab/evolution_engine.py

Evolve Niblit itself by detecting weaknesses, designing improvements,
and deploying upgrades.

Pipeline::

    weakness detection
          ↓
    hypothesis generation
          ↓
    architecture design + code synthesis
          ↓
    benchmark evaluation
          ↓
    deploy if improvement > baseline

The engine writes evolved modules to the ``evolved/`` directory and
optionally triggers a hot-reload via LiveUpdater.

Usage::

    from modules.ai_dev_lab.evolution_engine import EvolutionEngine
    engine = EvolutionEngine(lab=ai_dev_lab_instance)
    result = engine.evolve()
"""

import logging
import os
import time
from typing import Any, Dict, List, Optional

log = logging.getLogger("EvolutionEngine")

_EVOLVED_DIR = os.path.join(os.getcwd(), "evolved")
_IMPROVEMENT_PREFIX = "improvement_"


class EvolutionEngine:
    """
    Drive the self-evolution loop for Niblit.

    Args:
        lab:       AIDevLab instance (used for hypothesis generation + benchmarking).
        deploy:    When True, write improved modules to evolved/ directory.
        live_reload: When True, trigger LiveUpdater after deployment.
    """

    def __init__(
        self,
        lab: Optional[Any] = None,
        deploy: bool = False,
        live_reload: bool = False,
    ) -> None:
        self._lab = lab
        self._deploy = deploy
        self._live_reload = live_reload
        self._baseline: float = 0.0
        self._evolutions: List[Dict[str, Any]] = []

    # ── public API ────────────────────────────────────────────────────────────

    def evolve(
        self, domain_hint: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Execute one full evolution cycle.

        Returns a summary dict.
        """
        result: Dict[str, Any] = {
            "evolved": False,
            "improvement": 0.0,
            "deployed": False,
            "module_path": "",
            "performance": 0.0,
        }

        if self._lab is None:
            log.warning("EvolutionEngine: no AIDevLab instance — skipping")
            return result

        # 1 — Detect weakness
        weakness = self._detect_weakness()

        # 2 — Run a full lab cycle (hypothesis + design + synthesize + benchmark)
        try:
            lab_result = self._lab.run_cycle(domain_hint=domain_hint or weakness)
            perf = float(lab_result.get("performance", 0.0))
            result["performance"] = perf
        except Exception as exc:  # noqa: BLE001
            log.warning("EvolutionEngine: lab cycle failed: %s", exc)
            return result

        # 3 — Check improvement
        if perf > self._baseline:
            improvement = round(perf - self._baseline, 3)
            result["evolved"] = True
            result["improvement"] = improvement
            self._baseline = perf

            # 4 — Deploy
            if self._deploy:
                path = self._deploy_improvement(lab_result)
                result["deployed"] = bool(path)
                result["module_path"] = path

            self._evolutions.append({
                "timestamp": time.time(),
                "performance": perf,
                "improvement": improvement,
                "domain": domain_hint or weakness,
            })
            log.info(
                "EvolutionEngine: evolved — perf=%.3f improvement=%.3f",
                perf, improvement,
            )

        return result

    def evolve_loop(
        self,
        max_cycles: int = 10,
        domain_hint: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Run up to *max_cycles* evolution cycles.  Returns list of results."""
        results = []
        for _ in range(max_cycles):
            results.append(self.evolve(domain_hint=domain_hint))
        return results

    def history(self) -> List[Dict[str, Any]]:
        return list(self._evolutions)

    def stats(self) -> Dict[str, Any]:
        return {
            "evolutions": len(self._evolutions),
            "baseline": self._baseline,
            "best_improvement": max((e["improvement"] for e in self._evolutions), default=0.0),
        }

    # ── internals ─────────────────────────────────────────────────────────────

    @staticmethod
    def _detect_weakness() -> str:
        """
        Placeholder weakness detector.

        In a full deployment this would analyse benchmark history, memory
        profiles, and error logs.
        """
        weaknesses = [
            "code generation speed",
            "memory retrieval accuracy",
            "planning depth",
            "pattern recognition coverage",
        ]
        import random  # noqa: PLC0415
        return random.choice(weaknesses)

    def _deploy_improvement(self, lab_result: Dict[str, Any]) -> str:
        """Write the improved code to the evolved/ directory."""
        code = lab_result.get("code", "")
        if not code:
            return ""
        try:
            os.makedirs(_EVOLVED_DIR, exist_ok=True)
            ts = int(time.time())
            filename = f"{_IMPROVEMENT_PREFIX}{ts}.py"
            path = os.path.join(_EVOLVED_DIR, filename)
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(f"# Auto-generated by EvolutionEngine at {time.ctime(ts)}\n")
                fh.write(f"# Performance: {lab_result.get('performance', 0.0):.3f}\n\n")
                fh.write(code)
            log.info("EvolutionEngine: deployed to %s", path)

            if self._live_reload:
                self._trigger_live_reload()

            return path
        except Exception as exc:  # noqa: BLE001
            log.warning("EvolutionEngine._deploy_improvement: %s", exc)
            return ""

    @staticmethod
    def _trigger_live_reload() -> None:
        try:
            from modules.live_updater import LiveUpdater  # type: ignore[import]
            LiveUpdater().reload_all_changed()
        except Exception as exc:  # noqa: BLE001
            log.debug("EvolutionEngine: live reload failed: %s", exc)
