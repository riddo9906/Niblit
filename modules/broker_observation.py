"""Versioned read-only broker observation consumed by Core and both Desk shells."""
from dataclasses import dataclass, asdict
from decimal import Decimal, InvalidOperation
import math
from typing import Any

VERSION = "niblit.broker-observation/1"

def number(value):
    if isinstance(value, bool) or value is None:
        return None
    try:
        result = float(Decimal(str(value)))
        return result if math.isfinite(result) else None
    except (ValueError, TypeError, InvalidOperation):
        return None

@dataclass(frozen=True)
class BrokerObservation:
    schema_version: str
    gateway: dict[str, Any]
    account: dict[str, Any] | None
    balances: dict[str, float | None]
    positions: list[dict] | None
    pending_orders: list[dict] | None
    history: dict[str, Any] | None
    observation_at: float | None
    received_at: float | None
    core_synchronized_at: float
    freshness: str
    broker_authenticated: bool | None
    inventory_fresh: bool
    reconciliation: dict[str, Any]
    emergency_stop_active: bool | None
    execution_breaker_latched: bool | None
    execution_permitted: bool
    execution_disabled_reasons: list[str]
    last_verified: dict[str, Any] | None
    warnings: list[str]

def normalize(remote, *, now, received_at=None, last_verified=None):
    raw = remote.get("observation") or {}
    snap = raw.get("account_observation") or {}
    observed = number(snap.get("observed_at"))
    # Wall-clock source age and client freshness must both pass. No missing timestamp fallback.
    age = now - observed if observed is not None else None
    fresh = remote.get("broker_verified") is True and age is not None and 0 <= age < 30
    inventory_fresh = fresh and isinstance(snap.get("positions"), list) and isinstance(snap.get("orders"), list)
    fields = {k: number(snap.get(src)) if fresh else None for k, src in (
        ("balance", "balance"), ("equity", "equity"), ("margin", "margin"), ("free_margin", "free_margin"))}
    warnings = list(remote.get("last_probe_reasons") or [])
    if fresh and any(v is None for v in fields.values()):
        warnings.append("account_fields_unknown")
    if fresh and not inventory_fresh:
        warnings.append("inventory_unavailable")
    breaker = remote.get("breaker")
    recon = raw.get("reconciliation") or {"status": "UNKNOWN", "history_scope": "UNKNOWN",
        "complete": False, "warnings": ["gateway_reconciliation_evidence_unavailable"]}
    reasons = ["milestone_read_only", "funded_execution_disabled"]
    if breaker and breaker != "ENTRY_SUSPENDED": reasons.append("execution_breaker_latched")
    if not fresh: reasons.append("broker_observation_unavailable_or_stale")
    if not inventory_fresh: reasons.append("inventory_not_fresh")
    if recon.get("complete") is not True: reasons.append("reconciliation_incomplete")
    return asdict(BrokerObservation(
        VERSION,
        {"reachable": remote.get("gateway_reachable") is True,
         "identity": raw.get("gateway_id"), "version": remote.get("gateway_version"),
         "latency_ms": remote.get("latency_ms"),
         "status": "read_only_operational" if fresh and inventory_fresh else
                   "unverified" if remote.get("gateway_reachable") else "reconnecting",
         "health": raw.get("health") or {}, "transport": "ssh_forward",
         "ssh_peer_verified": remote.get("ssh_peer_verified")},
        snap.get("account") if fresh else None, fields,
        snap.get("positions") if inventory_fresh else None,
        snap.get("orders") if inventory_fresh else None,
        {"orders": raw.get("history", {}).get("history_orders"),
         "deals": raw.get("history", {}).get("history_deals"),
         "checkpoint": raw.get("history_checkpoint"),
         "coverage": recon.get("history_coverage"),
         "note": "Balance/cashflow deals are not trading profits"} if fresh else None,
        observed if fresh else None, received_at, now,
        "fresh" if fresh else "stale" if last_verified else "unavailable",
        True if fresh else None, inventory_fresh, recon,
        breaker == "EMERGENCY_STOP" if breaker else None,
        breaker != "ENTRY_SUSPENDED" if breaker else None, False, reasons,
        last_verified if not fresh else None, warnings + ([remote["error"]] if remote.get("error") else [])))
