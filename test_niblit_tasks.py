from niblit_tasks import NiblitTasks


class MemoryWithNoneLogs:
    def __init__(self):
        self.events = []

    def get_learning_log(self):
        return None

    def log_event(self, message):
        self.events.append(message)

    def store_learning(self, entry):
        self.events.append(entry)

    def get_preferences(self):
        return {}

    def store_preferences(self, prefs):
        self.events.append(prefs)


def test_idle_think_handles_none_learning_log():
    memory = MemoryWithNoneLogs()
    tasks = NiblitTasks(brain=None, memory=memory)

    tasks.idle_think()

    assert memory.events == []
