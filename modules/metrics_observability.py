#!/usr/bin/env python3
"""
Metrics & Observability - Prometheus integration

Comprehensive metrics collection and observability for production systems.
Integrates with Prometheus, Grafana, and Jaeger for full system visibility.

Features:
- Metric collection and aggregation
- Histogram tracking
- Timing and latency measurements
- Trace context support
- Prometheus export format
"""

import time
import logging
from typing import Dict, Any, Optional, List
from dataclasses import dataclass, field
from contextlib import asynccontextmanager
from datetime import datetime

log = logging.getLogger("Observability")


@dataclass
class MetricSnapshot:
    """Snapshot of metric values."""
    name: str
    value: float
    timestamp: float = field(default_factory=time.time)
    labels: Dict[str, str] = field(default_factory=dict)
    
    def to_prometheus(self) -> str:
        """Convert to Prometheus format."""
        labels_str = ""
        if self.labels:
            labels_list = [f'{k}="{v}"' for k, v in self.labels.items()]
            labels_str = "{" + ",".join(labels_list) + "}"
        
        return f"{self.name}{labels_str} {self.value} {int(self.timestamp * 1000)}"


class TelemetryCollector:
    """
    Collect and aggregate metrics for observability.
    
    Features:
    - Counters (monotonic increasing)
    - Gauges (point-in-time values)
    - Histograms (distribution of values)
    - Traces (operation timing)
    """
    
    def __init__(self):
        self.counters: Dict[str, int] = {}
        self.gauges: Dict[str, float] = {}
        self.histograms: Dict[str, List[float]] = {}
        self.traces: List[Dict[str, Any]] = []
        log.debug("TelemetryCollector initialized")
    
    def increment_counter(self, name: str, value: int = 1):
        """Increment counter metric."""
        if name not in self.counters:
            self.counters[name] = 0
        self.counters[name] += value
    
    def set_gauge(self, name: str, value: float):
        """Set gauge metric."""
        self.gauges[name] = value
    
    def record_histogram(self, name: str, value: float):
        """Record histogram value."""
        if name not in self.histograms:
            self.histograms[name] = []
        self.histograms[name].append(value)
    
    @asynccontextmanager
    async def observe(self, operation: str, **labels):
        """
        Context manager for observing operation timing.
        
        Args:
            operation: Operation name
            **labels: Additional labels for categorization
        """
        start_time = time.time()
        trace = {
            "operation": operation,
            "start_time": start_time,
            "labels": labels,
        }
        
        try:
            yield
        except Exception as e:
            trace["error"] = str(e)
            raise
        finally:
            duration = time.time() - start_time
            trace["duration"] = duration
            trace["end_time"] = time.time()
            
            self.record_histogram(f"{operation}_duration_ms", duration * 1000)
            self.traces.append(trace)
    
    def get_histogram_stats(self, name: str) -> Dict[str, float]:
        """Get statistics for histogram."""
        values = self.histograms.get(name, [])
        if not values:
            return {}
        
        return {
            "count": len(values),
            "sum": sum(values),
            "avg": sum(values) / len(values),
            "min": min(values),
            "max": max(values),
            "p50": self._percentile(values, 50),
            "p95": self._percentile(values, 95),
            "p99": self._percentile(values, 99),
        }
    
    @staticmethod
    def _percentile(values: List[float], p: float) -> float:
        """Calculate percentile."""
        if not values:
            return 0
        sorted_vals = sorted(values)
        idx = int((p / 100) * len(sorted_vals))
        return sorted_vals[min(idx, len(sorted_vals) - 1)]
    
    def export_prometheus(self) -> str:
        """Export metrics in Prometheus format."""
        lines = []
        
        # Counters
        for name, value in self.counters.items():
            lines.append(f"{name}_total {value}")
        
        # Gauges
        for name, value in self.gauges.items():
            lines.append(f"{name} {value}")
        
        # Histograms
        for name, values in self.histograms.items():
            if values:
                lines.append(f"{name}_bucket{{le=\"+Inf\"}} {len(values)}")
                lines.append(f"{name}_count {len(values)}")
                lines.append(f"{name}_sum {sum(values)}")
        
        return "\n".join(lines)
    
    def get_stats(self) -> Dict[str, Any]:
        """Get all statistics."""
        return {
            "counters": self.counters,
            "gauges": self.gauges,
            "histograms": {
                name: self.get_histogram_stats(name)
                for name in self.histograms
            },
            "traces": len(self.traces),
        }


# Example usage
if __name__ == "__main__":
    import asyncio
    
    async def test():
        telemetry = TelemetryCollector()
        
        # Record some metrics
        telemetry.increment_counter("requests_total")
        telemetry.set_gauge("active_connections", 42)
        telemetry.record_histogram("latency_ms", 125.5)
        
        # Use context manager
        async with telemetry.observe("test_operation", user_id="123"):
            await asyncio.sleep(0.1)
        
        print("Stats:", telemetry.get_stats())
        print("\nPrometheus format:")
        print(telemetry.export_prometheus())
    
    asyncio.run(test())
