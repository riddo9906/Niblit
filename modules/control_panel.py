# modules/control_panel.py
class ControlPanel:
    def __init__(self, db, modules):
        self.db = db
        self.modules = modules

    def status(self):
        return {
            "facts_count": len(self.db.data.get('facts',[])),
            "interactions_count": len(self.db.data.get('interactions',[])),
            "available_modules": list(self.modules.keys())
        }
