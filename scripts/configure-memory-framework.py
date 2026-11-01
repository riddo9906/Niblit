"""Enable the local memory projection without changing execution or model settings."""
import json
from pathlib import Path
import shutil
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    from dotenv import dotenv_values, set_key
    values = dotenv_values(ROOT / ".env")
    state = ROOT / "runtime/memory-framework"
    state.mkdir(parents=True, exist_ok=True)
    profile = ROOT / ".env.memory-laboratory"
    if not profile.is_file():
        raise SystemExit("Create the private memory-laboratory profile first")
    source = Path(values.get("NIBLIT_MEMORY_PATH") or ROOT / "dist/niblit/niblit_memory.json")
    if not source.is_file():
        raise SystemExit("Existing memory source not found; refusing an empty migration")
    backup = state / "original-knowledge-before-qdrant.json"
    if not backup.exists():
        shutil.copy2(source, backup)
    permissions = Path(values.get("NIBLIT_PERMISSION_FILE") or state / "permissions.json")
    permissions.parent.mkdir(parents=True, exist_ok=True)
    old = json.loads(permissions.read_text()) if permissions.exists() else {}
    for scope in ("desktop", "trading"):
        for action in ("read", "ingest", "consolidate"):
            old[f"memory.{action}.{scope}"] = True
    permissions.write_text(json.dumps(old, indent=2), encoding="utf-8")
    updates = {"NIBLIT_MEMORY_LAB_ENABLED": "1", "NIBLIT_MEMORY_LAB_ENV_FILE": str(profile),
               "NIBLIT_MEMORY_LAB_LEDGER": str(state / "ledger.sqlite3"),
               "NIBLIT_MEMORY_SYNC_SOURCE": str(source), "NIBLIT_PERMISSION_FILE": str(permissions)}
    for key, value in updates.items():
        set_key(ROOT / ".env", key, value)
    print(json.dumps({"configured": True, "mode": "local_qdrant", "original_memory_preserved": True,
                      "paid_inference": False, "financial_execution_changed": False}))


if __name__ == "__main__":
    main()
