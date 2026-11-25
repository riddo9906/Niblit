"""Read-only readiness check for native cognition seed integration."""
from __future__ import annotations
import json
import os
import sys
from dotenv import dotenv_values

def main():
    env_file = sys.argv[1] if len(sys.argv) > 1 else ".env"
    values = dotenv_values(env_file)
    os.environ.update({key: str(value) for key, value in values.items() if value is not None})
    from modules.permission_manager import PermissionManager
    manager = PermissionManager()
    namespace = os.getenv("NIBLIT_MEMORY_LAB_NAMESPACE", "desktop")
    ledger = os.getenv("NIBLIT_MEMORY_LAB_LEDGER", "")
    print(json.dumps({
        "memory_lab_enabled": os.getenv("NIBLIT_MEMORY_LAB_ENABLED", "0") == "1",
        "ledger_configured": bool(ledger),
        "namespace": namespace,
        "ingest_permission": manager.check(f"memory.ingest.{namespace}"),
        "read_permission": manager.check(f"memory.read.{namespace}"),
        "verify_permission": manager.check(f"memory.verify.{namespace}"),
        "projection_worker_profile_enabled": os.getenv("NIBLIT_MEMORY_PROJECTION_WORKER", "1") != "0",
    }, indent=2))
if __name__ == "__main__":
    main()
