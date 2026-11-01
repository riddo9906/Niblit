"""Invite-only shared Niblit workspace, separate from desktop Core authority.

Owner-only bounded research tools are opt-in per turn. No desktop authority,
private Core memory, paid providers or broker actions are exposed here.
Deploy behind TLS; the default listener is loopback only.
"""
import hashlib
import hmac
import secrets
import re
import sqlite3
import threading
import time
import os
from contextlib import contextmanager
from pathlib import Path

import httpx
from modules.task_admission import task_owned, AdmissionBusy
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

ROOT = Path(__file__).resolve().parents[1]


class Login(BaseModel):
    username: str = Field(min_length=1, max_length=80)
    password: str = Field(min_length=1, max_length=256)


class Account(Login):
    role: str = 'viewer'


class Signup(Login):
    shared_workspace_acknowledged: bool


class Message(BaseModel):
    content: str = Field(min_length=1, max_length=4000)
    workspace: str = Field(default='shared',max_length=80)
    use_tools: bool = False


class WorkspaceTitle(BaseModel):
    title: str = Field(min_length=1,max_length=80)


class Plan(BaseModel):
    tier: str


class Member(BaseModel):
    username: str = Field(min_length=3,max_length=80)
    role: str | None = None


class ServerManager:
    def __init__(self, path, responder=None):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.turn_lock = threading.Lock()
        self.last_activity = time.monotonic()
        self.responder = responder
        with self.db() as db:
            db.executescript('''
            CREATE TABLE IF NOT EXISTS users(name TEXT PRIMARY KEY,salt TEXT,hash TEXT,role TEXT,active INTEGER);
            CREATE TABLE IF NOT EXISTS logins(token TEXT PRIMARY KEY,name TEXT,csrf TEXT,expires REAL);
            CREATE TABLE IF NOT EXISTS messages(id INTEGER PRIMARY KEY,name TEXT,role TEXT,content TEXT,state TEXT,created REAL);
            CREATE TABLE IF NOT EXISTS audit(id INTEGER PRIMARY KEY,name TEXT,action TEXT,created REAL);
            CREATE TABLE IF NOT EXISTS attempts(name TEXT PRIMARY KEY,count INTEGER,until REAL);
            CREATE TABLE IF NOT EXISTS signups(name TEXT PRIMARY KEY,created REAL,state TEXT);
            ''')
            # Never retry model work after a process interruption.
            db.execute("UPDATE messages SET state='interrupted' WHERE state='pending'")
        from modules.portal_workspaces import Workspaces
        self.workspaces=Workspaces(self)
        from modules.portal_tools import initialize
        initialize(self)
        from modules.portal_learning import LocalTutor
        self.tutor=LocalTutor(self)

    @contextmanager
    def db(self):
        db = sqlite3.connect(self.path, timeout=15)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    @staticmethod
    def password(password, salt):
        return hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), n=16384, r=8, p=1).hex()

    def add_user(self, name, password, role, *, pending=False):
        if role not in ('admin', 'operator', 'viewer') or len(password) < 12 or not re.fullmatch(r'[A-Za-z0-9_.-]{3,80}',name):
            raise ValueError('Use a unique username, a password of at least 12 characters and a valid role')
        salt = secrets.token_hex(16)
        with self.db() as db:
            db.execute('INSERT INTO users VALUES(?,?,?,?,?)', (name, salt, self.password(password, salt), role,0 if pending else 1))
            if pending:
                db.execute("INSERT INTO signups VALUES(?,?,'pending')",(name,time.time()))
                db.execute('INSERT INTO audit(name,action,created) VALUES(?,?,?)',(name,'signup.requested',time.time()))

    def login(self, name, password):
        with self.db() as db:
            blocked = db.execute('SELECT * FROM attempts WHERE name=?', (name,)).fetchone()
            if blocked and blocked['count'] >= 5 and blocked['until'] > time.time():
                raise HTTPException(429, 'Please wait before trying again')
            user = db.execute('SELECT * FROM users WHERE name=? AND active=1', (name,)).fetchone()
            salt = user['salt'] if user else '00' * 16
            actual = self.password(password, salt)
            if not user or not hmac.compare_digest(actual, user['hash']):
                db.execute('INSERT INTO attempts VALUES(?,1,?) ON CONFLICT(name) DO UPDATE SET count=CASE WHEN until < ? THEN 1 ELSE count+1 END, until=?', (name,time.time()+300,time.time(),time.time()+300))
                result = None
            else:
                db.execute('DELETE FROM attempts WHERE name=?', (name,))
                token, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
                db.execute('INSERT INTO logins VALUES(?,?,?,?)', (hashlib.sha256(token.encode()).hexdigest(),name,csrf,time.time()+28800))
                db.execute('INSERT INTO audit(name,action,created) VALUES(?,?,?)', (name,'login',time.time()))
                result = token, csrf
        if result is None:
            raise HTTPException(401, 'Invalid login')
        return result

    def identity(self, token):
        with self.db() as db:
            row = db.execute('SELECT u.name,u.role,l.csrf FROM logins l JOIN users u ON u.name=l.name WHERE l.token=? AND l.expires>? AND u.active=1', (hashlib.sha256(token.encode()).hexdigest(),time.time())).fetchone()
        if not row:
            raise HTTPException(401, 'Please log in')
        return dict(row)

    def history(self, workspace='shared'):
        with self.db() as db:
            return [dict(r) for r in db.execute('SELECT * FROM (SELECT * FROM messages WHERE workspace=? ORDER BY id DESC LIMIT 100) ORDER BY id',(workspace,))]

    def submit(self, user, content, workspace='shared', use_tools=False):
        self.last_activity=time.monotonic()
        self.workspaces.access(user,workspace,write=True)
        if use_tools and user['role']!='admin':
            raise HTTPException(403, 'Research tools are administrator-only')
        if not self.turn_lock.acquire(blocking=False):
            raise HTTPException(409, 'Niblit is answering another participant; try again shortly')
        try:
            self.workspaces.reserve_turn(user,workspace)
            with self.db() as db:
                cursor = db.execute('INSERT INTO messages(name,role,content,state,created,workspace) VALUES(?,?,?,?,?,?)',(user['name'],'user',content,'pending',time.time(),workspace))
                message_id = cursor.lastrowid
                db.execute('INSERT INTO audit(name,action,created) VALUES(?,?,?)',(user['name'],'message.submit',time.time()))
            try:
                return self._complete_turn(user,content,workspace,use_tools,message_id)
            except AdmissionBusy as exc:
                with self.db() as db:db.execute("UPDATE messages SET state='failed' WHERE id=?",(message_id,))
                raise HTTPException(409,str(exc))
            except (httpx.HTTPError,OSError) as exc:
                with self.db() as db:db.execute("UPDATE messages SET state='failed' WHERE id=?",(message_id,))
                raise HTTPException(503,'Shared runtime authority unavailable; no automatic retry') from exc
        finally:
            self.last_activity=time.monotonic()
            self.turn_lock.release()

    @task_owned('portal_chat')
    def _complete_turn(self,user,content,workspace,use_tools,message_id):
        try:
            history = [m for m in self.history(workspace) if m['state']=='complete'][-12:]
            if use_tools:
                from modules.portal_tools import ResearchTools
                from modules.portal_model import reply
                answer=reply(history,content,tools=ResearchTools(self,user,workspace,message_id))
            else:
                answer = self.responder(history, content) if self.responder else self.local_reply(history, content)
            if not isinstance(answer,str) or not answer.strip():
                raise ValueError('Empty response')
        except Exception:
            with self.db() as db:
                db.execute("UPDATE messages SET state='failed' WHERE id=?",(message_id,))
            raise HTTPException(503, 'Local model unavailable. Your request was recorded, and was not retried.')
        with self.db() as db:
            db.execute("UPDATE messages SET state='complete' WHERE id=?",(message_id,))
            db.execute('INSERT INTO messages(name,role,content,state,created,workspace) VALUES(?,?,?,?,?,?)',('Niblit','assistant',answer[:16000],'complete',time.time(),workspace))
        self.workspaces.access(user,workspace)
        return {'ok':True}

    @staticmethod
    def local_reply(history, content):
        # Direct Ollama loopback connection cannot fall back to a paid cloud provider.
        from modules.portal_model import reply
        return reply(history,content)


def create_app(manager=None, origin='http://127.0.0.1:8768'):
    manager = manager or ServerManager(ROOT/'runtime/client-portal/session.sqlite3')
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    secure = origin.startswith('https://')
    from modules.portal_remote import remote_origin,client_path
    from urllib.parse import urlsplit
    remote=remote_origin(os.environ.get('NIBLIT_PORTAL_REMOTE_ORIGIN',''))

    @app.middleware('http')
    async def boundary(request, call_next):
        from urllib.parse import urlsplit
        request.state.remote_client=bool(remote and request.headers.get('host')==urlsplit(remote).netloc)
        expected=remote if request.state.remote_client else origin
        if request.headers.get('host') != urlsplit(expected).netloc:
            return __import__('starlette.responses',fromlist=['JSONResponse']).JSONResponse({'detail':'Invalid host'},status_code=400)
        if request.state.remote_client and not client_path(request.url.path):
            return __import__('starlette.responses',fromlist=['JSONResponse']).JSONResponse({'detail':'Local owner capability is not exposed remotely'},status_code=403)
        if request.method not in ('GET','HEAD') and request.headers.get('origin') != expected:
            return __import__('starlette.responses',fromlist=['JSONResponse']).JSONResponse({'detail':'Invalid origin'},status_code=403)
        response = await call_next(request)
        response.headers['Cache-Control']='no-store'
        response.headers['X-Content-Type-Options']='nosniff'
        response.headers['Content-Security-Policy']="default-src 'self'; script-src 'self'; style-src 'self'; frame-ancestors 'none'; base-uri 'none'"
        return response

    def auth(request, write=False, admin=False):
        user=manager.identity(request.cookies.get('niblit_session',''))
        if write and not hmac.compare_digest(request.headers.get('x-csrf-token',''),user['csrf']):
            raise HTTPException(403,'Invalid request token')
        if admin and user['role']!='admin':
            raise HTTPException(403,'Administrator required')
        return user

    @app.get('/api/health')
    def health():
        with manager.db() as db:
            db.execute('SELECT 1').fetchone()
        return {'status':'ok','storage':'available','model_status':'not_checked'}

    @app.get('/api/model-status')
    def model_status(request:Request):
        auth(request)
        from modules.portal_model import readiness
        return readiness()

    @app.get('/')
    def home():
        return FileResponse(ROOT/'assets/client-portal/index.html')

    @app.get('/admin')
    def admin_page():
        # The shell is public; every administrator data/action route still
        # requires the authenticated admin role and mutation CSRF checks.
        return FileResponse(ROOT/'assets/client-portal/index.html')

    @app.get('/portal.js')
    def script():
        return FileResponse(ROOT/'assets/client-portal/portal.js',media_type='text/javascript')

    @app.get('/portal.css')
    def stylesheet():
        return FileResponse(ROOT/'assets/client-portal/portal.css',media_type='text/css')

    @app.post('/api/login')
    def login(body:Login,request:Request):
        from fastapi.responses import JSONResponse
        token,csrf=manager.login(body.username,body.password)
        response=JSONResponse({'csrf':csrf})
        response.set_cookie('niblit_session',token,httponly=True,secure=secure or request.state.remote_client,samesite='strict',max_age=28800)
        return response

    @app.post('/api/signup',status_code=202)
    def signup(body:Signup):
        if not body.shared_workspace_acknowledged:
            raise HTTPException(400,'Please acknowledge the shared workspace')
        # A bounded pending queue prevents unbounded account creation. A production
        # proxy must also rate limit this route before password hashing is performed.
        with manager.db() as db:
            count=db.execute("SELECT COUNT(*) FROM signups WHERE state='pending'").fetchone()[0]
        if count>=100:
            raise HTTPException(429,'Registration queue is full; contact the administrator')
        try:
            manager.add_user(body.username,body.password,'viewer',pending=True)
        except ValueError:
            raise HTTPException(400,'Use 3–80 letters, numbers, dots, hyphens or underscores and a password of at least 12 characters')
        except sqlite3.IntegrityError:
            # Same response for existing and new users: never reset a password or
            # reactivate a revoked account through public registration.
            pass
        return {'message':'If this username is available, your request is awaiting administrator approval. No workspace access has been granted.'}

    @app.get('/api/session')
    def session(request:Request,workspace:str='shared'):
        user=auth(request)
        role=manager.workspaces.access(user,workspace)
        return {'remote_client':request.state.remote_client,'user':user,'session':workspace,'namespace':'client:'+workspace,'workspace_role':role,'tier':manager.workspaces.tier(user['name']),'workspaces':manager.workspaces.list(user),'messages':manager.history(workspace)}

    @app.post('/api/messages')
    def message(body:Message,request:Request):
        if request.state.remote_client and body.use_tools:
            raise HTTPException(403,'Owner research tools are local only')
        return manager.submit(auth(request,write=True),body.content,body.workspace,body.use_tools)

    @app.get('/api/tool-activity')
    def tool_activity(request:Request,workspace:str='shared'):
        user=auth(request)
        if user['role']!='admin': raise HTTPException(403,'Administrator access required')
        manager.workspaces.access(user,workspace)
        with manager.db() as db:
            events=[dict(r) for r in db.execute('SELECT * FROM tool_events WHERE workspace=? ORDER BY id DESC LIMIT 30',(workspace,))]
            proposals=[dict(r) for r in db.execute('SELECT * FROM improvement_proposals WHERE workspace=? ORDER BY id DESC LIMIT 10',(workspace,))]
        return {'events':events,'proposals':proposals,'policy':'Owner research only; no automatic application, shell, trades or paid inference'}

    def owner(request,write=False):
        user=auth(request,write=write)
        if user['role']!='admin': raise HTTPException(403,'Administrator access required')
        return user

    @app.get('/api/learning')
    def learning_status(request:Request):
        return manager.tutor.status(owner(request)['name'])

    @app.post('/api/learning/start')
    def learning_start(request:Request):
        user=owner(request,True)
        try:return manager.tutor.start(user['name'])
        except ValueError as exc:raise HTTPException(409,str(exc))

    @app.post('/api/learning/stop')
    def learning_stop(request:Request):
        user=owner(request,True);manager.tutor.stop()
        return manager.tutor.status(user['name'])

    @app.get('/api/plans')
    def plans():
        from modules.portal_workspaces import TIERS
        return {'tiers':TIERS,'billing':'Not connected. Pilot tiers are assigned by the administrator.'}

    @app.post('/api/workspaces')
    def workspace_create(body:WorkspaceTitle,request:Request):
        return manager.workspaces.create(auth(request,write=True),body.title)

    @app.post('/api/workspaces/{wid}/members')
    def workspace_member(wid:str,body:Member,request:Request):
        manager.workspaces.member(auth(request,write=True),wid,body.username,body.role)
        return {'ok':True}

    @app.get('/api/workspaces/{wid}/members')
    def workspace_members(wid:str,request:Request):
        user=auth(request)
        if manager.workspaces.access(user,wid)!='owner':
            raise HTTPException(403,'Workspace owner required')
        with manager.db() as db:
            return {'members':[dict(r) for r in db.execute('SELECT name,role FROM members WHERE workspace=?',(wid,))]}

    @app.post('/api/admin/plan/{name}')
    def assign_plan(name:str,body:Plan,request:Request):
        manager.workspaces.set_plan(auth(request,write=True,admin=True),name,body.tier)
        return {'ok':True}

    @app.post('/api/logout')
    def logout(request:Request):
        auth(request,write=True)
        with manager.db() as db:
            db.execute('DELETE FROM logins WHERE token=?',(hashlib.sha256(request.cookies['niblit_session'].encode()).hexdigest(),))
        return {'ok':True}

    @app.get('/api/admin')
    def admin(request:Request):
        auth(request,admin=True)
        with manager.db() as db:
            return {'users':[dict(r) for r in db.execute("SELECT u.name,u.role,u.active,s.state AS signup_state,COALESCE(p.tier,'community') AS tier FROM users u LEFT JOIN signups s ON s.name=u.name LEFT JOIN plans p ON p.name=u.name")], 'audit':[dict(r) for r in db.execute('SELECT * FROM audit ORDER BY id DESC LIMIT 100')]}

    @app.post('/api/admin/approve/{name}')
    def approve(name:str,request:Request):
        user=auth(request,write=True,admin=True)
        with manager.db() as db:
            changed=db.execute("UPDATE signups SET state='approved' WHERE name=? AND state='pending'",(name,)).rowcount
            if not changed:
                raise HTTPException(400,'No pending registration found')
            db.execute("UPDATE users SET active=1,role='viewer' WHERE name=?",(name,))
            db.execute('INSERT INTO audit(name,action,created) VALUES(?,?,?)',(user['name'],'signup.approved:'+name,time.time()))
        return {'ok':True}

    @app.post('/api/admin/users')
    def add_user(body:Account,request:Request):
        user=auth(request,write=True,admin=True)
        try:
            manager.add_user(body.username,body.password,body.role)
        except (ValueError,sqlite3.IntegrityError):
            raise HTTPException(400,'Invalid account or username already exists')
        with manager.db() as db:
            db.execute('INSERT INTO audit(name,action,created) VALUES(?,?,?)',(user['name'],'account.created:'+body.username,time.time()))
        return {'ok':True}

    @app.post('/api/admin/revoke/{name}')
    def revoke(name:str,request:Request):
        user=auth(request,write=True,admin=True)
        if name==user['name']:
            raise HTTPException(400,'Cannot revoke your own administrator account')
        with manager.db() as db:
            db.execute('UPDATE users SET active=0 WHERE name=?',(name,))
            db.execute("UPDATE signups SET state='revoked' WHERE name=?",(name,))
            db.execute('DELETE FROM logins WHERE name=?',(name,))
            db.execute('INSERT INTO audit(name,action,created) VALUES(?,?,?)',(user['name'],'account.revoked:'+name,time.time()))
        return {'ok':True}
    return app
