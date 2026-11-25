"""Durable single-owner lease contract for a future demo-position handover.

Not wired to a broker, API, trading worker or frozen release. A lease record
is NOT order permission. The current r12 process does not participate in this
registry, so this module cannot grant cross-runtime execution by itself.
"""
from __future__ import annotations

import hashlib
import json
import math
import sqlite3
from pathlib import Path


def _fingerprint(evidence: dict) -> str:
    return hashlib.sha256(json.dumps(evidence, sort_keys=True, allow_nan=False,
                                     separators=(",", ":")).encode("utf-8")).hexdigest()


def review_handover(snapshot: dict, *, prior_owner_released: bool) -> dict:
    """Produce a deterministic review only; never authorize execution."""
    reasons = []
    if not isinstance(snapshot, dict) or snapshot.get("state") != "observed":
        reasons.append("Broker observation unavailable")
        snapshot = {}
    if snapshot.get("account_mode") != "demo" or snapshot.get("account_binding_verified") is not True:
        reasons.append("Verified demo account required")
    if snapshot.get("observation_handover_eligible") is not True:
        reasons.append("Broker/Core receipt evidence incomplete")
    if snapshot.get("broker_pending_order_count") != 0:
        reasons.append("Native pending-order state unverified")
    positions = snapshot.get("position_claims")
    if not isinstance(positions, list) or len(positions) != 1:
        reasons.append("Exactly one reviewed native position required")
        positions = []
    for p in positions:
        if (p.get("matching_core_order_count") != 1 or
                p.get("native_open_deal_receipt_found") is not True or
                p.get("account_binding_verified") is not True or
                p.get("protected") is not True):
            reasons.append("Original native Core provenance or protections not verified")
        if not (isinstance(p.get("ticket"), str) and p["ticket"].isdigit()
                and isinstance(p.get("position_identifier"), str)
                and p["position_identifier"].isdigit()
                and isinstance(p.get("symbol"), str) and p["symbol"]):
            reasons.append("Position identifier or symbol invalid")
    if prior_owner_released is not True:
        reasons.append("Original runtime has not issued an explicit ownership release")
    valid = not reasons
    evidence = {
        "scope": "DEMO", "ticket": positions[0].get("ticket") if positions else None,
        "identifier": positions[0].get("position_identifier") if positions else None,
        "symbol": positions[0].get("symbol") if positions else None,
        "account_mode": snapshot.get("account_mode"),
        "account_verified": snapshot.get("account_binding_verified") is True,
        "provenance_verified": bool(positions and positions[0].get("native_open_deal_receipt_found") is True),
    }
    return {
        "proposal_version": "mt5-demo-adoption-review/1",
        "evidence_fingerprint": _fingerprint(evidence),
        "review_passed": valid,
        "blockers": reasons,
        "execution_authorized": False,
        "trading_ownership_transferred": False,
        "requires_runtime_revalidation": True,
    }


class StagingLeaseRegistry:
    """Atomic SQLite owner mutex for simulations, not a broker authority.

    The registry must not be used to infer an r12 release: r12 does not use it.
    The lease is an advisory single-writer proof only, and its tokens cannot be
    consumed by any existing order controller.
    """

    def __init__(self, db_path: str | Path):
        self.path = Path(db_path)
        if self.path.parent != self.path.parent.resolve():
            raise ValueError("Uncanonicalized lease path")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._db() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS advisory_leases (
                        position_key TEXT PRIMARY KEY,
                        holder TEXT NOT NULL, fingerprint TEXT NOT NULL,
                        expires_at REAL NOT NULL)""")

    def _db(self):
        db = sqlite3.connect(str(self.path), timeout=5, isolation_level=None)
        db.execute("PRAGMA busy_timeout=5000")
        return db

    def acquire(self, *, position_key: str, holder: str, fingerprint: str,
                now: float, ttl: float) -> bool:
        if not all(isinstance(x, str) and 1 <= len(x) <= 128
                   for x in (position_key, holder, fingerprint)):
            raise ValueError("Explicit bounded lease identity required")
        if (not isinstance(now, (int, float)) or isinstance(now, bool)
                or not math.isfinite(now)
                or not isinstance(ttl, (int, float)) or isinstance(ttl, bool)
                or not math.isfinite(ttl) or not 1 <= ttl <= 300):
            raise ValueError("Finite bounded lease time required")
        with self._db() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT holder,fingerprint,expires_at FROM advisory_leases WHERE position_key=?",
                             (position_key,)).fetchone()
            # An expired lease is not automatically reclaimed. The previous
            # owner may still be controlling broker orders or recovering.
            if row is not None:
                db.execute("ROLLBACK")
                return False
            db.execute("INSERT INTO advisory_leases VALUES(?,?,?,?)",
                       (position_key, holder, fingerprint, now + ttl))
            db.execute("COMMIT")
            return True

    def release(self, *, position_key: str, holder: str, fingerprint: str) -> bool:
        with self._db() as db:
            db.execute("BEGIN IMMEDIATE")
            changed = db.execute(
                "DELETE FROM advisory_leases WHERE position_key=? AND holder=? AND fingerprint=?",
                (position_key, holder, fingerprint)
            ).rowcount
            db.execute("COMMIT")
            return changed == 1

    def status(self, position_key: str):
        with self._db() as db:
            row = db.execute(
                "SELECT holder,fingerprint,expires_at FROM advisory_leases WHERE position_key=?",
                (position_key,)
            ).fetchone()
        if row is None:
            return {"state": "unclaimed", "execution_authorized": False}
        return {"state": "held", "holder": row[0], "fingerprint": row[1],
                "expires_at": row[2], "execution_authorized": False}
