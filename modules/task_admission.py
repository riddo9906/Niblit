"""Shared task admission via the existing private memory gateway.

No queue, prompt storage, paid provider or expiry-based overlap. The authority
survives process restarts in SQLite. Ambiguous failures remain quarantined.
"""
from contextlib import contextmanager
from contextvars import ContextVar
from functools import wraps
import asyncio
import hashlib
import os
from pathlib import Path
import secrets
import time
import urllib.error
from urllib.parse import urlsplit
import httpx

_held=ContextVar('niblit_task_held',default=False)
_lease=ContextVar('niblit_task_lease',default=None)
_cancel_event=ContextVar('niblit_task_cancel_event',default=None)

def check_cancelled():
    event=_cancel_event.get()
    if event is not None and event.is_set():raise TaskCancelled('Research request cancelled; no further work scheduled')

def delegation_headers():
    token=_lease.get()
    return {'x-niblit-task-token':token} if token else {}


def ambiguous_failure(exc):
    seen=set()
    while exc is not None and id(exc) not in seen:
        seen.add(id(exc))
        if isinstance(exc,urllib.error.HTTPError):return exc.code>=500 or exc.code in (408,429)
        if isinstance(exc,(httpx.TransportError,TimeoutError,urllib.error.URLError,KeyboardInterrupt,SystemExit,asyncio.CancelledError)):
            return True
        if isinstance(exc,httpx.HTTPStatusError) and exc.response.status_code>=500:return True
        exc=exc.__cause__ or exc.__context__
    return False


class AdmissionBusy(RuntimeError):pass
class AdmissionUncertain(RuntimeError):pass
class TaskCancelled(RuntimeError):pass


def task_is_held():return _held.get()


class TaskAuthority:
    def __init__(self,gateway):
        self.gateway=gateway
        with gateway.db() as db:
            db.execute('CREATE TABLE IF NOT EXISTS task_admission(singleton INTEGER PRIMARY KEY CHECK(singleton=1),state TEXT,token_hash TEXT,owner TEXT,started REAL)')

            db.execute('''CREATE TABLE IF NOT EXISTS trading_admission(
                singleton INTEGER PRIMARY KEY CHECK(singleton=1), state TEXT NOT NULL,
                token_hash TEXT NOT NULL, owner TEXT NOT NULL, started REAL NOT NULL,
                pid INTEGER NOT NULL, process_started REAL NOT NULL, session_id TEXT)''')
            db.execute('''CREATE TABLE IF NOT EXISTS trading_admission_audit(
                id INTEGER PRIMARY KEY, at REAL NOT NULL, session_id TEXT,
                decision TEXT NOT NULL, reason TEXT NOT NULL)''')

            db.execute('CREATE TABLE IF NOT EXISTS inference_foreground_wait(singleton INTEGER PRIMARY KEY CHECK(singleton=1),request_id TEXT NOT NULL,expires REAL NOT NULL)')
            db.execute('CREATE TABLE IF NOT EXISTS task_delegations(token_hash TEXT, request_id TEXT, state TEXT, PRIMARY KEY(token_hash,request_id))')

    @staticmethod
    def _owner_gone(pid, process_started):
        import psutil
        try:
            return abs(psutil.Process(pid).create_time() - process_started) > 0.01
        except psutil.NoSuchProcess:
            return True
        except (psutil.Error, OSError):
            return False

    @staticmethod
    def _trading_audit(db, session_id, decision, reason):
        db.execute('INSERT INTO trading_admission_audit(at,session_id,decision,reason) VALUES(?,?,?,?)',
                   (time.time(), session_id, decision, reason))

    def _acquire_trading(self, session_id):
        # Broker delivery is deterministic and does not consume the inference
        # provider. Keep its single-flight reservation in the same authority.
        import psutil
        token = secrets.token_urlsafe(32)
        denied = None
        with self.gateway.db() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT * FROM trading_admission WHERE singleton=1').fetchone()
            if row:
                has_ledger = db.execute(
                    "SELECT 1 FROM sqlite_master WHERE type='table' AND name='trading_orders'"
                ).fetchone()
                uncertain = has_ledger and db.execute(
                    "SELECT 1 FROM trading_orders WHERE state IN ('sending','unknown','partial')"
                ).fetchone()
                if has_ledger and not uncertain and self._owner_gone(row['pid'], row['process_started']):
                    db.execute('DELETE FROM trading_admission WHERE singleton=1')
                    self._trading_audit(db, row['session_id'], 'recovered',
                                        'Owner process ended and broker ledger has no uncertain delivery')
                else:
                    denied = ('Prior broker delivery is quarantined' if row['state'] == 'quarantined'
                              else 'Another Core broker cycle owns admission')
            if denied:
                self._trading_audit(db, session_id, 'denied', denied)
            else:
                db.execute("INSERT INTO trading_admission VALUES(1,'active',?,'trading_cycle',?,?,?,?)",
                           (hashlib.sha256(token.encode()).hexdigest(), time.time(),
                            os.getpid(), psutil.Process().create_time(), session_id))
                self._trading_audit(db, session_id, 'granted', 'Core broker cycle admitted')
        if denied:
            raise AdmissionBusy(denied)
        return {'token': token, 'owner': 'trading_cycle', 'queued': False}

    def acquire(self,owner,*,session_id=None,request_id=None):
        if owner == 'trading_cycle':
            return self._acquire_trading(session_id)
        if owner not in {'portal_chat','local_tutor','core_tool_loop','core_inference','autonomous_step','trading_cycle','niblit_chat'}:raise ValueError('Unknown task owner')
        token=secrets.token_urlsafe(32)
        with self.gateway.db() as db:
            db.execute('BEGIN IMMEDIATE')
            now=time.time()
            # This expiry applies only to an ungranted scheduling preference.
            # Active/quarantined inference leases are NEVER expired or stolen.
            db.execute('DELETE FROM inference_foreground_wait WHERE expires<=?',(now,))
            waiter=db.execute('SELECT request_id,expires FROM inference_foreground_wait WHERE singleton=1').fetchone()
            active=db.execute('SELECT state FROM task_admission WHERE singleton=1').fetchone()
            if owner=='niblit_chat':
                import re
                if not isinstance(request_id,str) or not re.fullmatch('[a-f0-9]{32}',request_id):raise ValueError('Interactive request identity required')
                if active and active['state']=='quarantined':raise AdmissionUncertain('Prior inference remains quarantined')
                if waiter and waiter['request_id']!=request_id:raise AdmissionBusy('Another interactive message is waiting')
                if active:
                    db.execute('INSERT OR IGNORE INTO inference_foreground_wait VALUES(1,?,?)',(request_id,now+60))
                    return {'waiting':True,'queued':True,'retry_after':.5}
            elif waiter:
                raise AdmissionBusy('Interactive chat has the next inference slot')
            if active:raise AdmissionBusy('Another task is active or quarantined; no work queued')
            db.execute('DELETE FROM inference_foreground_wait WHERE request_id=?',(request_id,))
            db.execute('INSERT INTO task_admission VALUES(1,?,?,?,?)',('active',hashlib.sha256(token.encode()).hexdigest(),owner,now))
        return {'token':token,'owner':owner,'queued':False}

    def finish(self,token,uncertain=False):
        with self.gateway.db() as db:
            db.execute('BEGIN IMMEDIATE')
            broker = db.execute('SELECT token_hash,session_id FROM trading_admission WHERE singleton=1').fetchone()
            if broker and secrets.compare_digest(broker['token_hash'], hashlib.sha256(token.encode()).hexdigest()):
                if uncertain:
                    db.execute("UPDATE trading_admission SET state='quarantined' WHERE singleton=1")
                else:
                    db.execute('DELETE FROM trading_admission WHERE singleton=1')
                state = 'quarantined' if uncertain else 'idle'
                self._trading_audit(db, broker['session_id'], state, 'Core broker cycle finished')
                return {'state': state}
            row=db.execute('SELECT token_hash FROM task_admission WHERE singleton=1').fetchone()
            if not row or not secrets.compare_digest(row[0],hashlib.sha256(token.encode()).hexdigest()):raise ValueError('Task ownership mismatch')
            busy=db.execute("SELECT 1 FROM task_delegations WHERE token_hash=? AND state='active'",(row[0],)).fetchone()
            state=db.execute('SELECT state FROM task_admission WHERE singleton=1').fetchone()[0]
            uncertain=uncertain or bool(busy) or bool(db.execute("SELECT 1 FROM task_delegations WHERE token_hash=? AND state='uncertain'",(row[0],)).fetchone())
            if uncertain:db.execute("UPDATE task_admission SET state='quarantined' WHERE singleton=1")
            else:db.execute('DELETE FROM task_admission WHERE singleton=1')
        return {'state':'quarantined' if uncertain else 'idle'}

    def delegate(self,token,request_id,complete=False,uncertain=False):
        import re
        if not isinstance(token,str) or not 32<=len(token)<=120 or not re.fullmatch(r'[a-f0-9]{32}',request_id):
            raise ValueError('Invalid delegation')
        hashed=hashlib.sha256(token.encode()).hexdigest()
        with self.gateway.db() as db:
            db.execute('BEGIN IMMEDIATE')
            row=db.execute('SELECT token_hash,state FROM task_admission WHERE singleton=1').fetchone()
            if not row or not secrets.compare_digest(row[0],hashed):raise ValueError('Task ownership mismatch')
            if not complete and db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='task_authorizations'").fetchone():
                grant=db.execute('SELECT state,expires FROM task_authorizations WHERE token_hash=?',(hashed,)).fetchone()
                if grant and (grant['state']!='running' or grant['expires']<=time.time()):raise AdmissionBusy('Learning task authorization revoked or expired')
                if grant and db.execute('SELECT count(*) FROM task_delegations WHERE token_hash=?',(hashed,)).fetchone()[0]>=1:raise AdmissionBusy('Approved learning generation budget exhausted')
            if complete:
                uncertain=uncertain or row[1]=='quarantined'
                changed=db.execute("UPDATE task_delegations SET state=? WHERE token_hash=? AND request_id=? AND state='active'",('uncertain' if uncertain else 'complete',hashed,request_id)).rowcount
                if changed!=1:raise ValueError('Unknown or completed delegation')
                if uncertain:db.execute("UPDATE task_admission SET state='quarantined' WHERE singleton=1")
            else:
                if row[1]!='active':raise AdmissionBusy('Task quarantined')
                if db.execute("SELECT 1 FROM task_delegations WHERE token_hash=? AND (state='active' OR request_id=?)",(hashed,request_id)).fetchone():raise AdmissionBusy('Delegation busy or replayed')
                db.execute('INSERT INTO task_delegations VALUES(?,?,?)',(hashed,request_id,'active'))
        return {'state':'complete' if complete else 'claimed','execution_authorized':False}

    def status(self, resource='inference'):
        with self.gateway.db() as db:
            if resource == 'broker':
                row = db.execute(
                    'SELECT state,owner,started,session_id,pid,process_started '
                    'FROM trading_admission WHERE singleton=1'
                ).fetchone()
            else:
                row = db.execute('SELECT state,owner,started FROM task_admission WHERE singleton=1').fetchone()
        result = dict(row) if row else {'state':'idle'}
        if resource == 'broker' and row:
            result['owner_process_ended'] = self._owner_gone(row['pid'], row['process_started'])
        if resource != 'broker':
            with self.gateway.db() as db:
                waiting=db.execute('SELECT expires FROM inference_foreground_wait WHERE expires>?',(time.time(),)).fetchone()
            result.update(queued=bool(waiting),waiting_owner='niblit_chat' if waiting else None)
            return result
        return {**result, 'queued': False}


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
        body={'owner':owner}
        if owner=='niblit_chat':
            import uuid
            body['request_id']=uuid.uuid4().hex
        deadline=time.monotonic()+60
        while True:
            check_cancelled()
            response=client.post(url+'/api/local-tutor/task/acquire',headers=headers,json=body)
            if response.status_code==423:raise AdmissionUncertain('Prior inference needs verified recovery')
            if response.status_code==409:raise AdmissionBusy('Another task or interactive message owns admission')
            response.raise_for_status();payload=response.json()
            if payload.get('waiting'):
                if owner!='niblit_chat' or time.monotonic()>=deadline:raise AdmissionBusy('Interactive wait limit reached; no generation started')
                time.sleep(.5);continue
            lease=payload['token'];break
        marker=_held.set(True)
        lease_marker=_lease.set(lease)
        try:
            yield
        except BaseException as exc:
            # No automatic expiry: the old provider may still be generating.
            try:client.post(url+'/api/local-tutor/task/finish',headers=headers,json={'token':lease,'uncertain':ambiguous_failure(exc)}).raise_for_status()
            except Exception:pass
            raise
        else:
            finished=client.post(url+'/api/local-tutor/task/finish',headers=headers,json={'token':lease,'uncertain':False})
            finished.raise_for_status()
            if finished.json().get('state')=='quarantined':
                raise AdmissionUncertain('Task remains reserved: delegated work is incomplete or uncertain')
        finally:
            _lease.reset(lease_marker)
            _held.reset(marker)


def task_owned(owner):
    def decorate(fn):
        @wraps(fn)
        def wrapped(*args,**kwargs):
            event=kwargs.get('cancel_event') or _cancel_event.get()
            marker=_cancel_event.set(event)
            try:
                check_cancelled()
                with admitted(owner):
                    result=fn(*args,**kwargs)
                    check_cancelled()
                    return result
            finally:_cancel_event.reset(marker)
        return wrapped
    return decorate
