"""Run the existing Qdrant-backed memory worker independently of a desktop rebuild.

The same worker starts inside updated Core builds. This temporary standalone
entry also imports the previous release's KnowledgeDB without modifying it.
"""
import argparse
import json
import os
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()
    from dotenv import dotenv_values
    values = dotenv_values(ROOT / ".env")
    for key in ("NIBLIT_MEMORY_LAB_ENABLED", "NIBLIT_MEMORY_LAB_ENV_FILE", "NIBLIT_MEMORY_LAB_LEDGER",
                "NIBLIT_MEMORY_SYNC_SOURCE", "NIBLIT_PERMISSION_FILE"):
        if values.get(key):
            os.environ[key] = values[key]
    from modules.memory_laboratory.runtime import runtime_memory
    runtime = runtime_memory()
    if runtime is None:
        raise SystemExit("Memory framework is not configured")
    destination = ROOT / "diagnostics/memory-framework-status.json"
    try:
        while True:
            status = runtime.status()
            destination.write_text(json.dumps(status, indent=2), encoding="utf-8")
            if args.once:
                print(json.dumps(status))
                break
            time.sleep(10)
    except KeyboardInterrupt:
        pass
    finally:
        runtime.stop()


if __name__ == "__main__":
    main()
