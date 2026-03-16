#!/usr/bin/env python3
"""
modules/ai_dev_lab/lab_controller.py

Orchestrate the entire Self-Evolving AI Development Lab (SEADL).

Responsibilities:
    - manage experiment lifecycle (create → run → evaluate → store)
    - coordinate all sub-agents
    - schedule research cycles
    - publish discoveries

The lab can run a single cycle or a continuous autonomous loop.

Usage::

    from modules.ai_dev_lab.lab_controller import AIDevLab
    lab = AIDevLab()
    results = lab.run_cycle()
    lab.run_loop(max_cycles=10)
"""

import logging
import time
from typing import Any, Dict, List, Optional

from modules.ai_dev_lab.hypothesis_generator import HypothesisGenerator
from modules.ai_dev_lab.research_agent import ResearchAgent
from modules.ai_dev_lab.architecture_designer import ArchitectureDesigner
from modules.ai_dev_lab.algorithm_inventor import AlgorithmInventor
from modules.ai_dev_lab.code_synthesizer import CodeSynthesizer
from modules.ai_dev_lab.benchmark_engine import BenchmarkEngine
from modules.ai_dev_lab.experiment_database import ExperimentDatabase
from modules.ai_dev_lab.discovery_engine import DiscoveryEngine
from modules.ai_dev_lab.experiment_manager import ExperimentManager
from modules.ai_dev_lab.safety_guard import SafetyGuard

log = logging.getLogger("AIDevLab")

_DEFAULT_DB_PATH = "ai_dev_lab.db"


class AIDevLab:
    """
    Autonomous AI Development Lab.

    Orchestrates hypothesis generation, research, architecture design,
    code synthesis, benchmarking, and self-evolution.

    Args:
        llm:         Optional LLM adapter (generate(prompt) → str).
        graph:       Optional PatternGraphBuilder for enriched hypotheses.
        db_path:     Path to experiment SQLite database.
        deploy:      When True, the EvolutionEngine writes improvement modules.
    """

    def __init__(
        self,
        llm: Optional[Any] = None,
        graph: Optional[Any] = None,
        db_path: str = _DEFAULT_DB_PATH,
        deploy: bool = False,
    ) -> None:
        self._llm = llm

        # Sub-systems
        self.hypothesis_gen = HypothesisGenerator(graph=graph)
        self.research = ResearchAgent()
        self.architecture = ArchitectureDesigner()
        self.algorithm = AlgorithmInventor(graph=graph)
        self.code = CodeSynthesizer(llm=llm)
        self.benchmark = BenchmarkEngine()
        self.db = ExperimentDatabase(db_path=db_path)
        self.discovery = DiscoveryEngine()
        self.experiments = ExperimentManager(db=self.db)
        self.guard = SafetyGuard()

        self._cycles: int = 0
        self._discoveries: List[Dict[str, Any]] = []

    # ── public API ────────────────────────────────────────────────────────────

    def run_cycle(
        self,
        domain_hint: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Execute one full lab cycle.

        Returns a summary dict with keys:
            cycle, hypothesis, architecture, code, performance, discovery
        """
        self._cycles += 1
        cycle_start = time.time()

        # 1 — Generate hypothesis
        hypothesis = self.hypothesis_gen.generate(domain_hint=domain_hint)
        log.info("AIDevLab cycle %d: hypothesis='%s'", self._cycles, hypothesis["hypothesis"][:80])

        # 2 — Research
        research_findings = self.research.research(hypothesis["hypothesis"])

        # 3 — Design architecture
        arch_spec = self.architecture.design(hypothesis)

        # 4 — Invent algorithm
        algo = self.algorithm.invent(hypothesis["hypothesis"])

        # 5 — Synthesize code
        synth_result = self.code.generate(arch_spec)
        code_str = synth_result.get("code", "")

        # 6 — Benchmark
        benchmark_results = self.benchmark.evaluate(code_str, label=hypothesis["hypothesis"][:60])

        # 7 — Store in experiment DB
        exp_id = self.experiments.create(hypothesis, arch_spec)
        self.experiments.start(exp_id)
        self.experiments.complete(exp_id, code=code_str, benchmark_results=benchmark_results)

        # 8 — Detect discoveries
        discovery = self.discovery.detect(benchmark_results)
        if discovery:
            self._discoveries.append(discovery)
            self.publish(discovery)

        elapsed = round(time.time() - cycle_start, 2)
        return {
            "cycle": self._cycles,
            "hypothesis": hypothesis["hypothesis"],
            "architecture": arch_spec.get("name", ""),
            "algorithm": algo.get("name", ""),
            "code": code_str,
            "performance": benchmark_results.get("performance", 0.0),
            "discovery": discovery,
            "elapsed_s": elapsed,
        }

    def run_loop(
        self,
        max_cycles: Optional[int] = None,
        interval_seconds: float = 0.0,
        domain_hint: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """
        Run cycles continuously until *max_cycles* is reached.

        Args:
            max_cycles:       Stop after this many cycles (None = run forever).
            interval_seconds: Sleep between cycles.
            domain_hint:      Optional domain to focus on.
        """
        results = []
        log.info("AIDevLab: entering loop (max_cycles=%s)", max_cycles)
        while True:
            result = self.run_cycle(domain_hint=domain_hint)
            results.append(result)
            if max_cycles and self._cycles >= max_cycles:
                break
            if interval_seconds > 0:
                time.sleep(interval_seconds)
        return results

    def publish(self, discovery: Dict[str, Any]) -> None:
        """
        Publish a discovery.  Currently logs; extend to push to GitHub / KB.
        """
        log.info(
            "AIDevLab: DISCOVERY published — type=%s perf=%.3f",
            discovery.get("type", ""),
            discovery.get("performance", 0.0),
        )

    def generate_hypothesis(
        self, domain_hint: Optional[str] = None
    ) -> Dict[str, Any]:
        """Public alias for hypothesis_gen.generate()."""
        return self.hypothesis_gen.generate(domain_hint=domain_hint)

    def stats(self) -> Dict[str, Any]:
        return {
            "cycles": self._cycles,
            "discoveries": len(self._discoveries),
            "experiments": self.experiments.stats(),
            "db_count": self.db.count(),
        }
