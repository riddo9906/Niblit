"""Server-enforced workspace membership and manually assigned pilot entitlements.

Private means isolated from other clients, not encrypted from the server owner.
No payment processor, model tools or private desktop namespace is connected.
"""
import secrets
import time
from fastapi import HTTPException

TIERS = {
    'community': {'workspaces':0,'seats':0,'daily_turns':0},
    'personal': {'workspaces':1,'seats':1,'daily_turns':50},
    'pro': {'workspaces':3,'seats':1,'daily_turns':250},
    'team': {'workspaces':5,'seats':5,'daily_turns':500},
}


class Workspaces:
    def __init__(self, manager):
        self.manager=manager
        with manager.db() as db:
            db.executescript('''
            CREATE TABLE IF NOT EXISTS plans(name TEXT PRIMARY KEY,tier TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS workspaces(id TEXT PRIMARY KEY,owner TEXT NOT NULL,title TEXT NOT NULL,created REAL);
            CREATE TABLE IF NOT EXISTS members(workspace TEXT,name TEXT,role TEXT,PRIMARY KEY(workspace,name));
            CREATE TABLE IF NOT EXISTS usage(owner TEXT,day INTEGER,turns INTEGER,PRIMARY KEY(owner,day));
            ''')
            if 'workspace' not in [r['name'] for r in db.execute('PRAGMA table_info(messages)')]:
                db.execute("ALTER TABLE messages ADD COLUMN workspace TEXT NOT NULL DEFAULT 'shared'")
            db.execute('CREATE INDEX IF NOT EXISTS messages_workspace ON messages(workspace,id)')

    def tier(self,name):
        with self.manager.db() as db:
            row=db.execute('SELECT tier FROM plans WHERE name=?',(name,)).fetchone()
        return row['tier'] if row else 'community'

    def access(self,user,workspace,write=False):
        # Recheck activity on every operation, including after model completion.
        with self.manager.db() as db:
            active=db.execute('SELECT role FROM users WHERE name=? AND active=1',(user['name'],)).fetchone()
            if not active:
                raise HTTPException(401,'Please log in')
            if workspace=='shared':
                role=active['role']
            else:
                member=db.execute('SELECT role FROM members WHERE workspace=? AND name=?',(workspace,user['name'])).fetchone()
                if not member:
                    raise HTTPException(404,'Workspace not found')
                role=member['role']
        if write and role not in ('owner','operator','admin'):
            raise HTTPException(403,'A viewer can read this workspace')
        return role

    def list(self,user):
        with self.manager.db() as db:
            rows=[dict(r) for r in db.execute('SELECT w.id,w.title,w.owner,m.role FROM workspaces w JOIN members m ON m.workspace=w.id WHERE m.name=? ORDER BY w.created',(user['name'],))]
        return [{'id':'shared','title':'Shared Niblit workspace','owner':None,'role':user['role']},*rows]

    def create(self,user,title):
        tier=self.tier(user['name'])
        limit=TIERS[tier]['workspaces']
        if not title.strip() or len(title)>80:
            raise HTTPException(400,'Use a workspace name of 1–80 characters')
        with self.manager.db() as db:
            db.execute('BEGIN IMMEDIATE')
            count=db.execute('SELECT COUNT(*) FROM workspaces WHERE owner=?',(user['name'],)).fetchone()[0]
            if count>=limit:
                raise HTTPException(403,'Your assigned tier has no remaining private workspaces')
            wid=secrets.token_urlsafe(24)
            db.execute('INSERT INTO workspaces VALUES(?,?,?,?)',(wid,user['name'],title.strip(),time.time()))
            db.execute("INSERT INTO members VALUES(?,?,'owner')",(wid,user['name']))
            db.execute('INSERT INTO audit(name,action,created) VALUES(?,?,?)',(user['name'],'workspace.created:'+wid,time.time()))
        return {'id':wid}

    def set_plan(self,admin,name,tier):
        if tier not in TIERS:
            raise HTTPException(400,'Unknown tier')
        with self.manager.db() as db:
            if not db.execute('SELECT 1 FROM users WHERE name=?',(name,)).fetchone():
                raise HTTPException(404,'Account not found')
            # Downgrades must not silently strand workspaces or revoke members.
            count=db.execute('SELECT COUNT(*) FROM workspaces WHERE owner=?',(name,)).fetchone()[0]
            seats=db.execute('SELECT MAX(n) FROM (SELECT COUNT(*) n FROM members m JOIN workspaces w ON w.id=m.workspace WHERE w.owner=? GROUP BY m.workspace)',(name,)).fetchone()[0] or 0
            if count>TIERS[tier]['workspaces'] or seats>TIERS[tier]['seats']:
                raise HTTPException(409,'Current workspace or seat usage exceeds this tier')
            db.execute('INSERT INTO plans VALUES(?,?) ON CONFLICT(name) DO UPDATE SET tier=excluded.tier',(name,tier))
            db.execute('INSERT INTO audit(name,action,created) VALUES(?,?,?)',(admin['name'],'tier.assigned:'+name+':'+tier,time.time()))

    def member(self,user,wid,name,role=None):
        if self.access(user,wid)!='owner' or wid=='shared':
            raise HTTPException(403,'Workspace owner required')
        if name==user['name']:
            raise HTTPException(400,'Cannot remove or change the workspace owner')
        if role not in (None,'operator','viewer'):
            raise HTTPException(400,'Invalid member role')
        with self.manager.db() as db:
            db.execute('BEGIN IMMEDIATE')
            if role is None:
                db.execute('DELETE FROM members WHERE workspace=? AND name=?',(wid,name))
            else:
                if self.tier(user['name'])!='team':
                    raise HTTPException(403,'Team tier is required for invited members')
                if not db.execute('SELECT 1 FROM users WHERE name=? AND active=1',(name,)).fetchone():
                    raise HTTPException(404,'Approved account not found')
                count=db.execute('SELECT COUNT(*) FROM members WHERE workspace=?',(wid,)).fetchone()[0]
                exists=db.execute('SELECT 1 FROM members WHERE workspace=? AND name=?',(wid,name)).fetchone()
                if not exists and count>=TIERS['team']['seats']:
                    raise HTTPException(403,'Workspace seat limit reached')
                db.execute('INSERT INTO members VALUES(?,?,?) ON CONFLICT(workspace,name) DO UPDATE SET role=excluded.role',(wid,name,role))
            db.execute('INSERT INTO audit(name,action,created) VALUES(?,?,?)',(user['name'],'workspace.member.changed:'+wid+':'+name,time.time()))

    def reserve_turn(self,user,wid):
        self.access(user,wid,write=True)
        if wid=='shared':
            return
        with self.manager.db() as db:
            db.execute('BEGIN IMMEDIATE')
            owner=db.execute('SELECT owner FROM workspaces WHERE id=?',(wid,)).fetchone()['owner']
            plan=db.execute('SELECT tier FROM plans WHERE name=?',(owner,)).fetchone()
            limit=TIERS[plan['tier'] if plan else 'community']['daily_turns']
            day=int(time.time()//86400)
            row=db.execute('SELECT turns FROM usage WHERE owner=? AND day=?',(owner,day)).fetchone()
            if (row['turns'] if row else 0)>=limit:
                raise HTTPException(429,'Private workspace daily request limit reached (resets at 00:00 UTC)')
            db.execute('INSERT INTO usage VALUES(?,?,1) ON CONFLICT(owner,day) DO UPDATE SET turns=turns+1',(owner,day))
