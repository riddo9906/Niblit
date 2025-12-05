# modules/self_maintenance.py
import time

class SelfMaintenance:
    def __init__(self, db):
        self.db = db

    def run(self, retention_days=30):
        cutoff = int(time.time()) - int(retention_days)*24*3600
        before = len(self.db.data.get('interactions',[]))
        self.db.data['interactions'] = [i for i in self.db.data.get('interactions',[]) if i['ts'] >= cutoff]
        removed = before - len(self.db.data['interactions'])
        self.db.condense(keep_top=50)
        self.db._save()
        return f"Removed {removed} old interactions and condensed memory."
