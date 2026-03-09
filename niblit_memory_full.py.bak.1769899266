# niblit_memory.py

import json, threading, time, logging

log = logging.getLogger("NiblitMemory")

class MemoryManager:
    def __init__(self, filename="niblit_memory.json"):
        self.filename = filename
        self.lock = threading.Lock()
        self.memory = {}
        self.autosave_interval = 60
        t = threading.Thread(target=self._autosave_loop, daemon=True)
        t.start()

    def set(self, key, value):
        with self.lock:
            self.memory[key] = value
        log.debug(f"[Memory Set] {key}: {value}")

    def get(self, key, default=None):
        with self.lock:
            return self.memory.get(key, default)

    def autosave(self):
        with self.lock:
            try:
                with open(self.filename, 'w') as f:
                    json.dump(self.memory, f)
                log.debug("[Memory Autosaved]")
            except Exception as e:
                log.debug(f"[Memory Autosave Error] {e}")

    def _autosave_loop(self):
        while True:
            self.autosave()
            time.sleep(self.autosave_interval)