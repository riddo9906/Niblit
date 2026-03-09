# trainer.py

import logging, random

log = logging.getLogger("Trainer")

class Trainer:
    def __init__(self, collector):
        self.collector = collector
        self.steps = 0

    def step_if_needed(self):
        if self.collector.data:
            # Simulate training step
            self.steps += 1
            log.debug(f"[Trainer] Training step {self.steps} completed")