"""Print credential-free native dependency readiness; perform no inference."""
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dotenv import dotenv_values
from modules.native_runtime_readiness import check_readiness


if __name__ == '__main__':
    # Explicit bounded profile overrides legacy .env settings for this check only.
    # Neither file nor the invoking process environment is modified.
    values = {**dotenv_values(ROOT / '.env'), **os.environ,
              **dotenv_values(ROOT / 'deploy/runtime/native-local.env.example')}
    report = check_readiness(values, ROOT)
    print(json.dumps(report, indent=2))
    raise SystemExit(0 if report['ready'] else 1)
