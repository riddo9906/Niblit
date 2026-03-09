# collector.py

import logging

log = logging.getLogger("Collector")

class Collector:
    def __init__(self):
        self.data = []

    def add(self, entry):
        self.data.append(entry)
        log.debug(f"[Collector] New entry added: {entry}")

    def flush_if_needed(self):
        if len(self.data) > 50:  # arbitrary flush threshold
            self.data.clear()
            log.debug("[Collector] Data flushed")