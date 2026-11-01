import pytest
from fastapi.testclient import TestClient
from modules.server_manager import ServerManager,create_app


def test_private_isolation_tiers_and_team_revocation(tmp_path):
    seen=[]
    def reply(history,text):
        seen.append([x['content'] for x in history]);return 'reply '+text
    manager=ServerManager(tmp_path/'portal.sqlite',responder=reply)
    for name,role in [('owner','admin'),('alice','viewer'),('bobby','operator'),('carol','viewer')]:
        manager.add_user(name,'long-test-password',role)
    app=create_app(manager,'http://testserver')
    def client(name):
        c=TestClient(app);r=c.post('/api/login',json={'username':name,'password':'long-test-password'},headers={'Origin':'http://testserver'})
        return c,{'Origin':'http://testserver','X-CSRF-Token':r.json()['csrf']}
    owner,oh=client('owner');alice,ah=client('alice');bob,bh=client('bobby');carol,ch=client('carol')
    assert alice.post('/api/workspaces',json={'title':'Private'},headers=ah).status_code==403
    assert alice.post('/api/admin/plan/alice',json={'tier':'team'},headers=ah).status_code==403
    assert owner.post('/api/admin/plan/alice',json={'tier':'personal'},headers=oh).status_code==200
    wid=alice.post('/api/workspaces',json={'title':'Private'},headers=ah).json()['id']
    assert alice.post('/api/workspaces',json={'title':'Second'},headers=ah).status_code==403
    assert alice.post('/api/messages',json={'content':'PRIVATE ALICE','workspace':wid},headers=ah).status_code==200
    for c in [owner,bob,carol]:
        assert c.get('/api/session?workspace='+wid).status_code==404
        assert 'PRIVATE ALICE' not in c.get('/api/session').text
    assert bob.post('/api/messages',json={'content':'Shared'},headers=bh).status_code==200
    assert seen[-1]==[]  # Private content never entered shared model context.
    assert alice.post('/api/workspaces/'+wid+'/members',json={'username':'bobby','role':'operator'},headers=ah).status_code==403
    assert owner.post('/api/admin/plan/alice',json={'tier':'team'},headers=oh).status_code==200
    assert alice.post('/api/workspaces/'+wid+'/members',json={'username':'bobby','role':'viewer'},headers=ah).status_code==200
    assert 'PRIVATE ALICE' in bob.get('/api/session?workspace='+wid).text
    assert bob.post('/api/messages',json={'content':'denied','workspace':wid},headers=bh).status_code==403
    assert alice.post('/api/workspaces/'+wid+'/members',json={'username':'bobby','role':'operator'},headers=ah).status_code==200
    assert bob.post('/api/messages',json={'content':'Team message','workspace':wid},headers=bh).status_code==200
    assert owner.post('/api/admin/plan/alice',json={'tier':'personal'},headers=oh).status_code==409
    assert alice.post('/api/workspaces/'+wid+'/members',json={'username':'bobby','role':None},headers=ah).status_code==200
    assert bob.get('/api/session?workspace='+wid).status_code==404
    assert bob.post('/api/messages',json={'content':'denied','workspace':wid},headers=bh).status_code==404
    assert manager.history()==manager.history('shared')


def test_daily_limit_and_migration_preserves_shared_history(tmp_path):
    import sqlite3,time
    path=tmp_path/'old.sqlite'
    with sqlite3.connect(path) as db:
        db.execute('CREATE TABLE messages(id INTEGER PRIMARY KEY,name TEXT,role TEXT,content TEXT,state TEXT,created REAL)')
        db.execute("INSERT INTO messages VALUES(1,'old','user','existing history','complete',0)")
    m=ServerManager(path,responder=lambda h,c:'ok')
    assert m.history()[0]['content']=='existing history'
    m.add_user('alice','long-test-password','viewer')
    user={'name':'alice','role':'viewer'}
    m.workspaces.set_plan({'name':'admin'},'alice','personal')
    wid=m.workspaces.create(user,'Private')['id']
    assert m.history(wid)==[]
    with m.db() as db:db.execute('INSERT INTO usage VALUES(?,?,?)',('alice',int(time.time()//86400),50))
    with pytest.raises(Exception) as e:m.submit(user,'blocked',wid)
    assert e.value.status_code==429
    assert m.history(wid)==[]


def test_team_seats_and_pro_workspace_caps(tmp_path):
    m=ServerManager(tmp_path/'portal.sqlite')
    for name in ['owner','guest1','guest2','guest3','guest4','guest5']:
        m.add_user(name,'long-test-password','viewer')
    owner={'name':'owner','role':'viewer'}
    m.workspaces.set_plan({'name':'admin'},'owner','pro')
    for i in range(3):m.workspaces.create(owner,'Workspace '+str(i))
    with pytest.raises(Exception) as e:m.workspaces.create(owner,'Too many')
    assert e.value.status_code==403
    m.workspaces.set_plan({'name':'admin'},'owner','team')
    wid=m.workspaces.list(owner)[1]['id']
    for i in range(1,5):m.workspaces.member(owner,wid,'guest'+str(i),'viewer')
    with pytest.raises(Exception) as e:m.workspaces.member(owner,wid,'guest5','viewer')
    assert e.value.status_code==403
    m.workspaces.member(owner,wid,'guest4',None)
    m.workspaces.member(owner,wid,'guest5','operator')
    assert m.workspaces.access({'name':'guest5','role':'viewer'},wid,True)=='operator'
