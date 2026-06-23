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


class SelfMaintenance:
    def __init__(self, db, hybrid_manager=None, self_monitor=None):
        self.db = db
        self.hybrid_manager = hybrid_manager
        self.self_monitor = self_monitor
        self._history = deque(maxlen=100)

    def run(self, retention_days=30):
        cutoff = int(time.time()) - int(retention_days)*24*3600
        before = len(self.db.data.get('interactions',[]))
        self.db.data['interactions'] = [i for i in self.db.data.get('interactions',[]) if i['ts'] >= cutoff]
        removed = before - len(self.db.data['interactions'])
        self.db.condense(keep_top=50)
        self.db._save()
        summary = f"Removed {removed} old interactions and condensed memory."

        entry = {"ts": int(time.time()), "summary": summary, "removed": removed}
        self._history.append(entry)

        if self.self_monitor is not None:
            try:
                self.self_monitor.log_event(
                    "MAINTENANCE", "Self-maintenance run",
                    metadata={"removed": removed, "retention_days": int(retention_days)}
                )
            except Exception:
                pass

        if self.hybrid_manager is not None:
            try:
                self.hybrid_manager.upsert(
                    summary,
                    {"type": "maintenance_run", "removed": removed,
                     "retention_days": retention_days, "ts": entry["ts"]},
                    collection="niblit_system_events"
                )
            except Exception:
                pass

        return summary

    def run_with_learning(self, retention_days=30):
        """Run maintenance then persist results to hybrid_manager and self_monitor."""
        summary = self.run(retention_days=retention_days)
        entry = self._history[-1] if self._history else {"ts": int(time.time()), "summary": summary}

        if self.hybrid_manager is not None:
            try:
                self.hybrid_manager.upsert(
                    f"Learning maintenance run: {summary}",
                    {"type": "maintenance_learning", "ts": entry.get("ts"), "summary": summary},
                    collection="niblit_system_events"
                )
            except Exception:
                pass

        if self.self_monitor is not None:
            try:
                self.self_monitor.log_event(
                    "LEARNING", "run_with_learning completed",
                    metadata={"summary": summary}
                )
            except Exception:
                pass

        return summary

    def get_history(self):
        """Return the last 10 maintenance summaries."""
        return list(self._history)[-10:]


if __name__ == "__main__":
    print('Running self_maintenance.py')
