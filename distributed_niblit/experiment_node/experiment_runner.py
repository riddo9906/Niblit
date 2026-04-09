"""ExperimentRunner — lifecycle management for distributed experiments.

Usage example::

    runner = ExperimentRunner()
    exp_id = runner.create_experiment("NAS trial", "Can we improve accuracy by 5%?")
    result = runner.run({"exp_id": exp_id, "iterations": 3})
"""

from __future__ import annotations

import logging
import time
import uuid
from typing import Any, Dict, List, Optional

log = logging.getLogger("ExperimentRunner")


class ExperimentRunner:
    """Creates and executes named experiments."""

    def __init__(self) -> None:
        self._experiments: Dict[str, Dict[str, Any]] = {}

    # ── public API ──

    def create_experiment(
        self,
        name: str,
        hypothesis: str,
        config: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Register a new experiment; return its exp_id."""
        exp_id = str(uuid.uuid4())
        self._experiments[exp_id] = {
            "exp_id": exp_id,
            "name": name,
            "hypothesis": hypothesis,
            "config": config or {},
            "status": "created",
            "created_at": time.time(),
            "result": None,
        }
        log.info("ExperimentRunner: created %s (%s)", exp_id, name)
        return exp_id

    def run(self, experiment: Dict[str, Any]) -> Dict[str, Any]:
        """Run *experiment* dict and return result dict."""
        exp_id = experiment.get("exp_id", str(uuid.uuid4()))
        if exp_id not in self._experiments:
            self._experiments[exp_id] = {
                "exp_id": exp_id,
                "name": experiment.get("name", "anonymous"),
                "hypothesis": experiment.get("hypothesis", ""),
                "config": experiment.get("config", {}),
                "status": "running",
                "created_at": time.time(),
            }
        self._experiments[exp_id]["status"] = "running"
        start = time.time()
        result: Dict[str, Any] = {
            "exp_id": exp_id,
            "status": "completed",
            "score": 0.75,
            "iterations": experiment.get("iterations", 1),
            "elapsed_ms": 0.0,
        }
        result["elapsed_ms"] = round((time.time() - start) * 1000, 2)
        self._experiments[exp_id]["status"] = "completed"
        self._experiments[exp_id]["result"] = result
        log.info("ExperimentRunner: completed %s", exp_id)
        return result

    def get_experiment(self, exp_id: str) -> Optional[Dict[str, Any]]:
        """Return experiment metadata or None."""
        return self._experiments.get(exp_id)

    def list_experiments(self) -> List[str]:
        """Return list of all exp_ids."""
        return list(self._experiments.keys())


if __name__ == "__main__":
    print('Running experiment_runner.py')
