# modules/device_manager.py
import os, platform

class DeviceManager:
    def info(self):
        return {"os": platform.system(), "platform": platform.platform(), "cwd": os.getcwd()}

    def list_files(self, path="."):
        try:
            return os.listdir(path)
        except Exception as e:
            return {"error": str(e)}
