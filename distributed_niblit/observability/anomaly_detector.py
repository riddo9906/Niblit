"""AnomalyDetector — Z-score based anomaly detection for cluster metrics.

Usage example::

    detector = AnomalyDetector()
    detector.set_threshold("cpu", mean=0.5, stddev=0.1)
    detector.observe("cpu", 0.95)
    anomalies = detector.get_anomalies()
"""

from __future__ import annotations

import logging
import math
import time
from typing import Any, Dict, List

log = logging.getLogger("AnomalyDetector")

_Z_THRESHOLD = 3.0


class AnomalyDetector:
    """Detects anomalous metric values using configurable mean/stddev bounds."""

    def __init__(self) -> None:
        self._thresholds: Dict[str, Dict[str, float]] = {}
        self._observations: List[Dict[str, Any]] = []
        self._anomalies: List[Dict[str, Any]] = []

    # ── public API ──

    def set_threshold(self, metric_name: str, mean: float, stddev: float) -> None:
        """Set expected *mean* and *stddev* for *metric_name*."""
        self._thresholds[metric_name] = {"mean": mean, "stddev": max(stddev, 1e-9)}
        log.debug("AnomalyDetector: threshold set for %s mean=%.3f std=%.3f", metric_name, mean, stddev)

    def observe(self, metric_name: str, value: float) -> None:
        """Record an observation; auto-flag if anomalous."""
        obs: Dict[str, Any] = {"metric": metric_name, "value": value, "ts": time.time()}
        self._observations.append(obs)
        if self.is_anomalous(metric_name, value):
            obs["anomalous"] = True
            self._anomalies.append(obs)
            log.warning("AnomalyDetector: anomaly detected %s=%.4f", metric_name, value)

    def is_anomalous(self, metric_name: str, value: float) -> bool:
        """Return True if *value* is beyond Z-score threshold for *metric_name*."""
        params = self._thresholds.get(metric_name)
        if params is None:
            return False
        z = abs(value - params["mean"]) / params["stddev"]
        return z > _Z_THRESHOLD

    def get_anomalies(self) -> List[Dict[str, Any]]:
        """Return all detected anomaly records."""
        return list(self._anomalies)
