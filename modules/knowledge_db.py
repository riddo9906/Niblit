#!/usr/bin/env python3
# knowledge_db.py — Unified Knowledge Database for Niblit
# Combines MemoryManager features with KnowledgeDB persistence

import os
import json
import time
import threading
import logging
import re
from datetime import datetime

# Setup logging
log = logging.getLogger("KnowledgeDB")
logging.basicConfig(
    level=logging.DEBUG,
    format="[%(asctime)s][%(name)s][%(levelname)s] %(message)s"
)


class KnowledgeDB:

    _instance = None  # singleton

    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            cls._instance = super(KnowledgeDB, cls).__new__(cls)
        return cls._instance

    def __init__(self, path=None, autosave_interval=60, dump_interval=300):
        if getattr(self, "_initialized", False):
            return
        self._initialized = True

        self.path = path or os.path.join(os.getcwd(), "niblit_memory.json")
        self.autosave_interval = autosave_interval
        self.dump_interval = dump_interval

        self.lock = threading.Lock()
        self.data = {
            "facts": [],
            "interactions": [],
            "learning_log": [],
            "learning_queue": [],
            "preferences": {"mood": "neutral", "verbosity": "medium"},
            "events": [],
            "meta": {},
        }

        self._load()

        threading.Thread(target=self._autosave_loop, daemon=True).start()
        threading.Thread(target=self._dump_loop, daemon=True).start()

        log.info("KnowledgeDB initialized with autosave and dump threads")

    # ============================================================
    # INTERNAL LOAD / SAVE
    # ============================================================

    def _load(self):
        try:
            if os.path.exists(self.path):
                with open(self.path, "r", encoding="utf-8") as f:
                    loaded = json.load(f)
                self.data.update(loaded)
                log.info(f"KnowledgeDB loaded from {self.path}")
        except Exception as e:
            log.error(f"Failed to load KnowledgeDB: {e}")
            self._save()

    def _save(self):
        with self.lock:
            try:
                with open(self.path, "w", encoding="utf-8") as f:
                    json.dump(self.data, f, indent=4, ensure_ascii=False)
                log.debug("KnowledgeDB saved")
            except Exception as e:
                log.error(f"KnowledgeDB save failed: {e}")

    # ============================================================
    # THREAD LOOPS
    # ============================================================

    def _autosave_loop(self):
        while True:
            self._save()
            time.sleep(self.autosave_interval)

    def _dump_loop(self):
        while True:
            self.dump_state()
            time.sleep(self.dump_interval)

    # ============================================================
    # GENERIC GET / SET
    # ============================================================

    def set(self, key, value):
        with self.lock:
            self.data[key] = value
        self._save()
        log.debug(f"[KnowledgeDB Set] {key}")

    def get(self, key, default=None):
        with self.lock:
            return self.data.get(key, default)

    # ============================================================
    # EVENTS
    # ============================================================

    def log_event(self, text):
        with self.lock:
            self.data.setdefault("events", [])
            self.data["events"].append({
                "time": datetime.utcnow().isoformat(),
                "event": text
            })
        log.info(f"[Event] {text}")
        self._save()

    def get_events(self):
        with self.lock:
            return list(self.data.get("events", []))

    # ============================================================
    # INTERACTIONS / LEARNING
    # ============================================================

    def add_interaction(self, user_input=None, response=None, source="unknown", data=None):
        interaction = self._canonicalize(
            raw_input=user_input,
            response=response,
            source=source,
            data=data
        )

        # Store in learning_log (original behavior)
        self.store_learning(interaction)

        # ALSO store in interactions (new behavior)
        with self.lock:
            self.data.setdefault("interactions", [])
            self.data["interactions"].append(interaction)

        self.log_event(f"Interaction stored from {source}")
        log.info(f"[Interaction] {interaction}")

        self._save()

    def store_learning(self, entry):
        with self.lock:
            self.data.setdefault("learning_log", [])
            self.data["learning_log"].append(entry)
        log.info(f"[Learning Stored] {entry}")
        self._save()

    def get_learning_log(self):
        with self.lock:
            return list(self.data.get("learning_log", []))

    # ============================================================
    # FACTS / QUEUE
    # ============================================================

    def add_fact(self, key, value, tags=None):
        with self.lock:
            self.data.setdefault("facts", [])
            self.data["facts"].append({
                "key": key,
                "value": value,
                "tags": tags or [],
                "ts": int(time.time())
            })
        self._save()

    def list_facts(self, limit: int = 100):
        """Return the most recent facts, up to `limit`."""
        with self.lock:
            facts = self.data.get("facts", [])
            facts_sorted = sorted(
                facts,
                key=lambda x: x.get("ts", 0),
                reverse=True
            )
            return facts_sorted[:limit]

    def queue_learning(self, topic):
        with self.lock:
            self.data.setdefault("learning_queue", [])
            self.data["learning_queue"].append({
                "topic": topic,
                "status": "queued",
                "ts": int(time.time())
            })
        self._save()

    def get_learning_queue(self):
        with self.lock:
            return list(self.data.get("learning_queue", []))

    def mark_learning_done(self, topic):
        """Mark all queued items with the given topic as processed."""
        with self.lock:
            for item in self.data.get("learning_queue", []):
                if isinstance(item, dict) and item.get("topic") == topic:
                    item["status"] = "processed"
        self._save()

    # ============================================================
    # PERSONALITY / PREFERENCES
    # ============================================================

    def store_preferences(self, prefs):
        with self.lock:
            self.data["preferences"] = prefs
        self._save()
        log.info(f"[Preferences Stored] {prefs}")

    def get_preferences(self):
        with self.lock:
            return dict(self.data.get("preferences", {}))

    def get_personality(self):
        return self.get_preferences()

    # ============================================================
    # CANONICALIZATION
    # ============================================================

    def _canonicalize(self, raw_input=None, response=None, source="unknown", data=None):
        now = datetime.utcnow().isoformat()

        record = {
            "time": now,
            "speaker": "unknown",
            "input": None,
            "response": response,
            "source": source,
            "data": data,
        }

        if isinstance(raw_input, dict):
            record["data"] = raw_input
            return record

        if isinstance(raw_input, str):
            txt = raw_input.strip()
            m = re.match(r"^(user|assistant|agent|system)\s*:\s*(.+)$", txt, re.I)
            if m:
                record["speaker"] = m.group(1).lower()
                record["input"] = m.group(2)
            else:
                record["speaker"] = "user"
                record["input"] = txt

        return record

    # ============================================================
    # RECALL / SEARCH
    # ============================================================

    def recall(self, query: str, limit: int = 3, include_preferences=True):
        if query is None:
            query = ""

        results = []

        if not query.strip():
            recent = list(reversed(self.get_learning_log()))
            return recent[:limit]

        query_words = set(query.lower().split())

        for entry in reversed(self.get_learning_log()):
            text = json.dumps(entry).lower()
            if query_words & set(text.split()):
                results.append(entry)
                if len(results) >= limit:
                    break

        if include_preferences:
            prefs = self.get_preferences()
            for k, v in prefs.items():
                if any(w in str(v).lower() for w in query_words):
                    results.append({k: v})
                    if len(results) >= limit:
                        break

        return results[:limit]

    # ============================================================
    # HFBrain COMPATIBILITY
    # ============================================================

    def add_hf_context(self, *args, **kwargs):
        try:
            if len(args) == 2 and isinstance(args[0], str):
                role, content = args
                self.add_interaction(
                    user_input=f"{role}: {content}",
                    source="hf_brain"
                )
                return

            if len(args) >= 1 and isinstance(args[0], dict):
                context_dict = args[0]
                source = kwargs.get("source", "unknown")
                self.add_interaction(
                    user_input=context_dict,
                    source=source
                )
        except Exception as e:
            log.error(f"HF context storage failed: {e}")

    # ============================================================
    # STATE DUMP / ALL DATA
    # ============================================================

    def dump_state(self):
        with self.lock:
            log.info(
                "[KnowledgeDB Dump] Full current state:\n" +
                json.dumps(self.data, indent=4, ensure_ascii=False)
            )

    def get_all(self):
        with self.lock:
            return dict(self.data)

    # ============================================================
    # SHUTDOWN
    # ============================================================

    def shutdown(self):
        log.info("KnowledgeDB shutting down — saving final state")
        self._save()


# ============================================================
# GLOBAL SINGLETON
# ============================================================

GLOBAL_KNOWLEDGE = KnowledgeDB()


# ============================================================
# TEST
# ============================================================

if __name__ == "__main__":
    db = GLOBAL_KNOWLEDGE
    db.log_event("KnowledgeDB initialized")
    db.store_learning({"input": "Test learning log entry"})
    db.add_interaction("user: hi", "hello", source="self-test")
    db.add_hf_context({"topic": "testing HF context"}, source="self-test")
    db.add_hf_context("assistant", "HF-style message")
    db.dump_state()
    print("KnowledgeDB standalone test completed")
