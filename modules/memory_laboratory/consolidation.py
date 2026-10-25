"""Resource-bounded evidence proposals; never promotes or deletes evidence."""
import json
import re
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
            proposed, hashes, sources, subjects, concepts = [], {}, {}, {}, {}
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
                    proposal("stable_knowledge_requires_verification", [previous, row["id"]])
                hashes[p["content_hash"]] = row["id"]
                source_key = (row["source"], p["provenance"]["version"])
                for (source, version), old_id in list(sources.items())[:self.max_records]:
                    if source == row["source"] and version != source_key[1]:
                        proposal("source_correction_requires_review", [old_id, row["id"]])
                        break
                sources[source_key] = row["id"]
                # These are deliberately review candidates, not an assertion
                # that natural-language contradictions have been resolved.
                fact = re.match(r"^(.{2,100}?)\s+(?:is|equals)\s+(.{1,100}?)[.!]?\s*$", p["content"], re.I)
                if fact:
                    subject, value = (v.strip().lower() for v in fact.groups())
                    old = subjects.get(subject)
                    if old and old[1] != value:
                        proposal("possible_contradiction_requires_review", [old[0], row["id"]])
                    subjects[subject] = (row["id"], value)
                terms = set(re.findall(r"\b[a-zA-Z][a-zA-Z0-9_-]{4,}\b", p["content"].lower()))
                for old_id, old_terms in list(concepts.items())[-10:]:
                    if len(terms & old_terms) >= 2:
                        proposal("concept_relationship_candidate", [old_id, row["id"]])
                        break
                concepts[row["id"]] = terms
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
