# collector_full.py

import logging
from datetime import datetime

log = logging.getLogger("Collector")


class Collector:

    def __init__(self, db=None, trainer=None, self_teacher=None):

        self.buffer = []
        self.db = db
        self.trainer = trainer
        self.self_teacher = self_teacher

        self.flush_threshold = 40
        self.train_trigger = 8          # interactions before training step
        self.auto_learn_sources = {"research","llm","external"}

    # ==========================================
    # MAIN CAPTURE
    # ==========================================
    def capture(self, user_input, response, source="brain", meta=None):

        entry = {
            "time": datetime.utcnow().isoformat(),
            "input": user_input,
            "response": response,
            "source": source,
            "meta": meta or {}
        }

        self.buffer.append(entry)

        log.info(f"[Collector] captured interaction from {source}")

        # ---------- STORE DB ----------
        if self.db:
            try:
                self.db.store_interaction(entry)
            except Exception as e:
                log.warning(f"[Collector] DB store failed: {e}")

        # ---------- TRAINER WAKE ----------
        self._maybe_trigger_training()

        # ---------- SELF TEACH WAKE ----------
        self._maybe_trigger_self_teach(entry)

        self.flush_if_needed()

    # ==========================================
    # COMPATIBILITY ADD()
    # ==========================================
    def add(self, entry):

        self.buffer.append(entry)

        if self.db:
            try:
                self.db.store_interaction(entry)
            except Exception:
                pass

        self._maybe_trigger_training()
        self._maybe_trigger_self_teach(entry)

        self.flush_if_needed()

    # ==========================================
    # TRAINER AUTO-WAKE
    # ==========================================
    def _maybe_trigger_training(self):

        if not self.trainer:
            return

        if len(self.buffer) % self.train_trigger == 0:
            try:
                self.trainer.step_if_needed(self.buffer)
            except Exception as e:
                log.warning(f"[Collector] Trainer wake failed: {e}")

    # ==========================================
    # SELF-TEACH AUTO-WAKE
    # ==========================================
    def _maybe_trigger_self_teach(self, entry):

        if not self.self_teacher:
            return

        src = entry.get("source","")

        # only learn from meaningful sources
        if src in self.auto_learn_sources:

            topic = entry.get("input","")

            if topic and len(topic) > 4:
                try:
                    log.info(f"[Collector] auto self-teach triggered: {topic}")
                    self.self_teacher.teach(topic[:120])
                except Exception as e:
                    log.warning(f"[Collector] SelfTeacher failed: {e}")

    # ==========================================
    # BUFFER MANAGEMENT
    # ==========================================
    def flush_if_needed(self):

        if len(self.buffer) >= self.flush_threshold:

            log.info("[Collector] flushing RAM buffer")

            if self.db:
                for e in self.buffer:
                    try:
                        self.db.store_interaction(e)
                    except Exception:
                        pass

            self.buffer.clear()


if __name__ == "__main__":
    print("Running collector_full.py")
