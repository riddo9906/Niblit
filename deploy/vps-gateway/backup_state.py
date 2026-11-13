"""Consistent local recovery backup; never copies credentials or rewrites live state."""
import argparse
from datetime import datetime, timezone
from pathlib import Path
import sqlite3
from contextlib import closing

def backup(state, folder):
    state, folder = Path(state).resolve(), Path(folder).resolve()
    if not state.is_file():
        raise FileNotFoundError("Gateway state database unavailable")
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / ("gateway-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ") + ".sqlite3")
    # Reserve a new filename; never overwrite a prior recovery point.
    with target.open("xb"):
        pass
    with closing(sqlite3.connect(state.as_uri() + "?mode=ro", uri=True, timeout=5)) as source:
        with closing(sqlite3.connect(target)) as destination:
            source.backup(destination, pages=64, sleep=.05)
            if destination.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise RuntimeError("Backup integrity check failed")
    return target

if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("state")
    p.add_argument("folder")
    a = p.parse_args()
    print(backup(a.state, a.folder).name)
