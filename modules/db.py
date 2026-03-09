#!/usr/bin/env python3
import json
import time
import os
import threading
import logging

log = logging.getLogger("LocalDB")
logging.basicConfig(level=logging.INFO, format='[%(asctime)s][%(name)s][%(levelname)s] %(message)s')


class LocalDB:
    """
    JSON-backed semantic memory DB.
    Compatible with NiblitBrain and SelfIdeaImplementation.
    Supports:
    - Interactions
    - Facts/artifacts
    - Learning log
    - Preferences
    """

    def __init__(self, path="niblit.db"):
        self.path = path
        self.lock = threading.Lock()

        if not os.path.exists(self.path):
            self.data = {
                "interactions": [],
                "facts": [],
                "learning_log": [],
                "preferences": {"tone": "neutral", "interaction_style": "casual"}
            }
            self._save()
        else:
            try:
                self.data = self._read()
            except Exception:
                self.data = {
                    "interactions": [],
                    "facts": [],
                    "learning_log": [],
                    "preferences": {"tone": "neutral", "interaction_style": "casual"}
                }
                self._save()

    # -----------------------------
    # CORE IO
    # -----------------------------
    def _read(self):
        with open(self.path, "r") as f:
            return json.load(f)

    def _write(self, data):
        with open(self.path, "w") as f:
            json.dump(data, f, indent=2)

    def _save(self):
        with self.lock:
            self._write(self.data)

    # -----------------------------
    # INTERACTIONS
    # -----------------------------
    def add_entry(self, key, value):
        with self.lock:
            self.data.setdefault("interactions", [])
            self.data["interactions"].append({
                "ts": time.time(),
                "key": key,
                "value": value
            })
            self._save()

    def get_log(self):
        return self.data.get("interactions", [])

    # -----------------------------
    # FACTS / ARTIFACTS
    # -----------------------------
    def list_facts(self, limit=500):
        return self.data.get("facts", [])[:limit]

    def get_fact(self, key):
        for fact in self.data.get("facts", []):
            if fact.get("key") == key:
                return fact
        return None

    def add_fact(self, key, value, tags=None):
        tags = tags or []
        now = time.time()

        # 🔹 Ensure concept always exists for semantic artifacts
        if isinstance(value, dict) and "concept" not in value:
            value["concept"] = key

        with self.lock:
            existing = self.get_fact(key)

            if existing:
                # Ensure existing stored value also has concept
                if isinstance(existing.get("value"), dict) and "concept" not in existing["value"]:
                    existing["value"]["concept"] = key

                existing["value"] = value
                existing["last_updated"] = now
                existing["tags"] = list(set(existing.get("tags", []) + tags))
                existing["exposures"] = existing.get("exposures", 1) + 1
            else:
                self.data.setdefault("facts", [])
                self.data["facts"].append({
                    "key": key,
                    "value": value,
                    "tags": tags,
                    "created": now,
                    "last_updated": now,
                    "exposures": 1
                })

            self._save()

    # -----------------------------
    # LEARNING
    # -----------------------------
    def store_learning(self, entry):
        with self.lock:
            self.data.setdefault("learning_log", [])
            self.data["learning_log"].append(entry)
            self._save()
            log.info(f"[Learning Stored] {entry}")

    def get_learning_log(self):
        with self.lock:
            return list(self.data.get("learning_log", []))

    # -----------------------------
    # PREFERENCES
    # -----------------------------
    def get_preferences(self):
        with self.lock:
            return dict(self.data.get("preferences", {"tone": "neutral", "interaction_style": "casual"}))

    def store_preferences(self, prefs):
        with self.lock:
            self.data["preferences"] = prefs
            self._save()
            log.info(f"[Preferences Stored] {prefs}")

    # -----------------------------
    # RECALL / SEARCH
    # -----------------------------
    def recall(self, query="", limit=5):
        results = []
        query_lower = (query or "").lower()

        # Search in learning log
        for entry in reversed(self.get_learning_log()):
            text = json.dumps(entry).lower()
            if query_lower in text:
                results.append(entry)
            if len(results) >= limit:
                break

        # Fallback to interactions if no results
        if len(results) < limit:
            for item in reversed(self.get_log()):
                val = str(item.get("value", "")).lower()
                if query_lower in val:
                    results.append(item)
                if len(results) >= limit:
                    break

        return results[:limit]

    # -----------------------------
    # MAINTENANCE
    # -----------------------------
    def condense(self, keep_top=50):
        with self.lock:
            interactions = self.data.get("interactions", [])
            if len(interactions) > keep_top:
                self.data["interactions"] = interactions[-keep_top:]
                self._save()


if __name__ == "__main__":
    db = LocalDB()
    db.store_learning({"input": "Test learning entry"})
    db.add_entry("test_key", "Test interaction value")
    db.add_fact("idea:test", {"details": "Some details"}, tags=["idea"])
    db.recall("test")
    print("LocalDB standalone test completed")
