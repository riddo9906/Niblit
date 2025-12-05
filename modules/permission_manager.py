# modules/permission_manager.py
import json, os

PERM_FILE = "niblit_perms.json"

class PermissionManager:
    def __init__(self):
        self.path = PERM_FILE
        self.perms = {}
        self._load()

    def _load(self):
        try:
            if os.path.exists(self.path):
                with open(self.path,'r',encoding='utf-8') as f:
                    self.perms = json.load(f)
        except Exception:
            self.perms = {}

    def save(self):
        with open(self.path,'w',encoding='utf-8') as f:
            json.dump(self.perms,f,indent=2)

    def ask(self, action, description):
        # If already decided, return decision
        if action in self.perms:
            return self.perms[action]
        # Ask user in terminal (safe)
        resp = input(f"Grant permission for '{action}'? ({description}) [y/N]: ").strip().lower()
        allow = resp in ('y','yes')
        self.perms[action] = bool(allow)
        self.save()
        return allow

    def check(self, action):
        return bool(self.perms.get(action, False))
