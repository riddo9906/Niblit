import json
import time

class LocalDB:
    def __init__(self, path="niblit.db"):
        self.path = path
        if not self._exists():
            self._write({"log": []})

    def _exists(self):
        try:
            open(self.path).close()
            return True
        except:
            return False

    def _read(self):
        return json.loads(open(self.path).read())

    def _write(self, data):
        with open(self.path, "w") as f:
            f.write(json.dumps(data, indent=2))

    def add_entry(self, key, value):
        data = self._read()
        data["log"].append({
            "ts": time.time(),
            "key": key,
            "value": value
        })
        self._write(data)

    def get_log(self):
        return self._read()["log"]

