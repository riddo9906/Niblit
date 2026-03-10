# self_idea_generator.py

import threading, time, logging
from datetime import datetime

log = logging.getLogger("SelfIdeaGenerator")

class SelfIdeaGenerator:
    def __init__(self, db=None, collector=None):
        self.db = db
        self.collector = collector
        self.running = True

    def generate_plan(self, idea_text):
        plan = f"Implementation plan for '{idea_text}' - {datetime.utcnow().isoformat()}"
        if self.db:
            try:
                self.db.add_fact(f"impl:{idea_text}", plan, tags=['auto_generated'])
            except Exception:
                pass
        if self.collector:
            try:
                self.collector.capture(user_input=idea_text, response=plan, source="auto_generator")
            except Exception:
                pass
        log.info(f"[Generator] Generated plan for idea: {idea_text}")
        return plan

    def autonomous_loop(self, poll_interval=180):
        while self.running:
            if not self.db:
                time.sleep(poll_interval)
                continue

            try:
                ideas = [
                    f.get("value") for f in self.db.list_facts(500)
                    if f.get("key","").startswith("idea:")
                ]
                for idea in ideas[:5]:
                    self.generate_plan(idea)
            except Exception as e:
                log.error(f"[Generator] autonomous_loop error: {e}")
            time.sleep(poll_interval)

    def stop(self):
        self.running = False


if __name__ == "__main__":
    print('Running self_idea_generator.py')
