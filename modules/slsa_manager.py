from threading import Thread
from slsa_generator_full import start_slsa, SLSAGenerator


class SLSAEngineManager:
    """Singleton manager to control SLSA engine dynamically."""

    def __init__(self):
        self.engine: SLSAGenerator | None = None
        self.thread: Thread | None = None

    def start(self, topics=None):
        if self.engine and not self.engine.stop_event.is_set():
            return "SLSA engine already running."
        # Start engine and keep the thread handle
        self.engine, self.thread = start_slsa(topics=topics)
        return "SLSA engine started."

    def stop(self):
        if self.engine and not self.engine.stop_event.is_set():
            self.engine.stop()
            if self.thread and self.thread.is_alive():
                self.thread.join()  # Wait until the thread fully exits
            self.engine = None
            self.thread = None
            return "SLSA engine stopped."
        return "SLSA engine is not running."

    def restart(self, topics=None):
        self.stop()
        return self.start(topics=topics)

    def status(self):
        if self.engine and not self.engine.stop_event.is_set():
            return f"SLSA engine running on topics: {self.engine.topics}"
        return "SLSA engine is not active."


# singleton
slsa_manager = SLSAEngineManager()


if __name__ == "__main__":
    print('Running slsa_manager.py')
