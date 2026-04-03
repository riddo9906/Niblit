import json, os

try:
    from niblit_memory import _writable_path as _mem_writable_path
except Exception:
    import tempfile as _tempfile
    def _mem_writable_path(fn, env_var=None):  # type: ignore[misc]
        if env_var:
            v = os.environ.get(env_var, "").strip()
            if v:
                return v
        cwd = os.getcwd()
        return os.path.join(cwd, fn) if os.access(cwd, os.W_OK) else os.path.join(_tempfile.gettempdir(), fn)

PERM_FILE = _mem_writable_path("niblit_perms.json")

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
        if action in self.perms:
            return self.perms[action]
        resp = input(f"Grant permission for '{action}'? ({description}) [y/N]: ").strip().lower()
        allow = resp in ('y','yes')
        self.perms[action] = bool(allow)
        self.save()
        return allow

    def check(self, action):
        return bool(self.perms.get(action, False))
if __name__ == "__main__":
    print('Running permission_manager.py')
