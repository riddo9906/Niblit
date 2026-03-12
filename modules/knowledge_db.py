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
        
        self.lock = threading.RLock()
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
        
        threading.Thread(target=self._autosave_loop, daemon=True, name="KnowledgeDB-AutoSave").start()
        threading.Thread(target=self._dump_loop, daemon=True, name="KnowledgeDB-Dump").start()
        
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
            self._save(blocking=False)
    
    def _save(self, blocking=True):
        """Save data to disk. Can be non-blocking to prevent freezes."""
        def _do_save():
            try:
                with self.lock:
                    with open(self.path, "w", encoding="utf-8") as f:
                        json.dump(self.data, f, indent=4, ensure_ascii=False)
                    log.debug("KnowledgeDB saved")
            except Exception as e:
                log.error(f"KnowledgeDB save failed: {e}")
        
        if blocking:
            _do_save()
        else:
            # Queue save in background thread to prevent blocking
            threading.Thread(target=_do_save, daemon=True, name="KnowledgeDB-SaveBG").start()
    
    # ============================================================
    # THREAD LOOPS
    # ============================================================
    
    def _autosave_loop(self):
        while True:
            try:
                self._save(blocking=False)
                time.sleep(self.autosave_interval)
            except Exception as e:
                log.debug(f"Autosave error: {e}")
                time.sleep(5)
    
    def _dump_loop(self):
        while True:
            try:
                self.dump_state()
                time.sleep(self.dump_interval)
            except Exception as e:
                log.debug(f"Dump error: {e}")
                time.sleep(10)
    
    # ============================================================
    # GENERIC GET / SET
    # ============================================================
    
    def set(self, key, value):
        with self.lock:
            self.data[key] = value
        self._save(blocking=False)
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
        self._save(blocking=False)
    
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
        self._save(blocking=False)
    
    def store_learning(self, entry):
        with self.lock:
            self.data.setdefault("learning_log", [])
            self.data["learning_log"].append(entry)
            log.info(f"[Learning Stored] {entry}")
        self._save(blocking=False)
    
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
        self._save(blocking=False)
    
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
        self._save(blocking=False)
    
    def get_learning_queue(self):
        with self.lock:
            return list(self.data.get("learning_queue", []))
    
    def mark_learning_done(self, topic):
        """Mark all queued items with the given topic as processed."""
        with self.lock:
            for item in self.data.get("learning_queue", []):
                if isinstance(item, dict) and item.get("topic") == topic:
                    item["status"] = "processed"
        self._save(blocking=False)
    
    # ============================================================
    # PERSONALITY / PREFERENCES
    # ============================================================
    
    def store_preferences(self, prefs):
        with self.lock:
            self.data["preferences"] = prefs
        log.info(f"[Preferences Stored] {prefs}")
        self._save(blocking=False)
    
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
    
    def search(self, query: str, limit: int = 5, max_results: int = None) -> list:
        """
        Search through facts and learning log for matching entries.
        
        Args:
            query: Search query string
            limit: Maximum number of results to return
            max_results: Alternative name for limit (for compatibility)
        
        Returns:
            List of matching facts and learning entries
        """
        if max_results is not None:
            limit = max_results
        
        if query is None or query.strip() == "":
            return []
        
        query_lower = query.lower()
        query_words = set(query_lower.split())
        results = []
        seen = set()
        
        try:
            # Search facts
            with self.lock:
                facts = self.data.get("facts", [])
                for fact in reversed(facts):
                    try:
                        fact_text = json.dumps(fact).lower()
                        if any(word in fact_text for word in query_words):
                            fact_str = json.dumps(fact)
                            if fact_str not in seen:
                                results.append(fact)
                                seen.add(fact_str)
                                if len(results) >= limit:
                                    return results
                    except Exception:
                        pass
            
            # Search learning log
            with self.lock:
                learning_log = self.data.get("learning_log", [])
                for entry in reversed(learning_log):
                    try:
                        entry_text = json.dumps(entry).lower()
                        if any(word in entry_text for word in query_words):
                            entry_str = json.dumps(entry)
                            if entry_str not in seen:
                                results.append(entry)
                                seen.add(entry_str)
                                if len(results) >= limit:
                                    return results
                    except Exception:
                        pass
            
            # Search interactions
            with self.lock:
                interactions = self.data.get("interactions", [])
                for interaction in reversed(interactions):
                    try:
                        interaction_text = json.dumps(interaction).lower()
                        if any(word in interaction_text for word in query_words):
                            interaction_str = json.dumps(interaction)
                            if interaction_str not in seen:
                                results.append(interaction)
                                seen.add(interaction_str)
                                if len(results) >= limit:
                                    return results
                    except Exception:
                        pass
            
            log.debug(f"[Search] Found {len(results)} results for '{query}'")
            return results[:limit]
        
        except Exception as e:
            log.error(f"Search failed: {e}")
            return []
    
    def recall(self, query: str, limit: int = 3, include_preferences=True):
        """
        Recall information matching the query.
        
        Args:
            query: Search query
            limit: Maximum results
            include_preferences: Whether to include preference data
        
        Returns:
            List of matching results
        """
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
        try:
            with self.lock:
                log.info(
                    "[KnowledgeDB Dump] Full current state:\n" +
                    json.dumps(self.data, indent=4, ensure_ascii=False)[:500] + "..."
                )
        except Exception as e:
            log.debug(f"Dump state error: {e}")
    
    def get_all(self):
        with self.lock:
            return dict(self.data)
    
    # ============================================================
    # COMPATIBILITY METHODS
    # ============================================================
    
    def recent_interactions(self, limit: int = 50):
        """Return the most recent interactions, up to `limit`."""
        with self.lock:
            interactions = self.data.get("interactions", [])
            return list(interactions[-limit:])
    
    def mark_training_step(self, step: int):
        """Record a training step in metadata."""
        with self.lock:
            self.data.setdefault("meta", {})
            self.data["meta"]["last_training_step"] = step
            self.data["meta"]["last_training_ts"] = int(time.time())
        self._save(blocking=False)
    
    def store_interaction(self, entry: dict):
        """Store a raw interaction dict (used by Collector)."""
        with self.lock:
            self.data.setdefault("interactions", [])
            self.data["interactions"].append(entry)
        self._save(blocking=False)
        log.debug(f"[Interaction Stored] {entry}")
    
    # ============================================================
    # SHUTDOWN
    # ============================================================
    
    def shutdown(self):
        log.info("KnowledgeDB shutting down — saving final state")
        self._save(blocking=True)  # Final save must be blocking


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
