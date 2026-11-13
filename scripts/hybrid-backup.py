"""Online SQLite backup/restore to NEW paths only; never overwrite a live store."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import sqlite3
import time
import uuid
from contextlib import closing


def backup_sqlite(source, directory):
    source=Path(source).resolve(strict=True);directory=Path(directory).resolve()
    directory.mkdir(parents=True,exist_ok=True)
    target=directory/(source.stem+'-'+uuid.uuid4().hex+'.sqlite3')
    partial=target.with_suffix('.partial');start=time.monotonic()
    def bounded(status,remaining,total):
        if time.monotonic()-start>180:raise TimeoutError('Online backup deadline exceeded; partial is not a valid backup')
    with closing(sqlite3.connect(source.as_uri()+'?mode=ro',uri=True,timeout=5)) as src,closing(sqlite3.connect(partial)) as dst:
        # Pin a read snapshot. With the canonical WAL database, writers keep
        # running and concurrent commits cannot repeatedly restart the backup.
        src.execute('BEGIN')
        src.execute('SELECT name FROM sqlite_master LIMIT 1').fetchone()
        src.backup(dst,pages=1024,progress=bounded,sleep=.01)
        if dst.execute('PRAGMA integrity_check').fetchone()[0]!='ok':raise RuntimeError('Backup integrity failed')
    partial.rename(target)
    receipt={'source':str(source),'backup':str(target),'sha256':hashlib.sha256(target.read_bytes()).hexdigest(),
             'integrity':'ok','created_at':time.time(),'method':'sqlite_online_backup','restore_tested':False}
    target.with_suffix('.manifest.json').write_text(json.dumps(receipt,indent=2),encoding='utf-8')
    return receipt


def restore_new(backup, destination):
    backup=Path(backup).resolve(strict=True);destination=Path(destination).resolve()
    if destination.exists():raise FileExistsError('Restore requires a new destination, never a running store')
    receipt=json.loads(backup.with_suffix('.manifest.json').read_text(encoding='utf-8'))
    if hashlib.sha256(backup.read_bytes()).hexdigest()!=receipt['sha256']:raise ValueError('Backup checksum mismatch')
    destination.parent.mkdir(parents=True,exist_ok=True)
    with closing(sqlite3.connect(backup.as_uri()+'?mode=ro',uri=True)) as db:
        if db.execute('PRAGMA integrity_check').fetchone()[0]!='ok':raise ValueError('Backup integrity failed')
    # Exclusive creation avoids an overwrite if another process races this restore.
    with backup.open('rb') as src,destination.open('xb') as dst:shutil.copyfileobj(src,dst)
    return {'restored_to':str(destination),'live_store_replaced':False}


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('action',choices=['backup','restore-new'])
    parser.add_argument('source');parser.add_argument('destination');args=parser.parse_args()
    print(json.dumps(backup_sqlite(args.source,args.destination) if args.action=='backup' else restore_new(args.source,args.destination)))
