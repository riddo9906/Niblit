# self_idea_generator.py

import threading, time, logging, re
from datetime import datetime, timezone

log = logging.getLogger("SelfIdeaGenerator")

class SelfIdeaGenerator:
    def __init__(self, db=None, collector=None):
        self.db = db
        self.collector = collector
        self.running = True
        # Start the autonomous loop in a daemon thread so it runs in the
        # background without blocking the main application startup.
        self._thread = threading.Thread(
            target=self.autonomous_loop, daemon=True, name="SelfIdeaGenerator"
        )
        self._thread.start()
        log.info("[SelfIdeaGenerator] Background idea-generation thread started")

    def generate_plan(self, idea_text):
        # Skip ideas that are just "No data found" placeholders.
        if idea_text and re.search(r"No data found for\b", idea_text, re.IGNORECASE):
            log.debug("[Generator] Skipping 'No data found' placeholder idea")
            return None
        plan = f"Implementation plan for '{idea_text}' - {datetime.now(timezone.utc).isoformat()}"
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
