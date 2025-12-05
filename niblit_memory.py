import json
import os
import time
import threading

MEMORY_FILE = os.path.join(os.path.dirname(__file__), "niblit_memory.json")

class MemoryManager:
    def __init__(self, autosave_interval=60):
        self.data = {"entries": []}
        self.file = MEMORY_FILE
        self._load()
        self.autosave_interval = autosave_interval
        self._start_autosave_thread()

    # ------------------------
    # Load memory from JSON
    # ------------------------
    def _load(self):
        try:
            if os.path.exists(self.file):
                with open(self.file, 'r', encoding='utf-8') as f:
                    self.data = json.load(f)
        except Exception as e:
            print(f"[Memory] Failed to load: {e}")
            self.data = {"entries": []}

    # ------------------------
    # Save memory to JSON
    # ------------------------
    def _save(self):
        try:
            with open(self.file, 'w', encoding='utf-8') as f:
                json.dump(self.data, f, indent=2)
        except Exception as e:
            print(f"[Memory] Failed to save: {e}")

    # ------------------------
    # Add an entry
    # ------------------------
    def add_entry(self, user_text, reply_text):
        entry = {
            "user": user_text,
            "reply": reply_text,
            "ts": int(time.time())
        }
        self.data["entries"].append(entry)
        self._save()

    # ------------------------
    # Show all entries
    # ------------------------
    def show_all(self):
        return self.data.get("entries", [])

    # ------------------------
    # Condense memory to keep only N latest
    # ------------------------
    def condense(self, keep_top=100):
        entries = self.data.get("entries", [])
        if len(entries) > keep_top:
            self.data["entries"] = entries[-keep_top:]
            self._save()

    # ------------------------
    # Autosave loop
    # ------------------------
    def _autosave_loop(self):
        while True:
            time.sleep(self.autosave_interval)
            self._save()

    def _start_autosave_thread(self):
        thread = threading.Thread(target=self._autosave_loop, daemon=True)
        thread.start()

    # ------------------------
    # Manual autosave trigger
    # ------------------------
    def autosave(self):
        self._save()
