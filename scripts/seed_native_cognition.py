"""Preview or permission-gated seed of Niblit's native cognition foundation."""
from __future__ import annotations
import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from dotenv import dotenv_values
from modules.native_cognition.seed import seed_memory

def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", required=True)
    parser.add_argument("--ledger", required=True)
    parser.add_argument("--namespace", default="desktop")
    parser.add_argument("--principal", default="desktop_operator")
    parser.add_argument("--apply", action="store_true",
                        help="Queue seed records through the existing governed memory outbox.")
    args = parser.parse_args()
    if not args.apply:
        print(json.dumps(seed_memory(None, apply=False), indent=2))
        return 0
    values = dotenv_values(args.env_file)
    # Load the same operator profile before PermissionManager is imported.
    os.environ.update({key: str(value) for key, value in values.items() if value is not None})
    from modules.core_tool_runtime import _permission_manager
    manager = _permission_manager()
    ingest_grant = f"memory.ingest.{args.namespace}"
    if not manager.check(ingest_grant):
        raise PermissionError(f"Existing operator grant required: {ingest_grant}")
    from modules.memory_laboratory.gateway import MemoryGateway
    from modules.memory_laboratory.runtime import MemoryRuntime
    from modules.memory_laboratory.setup import Config
    gateway = MemoryGateway(Config.from_values(values), args.ledger)
    runtime = MemoryRuntime(gateway, scope={
        "namespace": args.namespace, "principal": args.principal})
    try:
        gateway.require("ingest", args.namespace, args.principal)
        backup_grant = f"memory.read.{args.namespace}"
        backup_receipt = "skipped_no_existing_read_grant"
        if manager.check(backup_grant):
            backup_dir = Path(args.ledger).resolve().parent / "backups"
            backup_path = backup_dir / "pre-native-cognition-0.1.0.sqlite3"
            if not backup_path.exists():
                backup_receipt = runtime.backup(backup_path)["path"]
            else:
                backup_receipt = str(backup_path)
        result = seed_memory(runtime, apply=True)
        result["pre_seed_backup"] = backup_receipt
        print(json.dumps(result, indent=2))
        return 0
    finally:
        gateway.close()

if __name__ == "__main__":
    raise SystemExit(main())
