"""Observation-only, broker-evidence-backed position cognition.

No broker connection, order submission, prediction or execution authority.
All state is rebuilt from immutable idempotent events in a caller-owned SQLite DB.
"""
from __future__ import annotations

import hashlib
import json
import math
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping


def _canonical(obj):
    return json.dumps(obj, allow_nan=False, sort_keys=True, separators=(",", ":"))


def _num(value, name, *, positive=False, zero=False):
    if type(value) not in (float, int) or not math.isfinite(value):
        raise ValueError(f"Invalid {name}")
    value = float(value)
    if positive and value <= 0 or zero and value < 0:
        raise ValueError(f"Invalid {name}")
    return value


@dataclass(frozen=True)
class PositionIdentity:
    adapter: str
    account: str
    broker_position_id: str
    core_order_id: str

    def __post_init__(self):
        for value in (self.adapter, self.account, self.broker_position_id, self.core_order_id):
            if not isinstance(value, str) or not value.strip() or len(value) > 180:
                raise ValueError("Non-empty scoped position identity required")

    @property
    def key(self):
        return hashlib.sha256(_canonical(vars(self)).encode()).hexdigest()


class PositionCognitionLedger:
    """SQLite immutable event store; caller controls DB path and access."""

    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._db() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS position_cognition_events_v1(
                position_key TEXT NOT NULL, event_id TEXT NOT NULL,
                observed_at REAL NOT NULL, kind TEXT NOT NULL,
                payload TEXT NOT NULL, PRIMARY KEY(position_key,event_id))""")
            db.execute("""CREATE INDEX IF NOT EXISTS cognition_by_time_v1
                ON position_cognition_events_v1(position_key,observed_at,event_id)""")

    def _db(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.execute("PRAGMA busy_timeout=10000")
        return db

    def record(self, identity: PositionIdentity, kind: str, observed_at: float,
               payload: Mapping, *, event_id: str | None = None):
        if kind not in {"entry", "mark", "deal", "protection", "thesis"}:
            raise ValueError("Unsupported position evidence kind")
        timestamp = _num(observed_at, "broker observation timestamp", positive=True)
        if not isinstance(payload, Mapping):
            raise ValueError("Payload must be structured evidence")
        payload = dict(payload)
        self._validate(kind, payload)
        encoded = _canonical(payload)
        fingerprint = hashlib.sha256(_canonical({
            "scope": identity.key, "kind": kind, "at": timestamp, "payload": payload
        }).encode()).hexdigest()
        ident = event_id or fingerprint
        if not isinstance(ident, str) or len(ident) > 180 or not ident:
            raise ValueError("Invalid provider evidence ID")
        with self._db() as db:
            previous = db.execute("""SELECT kind,observed_at,payload
                FROM position_cognition_events_v1
                WHERE position_key=? AND event_id=?""", (identity.key, ident)).fetchone()
            if previous is not None:
                if previous != (kind, timestamp, encoded):
                    raise ValueError("Conflicting reuse of broker evidence ID")
                return ident
            db.execute("""INSERT INTO position_cognition_events_v1 VALUES (?,?,?,?,?)""",
                       (identity.key, ident, timestamp, kind, encoded))
        return ident

    @staticmethod
    def _validate(kind, p):
        if kind == "entry":
            if p.get("side") not in ("buy", "sell"):
                raise ValueError("Entry direction unavailable")
            for field in ("entry", "quantity", "initial_stop"):
                _num(p.get(field), field, positive=True)
            direction = 1 if p["side"] == "buy" else -1
            if direction * (p["entry"] - p["initial_stop"]) <= 0:
                raise ValueError("Initial stop invalid for entry side")
            if not isinstance(p.get("strategy"), str) or not p["strategy"]:
                raise ValueError("Recorded entry strategy required")
            if not isinstance(p.get("decision_trace_id"), str) or not p["decision_trace_id"]:
                raise ValueError("Decision trace reference required")
            if p.get("take_profit") is not None:
                _num(p["take_profit"], "take profit", positive=True)
            if p.get("thesis_id") is not None and not isinstance(p["thesis_id"], str):
                raise ValueError("Thesis reference must be textual")
        elif kind == "mark":
            for field in ("bid", "ask", "quantity"):
                _num(p.get(field), field, positive=True if field != "quantity" else False,
                     zero=field == "quantity")
            if p["ask"] < p["bid"]:
                raise ValueError("Crossed quote")
            if p.get("floating_profit") is not None:
                _num(p["floating_profit"], "floating profit")
            if p.get("quote_timestamp") is not None:
                _num(p["quote_timestamp"], "quote timestamp", positive=True)
        elif kind == "deal":
            if p.get("action") not in ("open", "close"):
                raise ValueError("Deal action missing")
            _num(p.get("quantity"), "deal volume", positive=True)
            _num(p.get("price"), "deal price", positive=True)
            if p.get("quantity_after") is not None:
                _num(p["quantity_after"], "broker reconciled remaining quantity", zero=True)
            if p.get("realized_net") is not None:
                _num(p["realized_net"], "broker realized net")
            for field in ("commission", "swap", "fee"):
                if p.get(field) is not None:
                    _num(p[field], field)
        elif kind == "protection":
            if p.get("stop_loss") is not None:
                _num(p["stop_loss"], "modified SL", positive=True)
            if p.get("take_profit") is not None:
                _num(p["take_profit"], "modified TP", positive=True)
        elif kind == "thesis":
            if p.get("state") not in ("valid", "weakening", "invalidated", "uncertain"):
                raise ValueError("Unverified thesis state")
            if not isinstance(p.get("evidence_id"), str) or not p["evidence_id"]:
                raise ValueError("Thesis assessment needs evidence ID")

    def replay(self, identity: PositionIdentity):
        with self._db() as db:
            rows = db.execute("""SELECT event_id,observed_at,kind,payload
                FROM position_cognition_events_v1 WHERE position_key=?
                ORDER BY observed_at,event_id""", (identity.key,)).fetchall()
        result = {
            "schema": "niblit.position-cognition/1", "identity": vars(identity),
            "position_key": identity.key, "entry": None, "position_state": "unattributed",
            "observed_mfe_r": None, "observed_mae_r": None,
            "latest_executable_mark": None, "last_floating_profit": None,
            "broker_realized_net": None, "realized_net_complete": False,
            "deals": [], "protection": None, "thesis_state": "unknown",
            "latest_thesis_evidence_id": None, "event_count": len(rows),
            "execution_authorized": False, "learning_action": "record_only",
            "counterfactual_outcomes": None,
        }
        if not rows:
            return result
        entries = [(ts, p) for _, ts, kind, encoded in rows if kind == "entry"
                   for p in [json.loads(encoded)]]
        if not entries:
            return result
        entry_ts, entry = entries[0]
        if any(other != entry for _, other in entries[1:]):
            raise ValueError("Contradictory position entry evidence")
        result["entry"] = entry
        result["position_state"] = "open"
        result["protection"] = {
            "stop_loss": entry["initial_stop"], "take_profit": entry.get("take_profit")}
        risk = abs(entry["entry"] - entry["initial_stop"])
        direction = 1 if entry["side"] == "buy" else -1
        previous_deals = []
        quantity = float(entry["quantity"])
        quantity_coverage = "initial_broker_snapshot"
        mfe, mae = 0.0, 0.0
        last_mark = None
        thesis = None
        for event_id, ts, kind, encoded in rows:
            # Quotes before the entry cannot be used to manufacture excursion
            # history for a position that did not exist yet.
            if ts < entry_ts and kind != "entry":
                continue
            p = json.loads(encoded)
            if kind == "deal":
                previous_deals.append({"event_id": event_id, "observed_at": ts, **p})
                if p.get("quantity_after") is not None:
                    # Broker-confirmed position quantity wins over inferred fills.
                    # This supports partial opening fills without counting them
                    # twice against the original entry/position snapshot.
                    quantity = float(p["quantity_after"])
                    quantity_coverage = "broker_reconciled"
                elif p["action"] == "close":
                    quantity -= float(p["quantity"])
                    if quantity < -1e-7:
                        raise ValueError("Broker closes exceed recorded entry")
                else:
                    quantity_coverage = "ambiguous_open_fill_without_position_quantity"
            elif kind == "mark":
                if quantity <= 1e-7:
                    continue  # A closed trade has no further floating excursion.
                if p.get("quote_timestamp", ts) > ts:
                    raise ValueError("Mark quote is future dated")
                last_mark = {"timestamp": ts, "bid": p["bid"], "ask": p["ask"],
                             "quantity": p["quantity"]}
                executable = p["bid"] if direction == 1 else p["ask"]
                performance = direction * (executable - entry["entry"]) / risk
                mfe, mae = max(mfe, performance), min(mae, performance)
                result["latest_executable_mark"] = executable
                result["last_floating_profit"] = p.get("floating_profit")
                # Broker's current quantity can identify partial fills, but never
                # invent a broker close/deal or realized P&L.
                result["observed_quantity"] = p["quantity"]
            elif kind == "protection":
                for k in ("stop_loss", "take_profit"):
                    if k in p:
                        result["protection"][k] = p[k]
            elif kind == "thesis":
                thesis = (ts, p)
        result["deals"] = previous_deals
        result["quantity_evidence"] = quantity_coverage
        result["remaining_quantity_from_verified_closes"] = max(0.0, quantity)
        result["observed_mfe_r"] = mfe if last_mark is not None else None
        result["observed_mae_r"] = mae if last_mark is not None else None
        has_close = any(d["action"] == "close" for d in previous_deals)
        has_open_fill = any(d["action"] == "open" for d in previous_deals)
        result["position_state"] = (
            "closed" if quantity <= 1e-7 and has_close else
            "partially_closed" if quantity < entry["quantity"] and has_close else
            "partially_filled" if quantity < entry["quantity"] and has_open_fill else
            "open")
        close_deals = [d for d in previous_deals if d["action"] == "close"]
        if close_deals and all(d.get("realized_net") is not None for d in close_deals):
            result["broker_realized_net"] = sum(float(d["realized_net"]) for d in close_deals)
            result["realized_net_complete"] = result["position_state"] == "closed"
        if thesis:
            result["thesis_state"] = thesis[1]["state"]
            result["latest_thesis_evidence_id"] = thesis[1]["evidence_id"]
        return result
