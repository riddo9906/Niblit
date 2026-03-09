import os, threading, time
from .db import LocalDB

class LocalLLMAdapter:
    def __init__(self, db_path="local_llm.db"):
        self.db = LocalDB(db_path)
        self.model_loaded = False
        self.model_name = None

    def load(self, model_name="tiny-llama-1B"):
        self.model_name = model_name
        self.model_loaded = True
        self.db.add_entry("system", f"LocalLLM loaded model: {model_name}")
        return f"Local LLM loaded: {model_name}"

    def generate(self, prompt, max_tokens=200, online_adapter=None):
        """
        Use online adapter if available, else local pseudo-model.
        """
        if online_adapter and hasattr(online_adapter, 'is_online') and online_adapter.is_online():
            return online_adapter.query(prompt)
        return self._local_generate(prompt, max_tokens)

    def _local_generate(self, prompt, max_tokens=200):
        if not self.model_loaded:
            return "LocalLLM: No model loaded."
        base = ["Analyzing prompt...", "Generating structured completion...", "Applying mini-transformer output..."]
        seed = hash(prompt) % len(base)
        generated = base[seed] + "\n\n" + f"Response: {prompt[::-1][:max_tokens]}"
        self.db.add_entry("generation", {"prompt": prompt, "output": generated})
        return generated

    def embed(self, text):
        if not self.model_loaded:
            return "LocalLLM: No model loaded."
        vec = [round((ord(c) % 97) / 97, 3) for c in text][:32]
        self.db.add_entry("embedding", {"text": text, "vector": vec})
        return vec

    def background_learning(self, text):
        def worker(msg):
            time.sleep(0.2)
            self.db.add_entry("learn", {"ingested": msg})
        threading.Thread(target=worker, args=(text,), daemon=True).start()
        return "Background learn cycle started."

    def chat(self, prompt, max_tokens=150, online_adapter=None):
        return self.generate(prompt, max_tokens=max_tokens, online_adapter=online_adapter)
if __name__ == "__main__":
    print('Running local_llm_adapter.py')
