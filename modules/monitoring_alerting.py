#!/usr/bin/env python3
"""
Monitoring & Alerting - Prometheus integration

Alert management system with Prometheus metrics integration and
notification support.

Features:
- Alert definitions
- Alert triggering based on conditions
- Notification system
- Prometheus metrics export
- Alert history
"""

import logging
import asyncio
from typing import Dict, List, Callable, Optional, Any
from enum import Enum
from dataclasses import dataclass, field
from datetime import datetime

log = logging.getLogger("MonitoringAlerting")


class AlertSeverity(Enum):
    """Alert severity levels."""
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"
    EMERGENCY = "emergency"


@dataclass
class Alert:
    """Alert definition."""
    name: str
    condition: Callable[[Dict[str, Any]], bool]
    severity: AlertSeverity
    message: str
    actions: List[Callable] = field(default_factory=list)
    enabled: bool = True


@dataclass
class AlertEvent:
    """Alert event record."""
    alert_name: str
    timestamp: float = field(default_factory=lambda: datetime.now().timestamp())
    severity: AlertSeverity = AlertSeverity.INFO
    message: str = ""
    data: Dict[str, Any] = field(default_factory=dict)


class AlertManager:
    """
    Manage alerts and notifications.
    
    Features:
    - Alert registration
    - Condition evaluation
    - Action triggering
    - Alert history
    """
    
    def __init__(self):
        self.alerts: Dict[str, Alert] = {}
        self.triggered: set = set()
        self.history: List[AlertEvent] = []
        self.metrics = {
            "triggered": 0,
            "resolved": 0,
            "errors": 0,
        }
        log.debug("AlertManager initialized")
    
    def register_alert(self, alert: Alert):
        """
        Register an alert.
        
        Args:
            alert: Alert definition
        """
        self.alerts[alert.name] = alert
        log.info(f"Alert registered: {alert.name}")
    
    def register_alerts(self, alerts: List[Alert]):
        """Register multiple alerts."""
        for alert in alerts:
            self.register_alert(alert)
    
    async def check_alerts(self, metrics: Dict[str, Any]) -> List[AlertEvent]:
        """
        Check all alerts against metrics.
        
        Args:
            metrics: Current metrics
            
        Returns:
            List of triggered alerts
        """
        triggered_alerts = []
        
        for name, alert in self.alerts.items():
            if not alert.enabled:
                continue
            
            try:
                # Check condition
                if alert.condition(metrics):
                    if name not in self.triggered:
                        # Alert triggered
                        self.triggered.add(name)
                        self.metrics["triggered"] += 1
                        
                        # Execute actions
                        for action in alert.actions:
                            try:
                                if asyncio.iscoroutinefunction(action):
                                    await action()
                                else:
                                    action()
                            except Exception as e:
                                log.error(f"Action failed: {e}")
                                self.metrics["errors"] += 1
                        
                        # Record event
                        event = AlertEvent(
                            alert_name=name,
                            severity=alert.severity,
                            message=alert.message,
                            data=metrics.copy()
                        )
                        self.history.append(event)
                        triggered_alerts.append(event)
                        
                        log.warning(f"Alert triggered: {name} ({alert.severity.value})")
                else:
                    # Alert resolved
                    if name in self.triggered:
                        self.triggered.discard(name)
                        self.metrics["resolved"] += 1
                        log.info(f"Alert resolved: {name}")
                        
            except Exception as e:
                log.error(f"Alert check failed: {name}: {e}")
                self.metrics["errors"] += 1
        
        return triggered_alerts
    
    def get_active_alerts(self) -> List[str]:
        """Get list of currently triggered alerts."""
        return list(self.triggered)
    
    def get_history(self, limit: int = 100) -> List[AlertEvent]:
        """Get alert history."""
        return self.history[-limit:]
    
    def get_stats(self) -> Dict[str, Any]:
        """Get alert manager statistics."""
        return {
            "registered_alerts": len(self.alerts),
            "active_alerts": len(self.triggered),
            "history_size": len(self.history),
            **self.metrics,
        }


# Example usage
if __name__ == "__main__":
    import asyncio
    
    async def test():
        manager = AlertManager()
        
        # Define alerts
        high_error_rate = Alert(
            name="high_error_rate",
            condition=lambda m: m.get("error_rate", 0) > 0.05,
            severity=AlertSeverity.CRITICAL,
            message="Error rate exceeds 5%",
            actions=[lambda: print("Action: High error rate detected!")]
        )
        
        high_latency = Alert(
            name="high_latency",
            condition=lambda m: m.get("latency_ms", 0) > 1000,
            severity=AlertSeverity.WARNING,
            message="Latency exceeds 1 second",
        )
        
        manager.register_alerts([high_error_rate, high_latency])
        
        # Check alerts
        metrics = {"error_rate": 0.08, "latency_ms": 500}
        events = await manager.check_alerts(metrics)
        print(f"Triggered: {[e.alert_name for e in events]}")
        
        # Get stats
        print(f"Stats: {manager.get_stats()}")
    
    asyncio.run(test())
