"""Start the installed Docker Desktop if needed; preserve all existing data."""
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from modules.desktop_dependencies import ensure_docker

if __name__ == '__main__':
    result = ensure_docker()
    print(json.dumps(result))
    raise SystemExit(0 if result['ready'] else 1)
