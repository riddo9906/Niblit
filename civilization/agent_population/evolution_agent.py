"""EvolutionAgent — detects weaknesses and proposes system improvements.

Usage example::

    agent = EvolutionAgent("ev1", "evolution_agent")
    result = agent.execute({"system_state": {"accuracy": 0.6}})
"""

from __future__ import annotations

import logging
import time
from typing import Any, Dict

from .base_agent import BaseAgent

log = logging.getLogger("EvolutionAgent")


class EvolutionAgent(BaseAgent):
    """Drives continuous improvement through hypothesis-experiment cycles."""

    # ── public API ──

    def execute(self, task: Dict[str, Any]) -> Dict[str, Any]:
        """Execute evolution task; return improvement/deployed/hypothesis dict."""
        state = task.get("system_state", {})
        weakness = self.detect_weakness(state)
        hypothesis = self.generate_hypothesis(weakness)
        experiment_result = self.run_experiment(hypothesis)
        result = {
            "improvement": hypothesis.get("proposed_fix", "none"),
            "deployed": experiment_result.get("success", False),
            "hypothesis": hypothesis,
            "evolved_at": time.time(),
        }
        self._record_task()
        log.info("EvolutionAgent %s: weakness=%s", self._agent_id, weakness[:60])
        return result

    def detect_weakness(self, system_state: Dict[str, Any]) -> str:
        """Identify primary weakness from *system_state*."""
        accuracy = system_state.get("accuracy", 1.0)
        latency = system_state.get("latency_ms", 0)
        if accuracy < 0.7:
            return "low_accuracy"
        if latency > 500:
            return "high_latency"
        return "stable"

    def generate_hypothesis(self, weakness: str) -> Dict[str, Any]:
        """Return hypothesis dict for the detected *weakness*."""
        fixes: Dict[str, str] = {
            "low_accuracy": "Add more training data and tune hyperparameters.",
            "high_latency": "Cache frequent queries and optimise hot paths.",
            "stable": "Explore new architectures for marginal gains.",
        }
        return {
            "weakness": weakness,
            "proposed_fix": fixes.get(weakness, "Investigate further."),
            "confidence": 0.7,
        }

    def run_experiment(self, hypothesis: Dict[str, Any]) -> Dict[str, Any]:
        """Simulate running *hypothesis* as an experiment."""
        return {
            "hypothesis": hypothesis,
            "success": True,
            "improvement_delta": 0.05,
            "ran_at": time.time(),
        }
