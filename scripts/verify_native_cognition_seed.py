"""Read-only verification of native cognition seed queue/projection state."""
from __future__ import annotations
import argparse
import json
import sqlite3
from pathlib import Path

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ledger", required=True)
    args = parser.parse_args()
    db_path = Path(args.ledger).resolve()
    uri = db_path.as_uri() + "?mode=ro"
    with sqlite3.connect(uri, uri=True, timeout=10) as db:
        db.row_factory = sqlite3.Row
        rows = db.execute(
            "SELECT h.source,o.state,o.attempts,o.error FROM source_heads AS h "
            "JOIN ingestion_outbox AS o ON o.id=h.id "
            "WHERE h.source LIKE 'native://niblit/foundation/%' ORDER BY h.source"
        ).fetchall()
        record_rows = db.execute(
            "SELECT source,COUNT(*) AS total,"
            "SUM(CASE WHEN active=1 THEN 1 ELSE 0 END) AS active,"
            "SUM(CASE WHEN projection='verified' THEN 1 ELSE 0 END) AS projected "
            "FROM records WHERE source LIKE 'native://niblit/foundation/%' "
            "GROUP BY source ORDER BY source"
        ).fetchall()
    print(json.dumps({
        "seed_sources": len(rows),
        "outbox": [{"source": r["source"], "state": r["state"],
                    "attempts": r["attempts"], "error_type": type(r["error"]).__name__
                    if r["error"] else None} for r in rows],
        "record_projection": [dict(r) for r in record_rows],
        "content_emitted": False,
    }, indent=2))
if __name__ == "__main__":
    main()
