"""Consistent SQLite backup; run inside the portal with a mounted /backups folder.

No passwords or memory contents are printed. Copy completed backups off the host;
a second directory on the same disk is not disaster recovery.
"""
import os
from pathlib import Path
import sqlite3
from datetime import datetime, timezone


def backup(source, destination):
    source, destination = Path(source), Path(destination)
    if not source.is_file():
        raise ValueError('Portal database not found')
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        raise ValueError('Refusing to overwrite an existing backup')
    with sqlite3.connect(source.as_uri()+'?mode=ro', uri=True) as incoming:
        with sqlite3.connect(destination) as outgoing:
            incoming.backup(outgoing)
            if outgoing.execute('PRAGMA integrity_check').fetchone()[0]!='ok':
                raise ValueError('Backup integrity check failed')
    return destination.name


if __name__=='__main__':
    source=Path(os.environ.get('NIBLIT_PORTAL_DATA','/data'))/'session.sqlite3'
    target=Path(os.environ.get('NIBLIT_PORTAL_BACKUPS','/backups'))/('portal-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')+'.sqlite3')
    print('Created verified backup:',backup(source.resolve(),target))
