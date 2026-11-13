import json, os

try:
    from niblit_memory import _writable_path as _mem_writable_path
except Exception:
    import tempfile as _tempfile
    def _mem_writable_path(filename, env_var=None):  # type: ignore[misc]
        if env_var:
            v = os.environ.get(env_var, "").strip()
            if v:
                return v
        cwd = os.getcwd()
        return os.path.join(cwd, filename) if os.access(cwd, os.W_OK) else os.path.join(_tempfile.gettempdir(), filename)

PERM_FILE = _mem_writable_path("niblit_perms.json", env_var="NIBLIT_PERMISSION_FILE")

class PermissionManager:
    def __init__(self):
        self.path = PERM_FILE
        self.perms = {}
        self._load()

    def _load(self):
        try:
            if os.path.exists(self.path):
                with open(self.path,'r',encoding='utf-8') as f:
                    self.perms = json.load(f)
        except Exception:
            self.perms = {}

    def save(self):
        with open(self.path,'w',encoding='utf-8') as f:
            json.dump(self.perms,f,indent=2)

    def ask(self, action, description):
        if action in self.perms:
            return self.perms[action]
        resp = input(f"Grant permission for '{action}'? ({description}) [y/N]: ").strip().lower()
        allow = resp in ('y','yes')
        self.perms[action] = bool(allow)
        self.save()
        return allow

    def check(self, action):
        return bool(self.perms.get(action, False))
    @staticmethod
    def learning_spec(topic, justification, source_path='modules/memory_laboratory/runtime.py'):
        if not isinstance(topic,str) or not 3<=len(topic.strip())<=160:raise ValueError('Bounded learning objective required')
        if not isinstance(justification,str) or not 8<=len(justification.strip())<=1000:raise ValueError('Learning justification required')
        if source_path not in ('modules/memory_laboratory/runtime.py','modules/task_admission.py'):raise ValueError('Source outside bounded local research scope')
        return {'action':'learning.native_cycle','topic':topic.strip(),'justification':justification.strip(),
                'source_path':source_path,'namespace':'desktop','principal':'desktop_operator',
                'tools':['memory.recall','workspace_read','local_gguf','self_teacher.review','brain_trainer.source_observation','memory.observation'],
                'limits':{'cycles':1,'model_calls':1,'max_tokens':256,'source_reads':1,'source_chars':1800,'recall_hits':3,'observations':1,'wall_seconds':240},
                'expected_duration':'About 1–4 minutes; existing CPU model, one generation',
                'weights_training':False,'paid_requests':False,'trading_authority':False}

    @staticmethod
    def _learning_schema(db):
        db.execute('''CREATE TABLE IF NOT EXISTS task_authorizations(
            id TEXT PRIMARY KEY,spec TEXT NOT NULL,spec_hash TEXT NOT NULL,state TEXT NOT NULL,
            created REAL NOT NULL,expires REAL NOT NULL,runtime_id TEXT,token_hash TEXT,
            usage TEXT NOT NULL DEFAULT '{}',result TEXT)''')

    @staticmethod
    def _learning_hash(spec):
        import hashlib
        return hashlib.sha256(json.dumps(spec,sort_keys=True,allow_nan=False).encode()).hexdigest()

    def propose_learning(self,gateway,topic,justification,source_path='modules/memory_laboratory/runtime.py',renew=False):
        import time,uuid
        gateway.require('read','desktop','desktop_operator')
        spec=self.learning_spec(topic,justification,source_path);fingerprint=self._learning_hash(spec)
        with gateway.db() as db:
            self._learning_schema(db);db.execute('BEGIN IMMEDIATE')
            row=db.execute("SELECT id FROM task_authorizations WHERE spec_hash=? AND state='pending' AND expires>?",(fingerprint,time.time())).fetchone()
            if row:return row[0]
            denied=db.execute("SELECT id FROM task_authorizations WHERE spec_hash=? AND state='denied' ORDER BY created DESC LIMIT 1",(fingerprint,)).fetchone()
            if denied and not renew:return denied[0]
            if db.execute("SELECT count(*) FROM task_authorizations WHERE state IN ('pending','approved','running') AND expires>?",(time.time(),)).fetchone()[0]>=32:raise ValueError('Learning proposal limit reached')
            ident=uuid.uuid4().hex
            db.execute('INSERT INTO task_authorizations(id,spec,spec_hash,state,created,expires) VALUES(?,?,?,?,?,?)',(ident,json.dumps(spec,sort_keys=True),fingerprint,'pending',time.time(),time.time()+1800))
            gateway.audit(db,'learning.proposed',ident,spec_hash=fingerprint)
        return ident

    def learning_requests(self,gateway,runtime_id):
        import time
        gateway.require('read','desktop','desktop_operator')
        with gateway.db() as db:
            self._learning_schema(db)
            # Expiration/restart revokes grants, never inference ownership.
            db.execute("UPDATE task_authorizations SET state='expired' WHERE state IN ('pending','approved','running') AND expires<=?",(time.time(),))
            db.execute("UPDATE task_authorizations SET state='interrupted' WHERE state IN ('approved','running') AND runtime_id<>?",(runtime_id,))
            rows=db.execute('SELECT id,spec,spec_hash,state,created,expires,result FROM task_authorizations ORDER BY created DESC LIMIT 32').fetchall()
        return [{**dict(r),'spec':json.loads(r['spec']),'result':json.loads(r['result']) if r['result'] else None} for r in rows]

    def decide_learning(self,gateway,ident,spec_hash,decision,runtime_id):
        import time
        if decision not in ('approve_once','deny'):raise ValueError('Approve once or Deny required')
        gateway.require('read','desktop','desktop_operator')
        with gateway.db() as db:
            self._learning_schema(db);db.execute('BEGIN IMMEDIATE')
            row=db.execute('SELECT * FROM task_authorizations WHERE id=?',(ident,)).fetchone()
            if not row or row['state']!='pending' or row['expires']<=time.time():raise PermissionError('Proposal unavailable, expired or already decided')
            spec=json.loads(row['spec'])
            if row['spec_hash']!=spec_hash or self._learning_hash(spec)!=spec_hash or spec!=self.learning_spec(spec['topic'],spec['justification'],spec['source_path']):raise PermissionError('Learning scope changed; fresh approval required')
            state='approved' if decision=='approve_once' else 'denied'
            db.execute('UPDATE task_authorizations SET state=?,expires=?,runtime_id=? WHERE id=?',(state,time.time()+spec['limits']['wall_seconds'] if decision=='approve_once' else time.time(),runtime_id,ident))
            gateway.audit(db,'learning.'+state,ident,spec_hash=spec_hash,actor='desktop_operator')
        return spec

    def bind_learning(self,gateway,ident,runtime_id,token):
        import hashlib,time
        hashed=hashlib.sha256(token.encode()).hexdigest()
        with gateway.db() as db:
            db.execute('BEGIN IMMEDIATE')
            row=db.execute('SELECT * FROM task_authorizations WHERE id=?',(ident,)).fetchone()
            owner=db.execute('SELECT state,owner,token_hash FROM task_admission WHERE singleton=1').fetchone()
            if not row or row['state']!='approved' or row['runtime_id']!=runtime_id or row['expires']<=time.time():raise PermissionError('Task approval is invalid or consumed')
            if not owner or owner['state']!='active' or owner['owner']!='autonomous_step' or owner['token_hash']!=hashed:raise PermissionError('Original task ownership required')
            spec=json.loads(row['spec'])
            if self._learning_hash(spec)!=row['spec_hash']:raise PermissionError('Approved specification changed')
            db.execute("UPDATE task_authorizations SET state='running',token_hash=? WHERE id=?",(hashed,ident))
            gateway.audit(db,'learning.bound',ident,spec_hash=row['spec_hash'])
        return spec

    def authorize_learning_stage(self,gateway,ident,runtime_id,token,operation):
        import hashlib,time
        limits={'memory.recall':1,'workspace_read':1,'local_gguf':1,'self_teacher.review':1,'brain_trainer.source_observation':1,'memory.observation':1}
        hashed=hashlib.sha256(token.encode()).hexdigest()
        with gateway.db() as db:
            db.execute('BEGIN IMMEDIATE')
            row=db.execute('SELECT * FROM task_authorizations WHERE id=?',(ident,)).fetchone()
            owner=db.execute('SELECT state,owner,token_hash FROM task_admission WHERE singleton=1').fetchone()
            if not row or row['state']!='running' or row['runtime_id']!=runtime_id or row['token_hash']!=hashed or row['expires']<=time.time():raise PermissionError('Learning authorization revoked, expired or mismatched')
            if not owner or owner['state']!='active' or owner['owner']!='autonomous_step' or owner['token_hash']!=hashed:raise PermissionError('Learning task ownership lost')
            spec=json.loads(row['spec'])
            if self._learning_hash(spec)!=row['spec_hash']:raise PermissionError('Learning scope changed')
            if operation not in limits or operation not in spec['tools']:raise PermissionError('Tool outside approved task')
            usage=json.loads(row['usage']);usage[operation]=usage.get(operation,0)+1
            if usage[operation]>limits[operation]:raise PermissionError('Approved learning budget exhausted')
            db.execute('UPDATE task_authorizations SET usage=? WHERE id=?',(json.dumps(usage,sort_keys=True),ident))

    def finish_learning(self,gateway,ident,state,result=None):
        if state not in ('completed','failed','cancelled','expired','interrupted'):raise ValueError('Invalid terminal state')
        import time
        with gateway.db() as db:
            row=db.execute('SELECT expires FROM task_authorizations WHERE id=?',(ident,)).fetchone()
            if row and row['expires']<=time.time() and state in ('completed','failed'):state='expired'
            # Cancellation/denial wins over a late successful provider response.
            changed=db.execute("UPDATE task_authorizations SET state=?,result=? WHERE id=? AND state IN ('approved','running')",(state,json.dumps(result or {},default=str),ident)).rowcount
            if changed:gateway.audit(db,'learning.'+state,ident)
        return {'revoked':True,'state':state}

    def trading_schema(self, gateway, runtime_id):
        """Trading scopes use this permission manager and the canonical ledger.

        They never consult or change learning approvals or persistent permissions.
        """
        with gateway.db() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS trading_sessions(
                    id TEXT PRIMARY KEY,spec TEXT NOT NULL,spec_hash TEXT NOT NULL,
                    runtime_id TEXT NOT NULL,state TEXT NOT NULL,created REAL NOT NULL,
                    expires REAL NOT NULL,initial_equity REAL NOT NULL,peak_equity REAL NOT NULL,
                    entries INTEGER NOT NULL DEFAULT 0,reason TEXT);
                CREATE TABLE IF NOT EXISTS trading_control(
                    singleton INTEGER PRIMARY KEY CHECK(singleton=1),stopped INTEGER NOT NULL);
                INSERT OR IGNORE INTO trading_control VALUES(1,0);
            ''')
            db.execute("UPDATE trading_sessions SET state='interrupted',reason='Core restarted; activation required' WHERE runtime_id<>? AND state IN ('active','risk_halted','pending')", (runtime_id,))

    def propose_trading(self, gateway, spec, runtime_id, equity):
        import time, uuid
        gateway.require('read','desktop','desktop_operator')
        gateway.require('ingest','desktop','desktop_operator')
        if spec.get('environment') not in ('demo','dry-run','simulation') or spec.get('live_money') is not False:raise PermissionError('Real-money trading scopes are disabled')
        fingerprint=self._learning_hash(spec)
        ident=uuid.uuid4().hex
        with gateway.db() as db:
            db.execute('INSERT INTO trading_sessions VALUES(?,?,?,?,?,?,?,?,?,?,?)',
                (ident,json.dumps(spec,sort_keys=True,allow_nan=False),fingerprint,runtime_id,
                 'pending',time.time(),time.time()+300,equity,equity,0,None))
            gateway.audit(db,'trading.proposed',ident,spec_hash=fingerprint)
        return ident

    def activate_trading(self, gateway, ident, fingerprint, runtime_id, *, clear_stop=False):
        import time
        gateway.require('ingest','desktop','desktop_operator')
        with gateway.db() as db:
            db.execute('BEGIN IMMEDIATE')
            row=db.execute('SELECT * FROM trading_sessions WHERE id=?',(ident,)).fetchone()
            if not row or row['runtime_id']!=runtime_id or row['state']!='pending' or row['expires']<=time.time():
                raise PermissionError('Trading proposal expired, interrupted or already decided')
            spec=json.loads(row['spec'])
            if spec.get('environment') not in ('demo','dry-run','simulation') or spec.get('live_money') is not False:raise PermissionError('Real-money trading scopes are disabled')
            if row['spec_hash']!=fingerprint or self._learning_hash(spec)!=fingerprint:
                raise PermissionError('Trading scope changed; review a fresh proposal')
            if db.execute("SELECT 1 FROM trading_sessions WHERE state IN ('active','risk_halted') AND json_extract(spec,'$.adapter')=? AND json_extract(spec,'$.account')=? AND expires>?",(spec['adapter'],spec['account'],time.time())).fetchone():
                raise PermissionError('An account session is already active')
            stopped=db.execute('SELECT stopped FROM trading_control WHERE singleton=1').fetchone()[0]
            if stopped and not clear_stop:raise PermissionError('Emergency stop latched; explicit reset and activation required')
            if clear_stop:db.execute('UPDATE trading_control SET stopped=0 WHERE singleton=1')
            db.execute("UPDATE trading_sessions SET state='active',expires=?,reason=NULL WHERE id=?",
                       (time.time()+spec['seconds'],ident))
            gateway.audit(db,'trading.activated',ident,spec_hash=fingerprint,actor='desktop_operator')
        return spec

    def check_trading(self, gateway, ident, runtime_id, token, action, *, consume=False, db=None, token_hash=None, claimed_receipt=False):
        import time,hashlib
        from contextlib import nullcontext
        if action not in ('open','close'):raise PermissionError('Operation outside trading scope')
        gateway.require('ingest','desktop','desktop_operator')
        with (gateway.db() if db is None else nullcontext(db)) as conn:
            row=conn.execute('SELECT * FROM trading_sessions WHERE id=?',(ident,)).fetchone()
            if not row or row['runtime_id']!=runtime_id or row['expires']<=time.time():raise PermissionError('Trading session expired or interrupted')
            if row['state'] not in (('active',) if action=='open' else ('active','risk_halted')):
                raise PermissionError('Trading session stopped or risk halted')
            if conn.execute('SELECT stopped FROM trading_control WHERE singleton=1').fetchone()[0]:raise PermissionError('Emergency stop latched')
            owner=conn.execute('SELECT state,owner,token_hash FROM trading_admission WHERE singleton=1').fetchone()
            if not owner or owner['state']!='active' or owner['owner']!='trading_cycle' or owner['token_hash']!=(token_hash or hashlib.sha256(token.encode()).hexdigest()):
                raise PermissionError('Original Core trading-cycle admission required')
            spec=json.loads(row['spec'])
            if self._learning_hash(spec)!=row['spec_hash']:raise PermissionError('Trading scope changed')
            if action not in spec.get('position_actions', ('open','close')):
                raise PermissionError('Action outside approved position scope')
            if action=='open' and not claimed_receipt and row['entries']>=spec['limits']['max_entries']:raise PermissionError('Session entry limit reached')
            if consume and action=='open':conn.execute('UPDATE trading_sessions SET entries=entries+1 WHERE id=?',(ident,))
        return spec

    def stop_trading(self,gateway,ident=None,*,emergency=False,reason='Operator stopped session'):
        with gateway.db() as db:
            db.execute('BEGIN IMMEDIATE')
            if emergency:db.execute('UPDATE trading_control SET stopped=1 WHERE singleton=1')
            if ident is None:
                db.execute("UPDATE trading_sessions SET state='stopped',reason=? WHERE state IN ('active','risk_halted','pending')",(reason,))
            else:db.execute("UPDATE trading_sessions SET state='stopped',reason=? WHERE id=?",(reason,ident))
            gateway.audit(db,'trading.emergency_stop' if emergency else 'trading.stopped',ident or 'all')


if __name__ == "__main__":
    print('Running permission_manager.py')
