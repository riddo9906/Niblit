#!/usr/bin/env python3
# niblit_memory_upgraded.py — Unified MemoryManager with global singleton & enhanced features

import json
import os
import threading
import time
import logging
import re
from datetime import datetime

# Setup logging
log = logging.getLogger("NiblitMemory")
logging.basicConfig(level=logging.DEBUG,
                    format="[%(asctime)s][%(name)s][%(levelname)s] %(message)s")


class MemoryManager:

    _instance = None  # for singleton access

    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            cls._instance = super(MemoryManager, cls).__new__(cls)
        return cls._instance

    def __init__(self, filename=None, autosave_interval=60, dump_interval=300):
        if getattr(self, "_initialized", False):
            return  # prevent re-init on singleton
        self._initialized = True

        self.filename = filename or os.path.join(os.getcwd(), "niblit_memory.json")
        self.autosave_interval = autosave_interval
        self.dump_interval = dump_interval

        self.lock = threading.Lock()
        self.state = {
            "events": [],
            "learning_log": [],
            "preferences": {},
        }

        self._load()

        # Start background threads
        threading.Thread(target=self._autosave_loop, daemon=True).start()
        threading.Thread(target=self._dump_loop, daemon=True).start()

        log.info("MemoryManager initialized with autosave and periodic dump threads")

    # ============================================================
    # 🔥 INTERNAL INTEGRITY CHECK (NEW SAFETY)
    # ============================================================

    def _ensure_integrity(self):
        """
        Ensures required keys always exist.
        Prevents runtime crashes in other modules.
        """
        with self.lock:
            self.state.setdefault("events", [])
            self.state.setdefault("learning_log", [])
            self.state.setdefault("preferences", {})

    # ============================================================
    # 🔥 CANONICAL INGESTION LAYER (UNCHANGED LOGIC)
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
    # FILE LOAD / SAVE (UNCHANGED + INTEGRITY CHECK)
    # ============================================================

    def _load(self):
        if os.path.exists(self.filename):
            try:
                with open(self.filename, "r", encoding="utf-8") as f:
                    data = json.load(f)
                self.state.update(data)
                log.info(f"Memory loaded from {self.filename}")
            except Exception as e:
                log.error(f"Failed to load memory: {e}")
        else:
            log.info("Memory file not found, starting fresh")

        # 🔥 Always ensure required structure exists
        self._ensure_integrity()

    def save(self):
        with self.lock:
            try:
                with open(self.filename, "w", encoding="utf-8") as f:
                    json.dump(self.state, f, indent=4, ensure_ascii=False)
                log.debug("Memory saved")
            except Exception as e:
                log.error(f"Memory save failed: {e}")

    # ============================================================
    # THREAD LOOPS (UNCHANGED)
    # ============================================================

    def _autosave_loop(self):
        while True:
            self.save()
            time.sleep(self.autosave_interval)

    def _dump_loop(self):
        while True:
            self.dump_state()
            time.sleep(self.dump_interval)

    # ============================================================
    # GENERIC SET / GET (UNCHANGED)
    # ============================================================

    def set(self, key, value):
        with self.lock:
            self.state[key] = value
        log.debug(f"[Memory Set] {key}: {value}")
        self.save()

    def get(self, key, default=None):
        with self.lock:
            return self.state.get(key, default)

    # ============================================================
    # EVENT LOGGING (UNCHANGED)
    # ============================================================

    def log_event(self, text):
        with self.lock:
            self.state.setdefault("events", [])
            self.state["events"].append({
                "time": datetime.utcnow().isoformat(),
                "event": text
            })
        log.info(f"[Event] {text}")
        self.save()

    def get_events(self):
        with self.lock:
            return list(self.state.get("events", []))

    # ============================================================
    # LEARNING DATA (UNCHANGED + SAFE GUARD)
    # ============================================================

    def store_learning(self, data):
        with self.lock:
            self.state.setdefault("learning_log", [])
            self.state["learning_log"].append(data)
        log.info(f"[Learning Stored] {data}")
        self.save()

    def get_learning_log(self):
        """
        Canonical accessor.
        Guaranteed to exist for tasks compatibility.
        """
        with self.lock:
            return list(self.state.get("learning_log", []))

    # 🔥 Compatibility alias for older modules
    def get_logs(self):
        return self.get_learning_log()

    # ============================================================
    # 🔥 ENHANCED RECALL (SAFE EMPTY QUERY SUPPORT)
    # ============================================================

    def recall(self, query: str, limit: int = 3, include_preferences=True):
        if query is None:
            query = ""

        results = []

        # 🔥 If empty query → return most recent entries
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

        log.debug(f"[Recall] query='{query}' -> {results}")
        return results[:limit]

    # ============================================================
    # PREFERENCES (UNCHANGED)
    # ============================================================

    def store_preferences(self, pref_dict):
        with self.lock:
            self.state["preferences"] = pref_dict
        log.info(f"[Preferences Stored] {pref_dict}")
        self.save()

    def get_preferences(self):
        with self.lock:
            return dict(self.state.get("preferences", {}))

    # ============================================================
    # FIXED INTERACTION LOGGING (UNCHANGED)
    # ============================================================

    def add_interaction(self, user_input=None, response=None, source="unknown", data=None):
        interaction = self._canonicalize(
            raw_input=user_input,
            response=response,
            source=source,
            data=data
        )
        self.store_learning(interaction)
        self.log_event(f"Interaction stored from {source}")
        log.info(f"[Interaction] {interaction}")

    # ============================================================
    # HFBrain COMPATIBILITY (UNCHANGED)
    # ============================================================

    def add_hf_context(self, *args, **kwargs):
        try:
            if len(args) == 2 and isinstance(args[0], str):
                role, content = args
                self.add_interaction(user_input=f"{role}: {content}", source="hf_brain")
                return

            if len(args) >= 1 and isinstance(args[0], dict):
                context_dict = args[0]
                source = kwargs.get("source", "unknown")
                self.add_interaction(user_input=context_dict, source=source)
                return
        except Exception as e:
            log.error(f"HF context storage failed: {e}")

    # ============================================================
    # STATE DUMP (UNCHANGED)
    # ============================================================

    def dump_state(self):
        with self.lock:
            log.info("[Memory Dump] Full current state:\n" +
                     json.dumps(self.state, indent=4, ensure_ascii=False))

    def get_all(self):
        with self.lock:
            return {
                "events": list(self.state.get("events", [])),
                "learning_log": list(self.state.get("learning_log", [])),
                "preferences": dict(self.state.get("preferences", {})),
            }

    # ============================================================
    # SHUTDOWN / FLUSH (UNCHANGED)
    # ============================================================

    def shutdown(self):
        log.info("MemoryManager shutting down — saving final state")
        self.save()


# ============================================================
# GLOBAL SINGLETON INSTANCE
# ============================================================

GLOBAL_MEMORY = MemoryManager()

# Backward-compatibility alias used by niblit_hf, niblit_manager, lifecycle_engine
NiblitMemory = MemoryManager


# ============================================================
# TEST
# ============================================================

if __name__ == "__main__":
    mem = GLOBAL_MEMORY

    mem.log_event("Memory system initialized")
    mem.store_learning({"input": "Test learning log entry"})

    mem.add_interaction("user: hi", "hello", source="self-test")
    mem.add_hf_context({"topic": "testing HF context"}, source="self-test")
    mem.add_hf_context("assistant", "HF-style message")

    log.info("MemoryManager standalone test completed — all data logged")
    mem.dump_state()
