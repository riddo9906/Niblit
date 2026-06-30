from __future__ import annotations

import sys
from pathlib import Path

print('cwd', Path.cwd())
print('repo_root', Path(__file__).resolve().parent)
print('sys.path[0]', sys.path[0])
print('has_repo_root', str(Path(__file__).resolve().parent) in sys.path)
try:
    import shared.governance_contract as g
    print('imported', g.__file__)
except Exception as exc:  # pragma: no cover - diagnostic
    print(type(exc).__name__, exc)
