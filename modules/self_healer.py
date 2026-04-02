#!/usr/bin/env python3
# modules/self_healer.py

import time
from collections import deque

try:
    from modules.hybrid_qdrant_manager import HybridQdrantManager
except Exception:
    HybridQdrantManager = None

try:
    from modules.self_monitor import SelfMonitor
except Exception:
    SelfMonitor = None


class SelfHealer:
    def __init__(self, db, hybrid_manager=None, self_monitor=None):
        self.db = db
        self.hybrid_manager = hybrid_manager
        self.self_monitor = self_monitor
        self._history = deque(maxlen=100)

    def repair(self):
        repaired = 0
        try:
            facts = self.db.list_facts(500)
        except Exception:
            facts = []

        for f in facts:
            val = f.get("value")
            if val is None or str(val).strip() == "":
                try:
                    self.db.add_fact(
                        f.get("key", "unknown"),
                        "[REPAIRED EMPTY FACT]",
                        tags=f.get("tags", [])
                    )
                    repaired += 1
                except Exception:
                    pass

        result = f"Repaired {repaired} broken or empty facts."
        entry = {"ts": int(time.time()), "result": result, "repaired": repaired}
        self._history.append(entry)

        if self.self_monitor is not None:
            try:
                self.self_monitor.log_event(
                    "HEAL_REPAIR", "Self-healer repair run",
                    metadata={"repaired": repaired}
                )
            except Exception:
                pass

        if self.hybrid_manager is not None:
            try:
                self.hybrid_manager.upsert(
                    result,
                    {"type": "repair_run", "repaired": repaired, "ts": entry["ts"]},
                    collection="niblit_system_events"
                )
            except Exception:
                pass

        return result

    def full_heal(self, orchestrator=None):
        msg = self.repair()
        if orchestrator:
            try:
                extra = orchestrator.run_repair_cycle()
                msg = msg + "\n" + str(extra)
            except Exception:
                pass
        return msg

    def repair_with_learning(self):
        """Run repair, store results, then query hybrid_manager for known-good patterns."""
        result = self.repair()
        suggestions = self._search_repair_patterns(result)

        if self.hybrid_manager is not None:
            try:
                self.hybrid_manager.upsert(
                    f"Learning repair: {result}",
                    {"type": "repair_learning", "ts": int(time.time()), "result": result},
                    collection="niblit_system_events"
                )
            except Exception:
                pass

        if self.self_monitor is not None:
            try:
                self.self_monitor.log_event(
                    "LEARNING", "repair_with_learning completed",
                    metadata={"result": result, "suggestions_count": len(suggestions)}
                )
            except Exception:
                pass

        return {"result": result, "suggestions": suggestions}

    def _search_repair_patterns(self, issue_text):
        """Query hybrid_manager for similar past repairs and return suggestions."""
        if self.hybrid_manager is None:
            return []
        try:
            hits = self.hybrid_manager.query(
                issue_text,
                collection="niblit_system_events",
                top_k=5
            )
            return [h.get("payload", {}).get("_text", str(h)) for h in (hits or [])]
        except Exception:
            return []

    def get_repair_history(self):
        """Return the last 10 repair entries."""
        return list(self._history)[-10:]


if __name__ == "__main__":
    print("Running self_healer.py")
