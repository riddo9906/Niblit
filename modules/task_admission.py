"""Shared task admission via the existing private memory gateway.

No queue, prompt storage, paid provider or expiry-based overlap. The authority
survives process restarts in SQLite. Ambiguous failures remain quarantined.
"""
from contextlib import contextmanager
from contextvars import ContextVar
from functools import wraps
import hashlib
import os
from pathlib import Path
import secrets
import time
import urllib.error
from urllib.parse import urlsplit
import httpx

_held=ContextVar('niblit_task_held',default=False)


def ambiguous_failure(exc):
    seen=set()
    while exc is not None and id(exc) not in seen:
        seen.add(id(exc))
        if isinstance(exc,(httpx.TransportError,TimeoutError,urllib.error.URLError,KeyboardInterrupt,SystemExit)):
            return True
        if isinstance(exc,httpx.HTTPStatusError) and exc.response.status_code>=500:return True
        exc=exc.__cause__ or exc.__context__
    return False


class AdmissionBusy(RuntimeError):pass


def task_is_held():return _held.get()


class TaskAuthority:
    def __init__(self,gateway):
        self.gateway=gateway
        with gateway.db() as db:
            db.execute('CREATE TABLE IF NOT EXISTS task_admission(singleton INTEGER PRIMARY KEY CHECK(singleton=1),state TEXT,token_hash TEXT,owner TEXT,started REAL)')

    def acquire(self,owner):
        if owner not in {'portal_chat','local_tutor','core_tool_loop','core_inference','autonomous_step'}:raise ValueError('Unknown task owner')
        token=secrets.token_urlsafe(32)
        with self.gateway.db() as db:
            db.execute('BEGIN IMMEDIATE')
            if db.execute('SELECT 1 FROM task_admission WHERE singleton=1').fetchone():raise AdmissionBusy('Another task is active or quarantined; no work queued')
            db.execute('INSERT INTO task_admission VALUES(1,?,?,?,?)',('active',hashlib.sha256(token.encode()).hexdigest(),owner,time.time()))
        return {'token':token,'owner':owner,'queued':False}

    def finish(self,token,uncertain=False):
        with self.gateway.db() as db:
            db.execute('BEGIN IMMEDIATE')
            row=db.execute('SELECT token_hash FROM task_admission WHERE singleton=1').fetchone()
            if not row or not secrets.compare_digest(row[0],hashlib.sha256(token.encode()).hexdigest()):raise ValueError('Task ownership mismatch')
            if uncertain:db.execute("UPDATE task_admission SET state='quarantined' WHERE singleton=1")
            else:db.execute('DELETE FROM task_admission WHERE singleton=1')
        return {'state':'quarantined' if uncertain else 'idle'}

    def status(self):
        with self.gateway.db() as db:
            row=db.execute('SELECT state,owner,started FROM task_admission WHERE singleton=1').fetchone()
        return {'state':row[0],'owner':row[1],'started':row[2],'queued':False} if row else {'state':'idle','queued':False}


@contextmanager
def admitted(owner):
    if os.getenv('NIBLIT_SHARED_ADMISSION','0')!='1' or _held.get():
        yield;return
    url=os.getenv('NIBLIT_ADMISSION_URL','http://127.0.0.1:8772')
    parsed=urlsplit(url)
    if parsed.scheme!='http' or parsed.hostname not in {'127.0.0.1','localhost','host.docker.internal'} or parsed.port!=8772 or parsed.path or parsed.query or parsed.fragment or parsed.username:
        raise ValueError('Admission authority must be the fixed private gateway')
    keypath=os.getenv('NIBLIT_PORTAL_GGUF_KEY_FILE',str(Path(__file__).resolve().parents[1]/'runtime/client-portal/gguf-api-key'))
    key=Path(keypath).read_text().strip()
    if len(key)<32:raise ValueError('Admission authentication unavailable')
    with httpx.Client(trust_env=False,timeout=5) as client:
        headers={'Authorization':'Bearer '+key}
        response=client.post(url+'/api/local-tutor/task/acquire',headers=headers,json={'owner':owner})
        if response.status_code==409:raise AdmissionBusy('Niblit is completing another task; no request was queued')
        response.raise_for_status();lease=response.json()['token']
        marker=_held.set(True)
        try:
            yield
        except BaseException as exc:
            # No automatic expiry: the old provider may still be generating.
            try:client.post(url+'/api/local-tutor/task/finish',headers=headers,json={'token':lease,'uncertain':ambiguous_failure(exc)}).raise_for_status()
            except Exception:pass
            raise
        else:
            client.post(url+'/api/local-tutor/task/finish',headers=headers,json={'token':lease,'uncertain':False}).raise_for_status()
        finally:_held.reset(marker)


def task_owned(owner):
    def decorate(fn):
        @wraps(fn)
        def wrapped(*args,**kwargs):
            with admitted(owner):return fn(*args,**kwargs)
        return wrapped
    return decorate
