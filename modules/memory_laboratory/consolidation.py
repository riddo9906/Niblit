"""Resource-bounded evidence proposals; never promotes or deletes evidence."""
import json
import threading
import time
from datetime import datetime, timezone

from .gateway import digest, now


class Consolidator:
    def __init__(self, gateway, *, namespace, principal, max_records=100, seconds=1.0):
        self.gateway, self.namespace, self.principal = gateway, namespace, principal
        self.max_records = max(1, min(int(max_records), 100))
        self.seconds = max(.01, min(float(seconds), 2))
        self.stop_event = threading.Event()
        self.thread = None

    def tick(self):
        g = self.gateway
        g.require("consolidate", self.namespace, self.principal)
        deadline = time.monotonic() + self.seconds
        with g.db() as db:
            db.execute("CREATE TABLE IF NOT EXISTS proposals(id TEXT PRIMARY KEY, payload TEXT NOT NULL)")
            rows = db.execute("SELECT * FROM records WHERE namespace=? AND principal=? ORDER BY rowid DESC LIMIT ?",
                              (self.namespace, self.principal, self.max_records)).fetchall()
            proposed, hashes, sources = [], {}, {}
            def proposal(kind, ids):
                key = digest(json.dumps([kind, sorted(ids)]))
                payload = {"id": key, "kind": kind, "evidence_ids": ids,
                           "verification": "unverified", "requires_operator_verification": True,
                           "created_at": now()}
                db.execute("INSERT OR IGNORE INTO proposals VALUES(?,?)", (key, json.dumps(payload)))
                proposed.append(payload)
            for row in rows:
                if time.monotonic() >= deadline:
                    break
                p = json.loads(row["payload"])
                if p["lifecycle"] == "deleted":
                    continue
                previous = hashes.get(p["content_hash"])
                if previous:
                    proposal("repeated_information_candidate", [previous, row["id"]])
                hashes[p["content_hash"]] = row["id"]
                source_key = (row["source"], p["provenance"]["version"])
                for (source, version), old_id in list(sources.items())[:self.max_records]:
                    if source == row["source"] and version != source_key[1]:
                        proposal("source_correction_requires_review", [old_id, row["id"]])
                        break
                sources[source_key] = row["id"]
                age = (datetime.now(timezone.utc) - datetime.fromisoformat(p["updated_at"])).days
                if age > 90 and p["importance"] < .5:
                    proposal("stale_low_value_review", [row["id"]])
                if p["category"] == "procedural":
                    proposal("reusable_procedure_candidate", [row["id"]])
            g.audit(db, "consolidation.proposed", None, count=len(proposed), scanned=len(rows))
        return {"proposals": proposed, "scanned": len(rows), "original_evidence_unchanged": True}

    def start(self, interval=60):
        if self.thread and self.thread.is_alive():
            return
        interval = max(30, float(interval))
        def work():
            while not self.stop_event.wait(interval):
                try:
                    self.tick()
                except Exception:
                    # No retries in a tight loop; no evidence mutation on failure.
                    continue
        self.stop_event.clear()
        self.thread = threading.Thread(target=work, daemon=True, name="MemoryConsolidation")
        self.thread.start()

    def stop(self):
        self.stop_event.set()
        if self.thread:
            self.thread.join(timeout=3)
