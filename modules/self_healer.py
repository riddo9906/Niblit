#!/usr/bin/env python3
# modules/self_healer.py

class SelfHealer:
    def __init__(self, db):
        self.db = db

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

        return f"Repaired {repaired} broken or empty facts."

    def full_heal(self, orchestrator=None):
        msg = self.repair()
        if orchestrator:
            try:
                extra = orchestrator.run_repair_cycle()
                msg = msg + "\n" + str(extra)
            except Exception:
                pass
        return msg

if __name__ == "__main__":
    print("Running self_healer.py")
