# modules/filesystem_manager.py
import os

class FileSystemManager:
    def ensure_structure(self, base_path):
        folders = ['modules','_pycache_','logs','scripts','downloads','uploads']
        for f in folders:
            p = os.path.join(base_path, f)
            if not os.path.exists(p):
                os.makedirs(p, exist_ok=True)
        return f"Ensured structure at {base_path}"
