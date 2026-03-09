# trainer_full.py

import logging

log = logging.getLogger("Trainer")


class Trainer:

    def __init__(self, db=None):
        self.db = db
        self.steps = 0

    def step_if_needed(self, interactions):

        if not interactions:
            return

        self.steps += 1

        log.info(f"[Trainer] Training step {self.steps} using {len(interactions)} samples")

        # optional DB training flag
        if self.db:
            try:
                self.db.mark_training_step(self.steps)
            except Exception:
                pass


if __name__ == "__main__":
    print('Running trainer_full.py')
