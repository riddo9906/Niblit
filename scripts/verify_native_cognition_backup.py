from pathlib import Path
import sqlite3, json
p=Path(r"C:\Users\Riyaad\Documents\GitHub\Niblit\runtime\memory-framework\backups\pre-native-cognition-0.1.0.sqlite3")
with sqlite3.connect(p.as_uri()+"?mode=ro",uri=True,timeout=30) as db:
    result=db.execute("PRAGMA quick_check").fetchone()[0]
    tables=db.execute("SELECT COUNT(*) FROM sqlite_master WHERE type='table'").fetchone()[0]
print(json.dumps({"backup_exists":p.exists(),"bytes":p.stat().st_size,"quick_check":result,"table_count":tables}))
