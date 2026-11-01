"""Point-in-time market journal. Observations and realized outcomes stay distinct.

Numeric state vectors have their own Qdrant collection/model identity; they are
never mixed with language embeddings. Similarity is not a trading edge or order.
"""
import json
import math
from datetime import datetime, timezone
from uuid import NAMESPACE_URL, uuid5

from .gateway import digest, now
from .setup import validate_vector


def utc(value):
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("market timestamps require timezone")
    return parsed.astimezone(timezone.utc).isoformat()


class MarketJournal:
    def __init__(self, gateway):
        self.gateway = gateway
        with gateway.db() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS market_observations(
                id TEXT PRIMARY KEY, identity TEXT NOT NULL, observed_at TEXT NOT NULL,
                available_at TEXT NOT NULL, payload TEXT NOT NULL, vector TEXT NOT NULL,
                projected INTEGER NOT NULL DEFAULT 0, outcome TEXT, outcome_at TEXT)""")

    def observe(self, vector, *, symbol, venue, interval, mode, observed_at,
                available_at=None, features=None, feature_version="legacy-zscore7-v1"):
        self.gateway.require("ingest", "trading", "desktop_operator")
        if mode not in {"live", "paper", "replay", "observe"}:
            raise ValueError("explicit market mode required")
        if not all(isinstance(v, str) and 0 < len(v) <= 100 for v in (symbol, venue, interval, feature_version)):
            raise ValueError("invalid market identity")
        vector = validate_vector(vector)
        observed_at, available_at = utc(observed_at), utc(available_at or now())
        if observed_at > available_at:
            raise ValueError("observation cannot predate data availability")
        identity = json.dumps([symbol.upper(), venue, interval, mode, feature_version, len(vector)])
        key = str(uuid5(NAMESPACE_URL, identity + observed_at))
        payload = dict(id=key, symbol=symbol.upper(), venue=venue, interval=interval,
                       mode=mode, feature_version=feature_version, observed_at=observed_at,
                       available_at=available_at, features=features or {}, verification="observation_only")
        encoded = json.dumps(payload, sort_keys=True, allow_nan=False)
        with self.gateway.db() as db:
            existing = db.execute("SELECT payload,vector FROM market_observations WHERE id=?", (key,)).fetchone()
            if existing and (existing["payload"] != encoded or json.loads(existing["vector"]) != vector):
                raise ValueError("immutable observation conflict; use a new observation identity")
            db.execute("INSERT OR IGNORE INTO market_observations(id,identity,observed_at,available_at,payload,vector) VALUES(?,?,?,?,?,?)",
                       (key, identity, observed_at, available_at, encoded, json.dumps(vector)))
        self.project(key)
        return key

    def collection(self, identity):
        return self.gateway.config.prefix + "_market_" + digest(identity)[:16]

    def project(self, key):
        with self.gateway.db() as db:
            row = db.execute("SELECT * FROM market_observations WHERE id=?", (key,)).fetchone()
        collection = self.collection(row["identity"])
        backend = self.gateway.backend
        response = backend.client.get(f"/collections/{collection}")
        if response.status_code == 404:
            backend.request("PUT", f"/collections/{collection}", json={"vectors": {"size": len(json.loads(row["vector"])), "distance": "Cosine"}})
            for field in ("observed_at", "available_at"):
                backend.request("PUT", f"/collections/{collection}/index?wait=true", json={"field_name": field, "field_schema": "datetime"})
        else:
            response.raise_for_status()
        backend.request("PUT", f"/collections/{collection}/points?wait=true", json={"points": [{
            "id": key, "vector": json.loads(row["vector"]), "payload": json.loads(row["payload"])}]})
        check = backend.request("POST", f"/collections/{collection}/points", json={"ids": [key], "with_payload": True})
        if len(check) != 1 or check[0]["payload"] != json.loads(row["payload"]):
            raise ValueError("market projection verification failed")
        with self.gateway.db() as db:
            db.execute("UPDATE market_observations SET projected=1 WHERE id=?", (key,))

    def repair_pending(self, limit=8):
        with self.gateway.db() as db:
            rows = db.execute("SELECT id FROM market_observations WHERE projected=0 LIMIT ?", (limit,)).fetchall()
        for row in rows:
            self.project(row["id"])
        return len(rows)

    def record_outcome(self, key, *, realized_return, available_at, evidence):
        self.gateway.require("ingest", "trading", "desktop_operator")
        if not evidence.strip() or not math.isfinite(realized_return):
            raise ValueError("actual outcome evidence required")
        stamp = utc(available_at)
        with self.gateway.db() as db:
            row = db.execute("SELECT * FROM market_observations WHERE id=?", (key,)).fetchone()
            if not row or stamp <= row["available_at"] or stamp > now():
                raise ValueError("outcome must follow observation and already be available")
            outcome = json.dumps({"realized_return": realized_return, "evidence": evidence}, sort_keys=True)
            if row["outcome"] and (row["outcome"] != outcome or row["outcome_at"] != stamp):
                raise ValueError("immutable outcome conflict")
            db.execute("UPDATE market_observations SET outcome=?,outcome_at=? WHERE id=?", (outcome, stamp, key))

    def similar(self, vector, *, symbol, venue, interval, mode, as_of,
                feature_version="legacy-zscore7-v1", limit=10, max_age_seconds=86400):
        self.gateway.require("read", "trading", "desktop_operator")
        vector, cutoff = validate_vector(vector), utc(as_of)
        if not 1 <= limit <= 50 or not 0 < max_age_seconds <= 31536000:
            raise ValueError("invalid market retrieval bounds")
        identity = json.dumps([symbol.upper(), venue, interval, mode, feature_version, len(vector)])
        from datetime import timedelta
        oldest = (datetime.fromisoformat(cutoff)-timedelta(seconds=max_age_seconds)).isoformat()
        selected = None
        try:
            hits = self.gateway.backend.request("POST", f"/collections/{self.collection(identity)}/points/query", json={
                "query": vector, "limit": min(limit*4, 200), "with_payload": False,
                "filter": {"must": [{"key": "observed_at", "range": {"gte": oldest, "lt": cutoff}},
                                      {"key": "available_at", "range": {"lte": cutoff}}]}})["points"]
            selected = {str(h["id"]) for h in hits}
        except Exception:
            pass  # durable journal remains usable; each result names fallback
        with self.gateway.db() as db:
            rows = db.execute("SELECT * FROM market_observations WHERE identity=? AND observed_at<? AND available_at<=? AND observed_at>=? ORDER BY observed_at DESC LIMIT 10000", (identity, cutoff, cutoff, oldest)).fetchall()
        # Authoritative local post-filter also protects against stale indexes.
        result = []
        for row in rows:
            if selected is not None and row["projected"] and row["id"] not in selected:
                continue
            age = (datetime.fromisoformat(cutoff)-datetime.fromisoformat(row["observed_at"])).total_seconds()
            if age > max_age_seconds:
                continue
            score = sum(a*b for a,b in zip(vector, json.loads(row["vector"])))
            item = {**json.loads(row["payload"]), "score": score, "outcome": None,
                    "retrieval_backend": "qdrant" if selected is not None and row["projected"] else "local_numeric_degraded"}
            if row["outcome_at"] and row["outcome_at"] <= cutoff:
                item["outcome"] = json.loads(row["outcome"])
            result.append(item)
        return sorted(result, key=lambda p:p["score"], reverse=True)[:limit]
