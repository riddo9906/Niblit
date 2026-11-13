"""NUCM-2 logical episodes over the existing canonical ledger and durable outbox.

No execution intentions are restored. Qdrant remains an optional projection.
"""
from datetime import datetime,timezone
import json
import re
from .gateway import digest
from .runtime import SECRET


KINDS={'observation','hypothesis','prediction','simulation','broker_outcome','limitation'}
LOGICAL={'working','episodic','semantic','procedural','temporal','graph','metacognitive'}


def timestamp(value):
    if not isinstance(value,str):raise ValueError('Timezone-aware timestamp required')
    stamp=datetime.fromisoformat(value.replace('Z','+00:00'))
    if stamp.tzinfo is None:raise ValueError('Timezone-aware timestamp required')
    return stamp.astimezone(timezone.utc).isoformat()


class CognitiveMemory:
    def __init__(self,runtime):
        self.runtime=runtime;self.gateway=runtime.gateway;self.scope=dict(runtime.scope)
        with self.gateway.db() as db:
            db.executescript('''CREATE TABLE IF NOT EXISTS cognitive_episodes_v2(
                id TEXT PRIMARY KEY,namespace TEXT NOT NULL,principal TEXT NOT NULL,
                domain TEXT NOT NULL,observed_at TEXT NOT NULL,available_at TEXT NOT NULL,
                payload TEXT NOT NULL,outbox_id TEXT NOT NULL);
                CREATE INDEX IF NOT EXISTS cognitive_scope_time_v2
                ON cognitive_episodes_v2(namespace,principal,domain,available_at);''')

    def record(self, *, domain, event_id, source, observed_at, available_at, content,
               kind='observation',logical_type='episodic',support=(),contradict=(),
               valid_until=None,rule_version='1'):
        self.gateway.require('ingest',**self.scope)
        if (kind not in KINDS or logical_type not in LOGICAL or not isinstance(domain,str)
                or not domain.isidentifier() or not all(isinstance(v,str) and 0<len(v)<=512 for v in (event_id,source,rule_version))
                or not isinstance(content,str) or not 0<len(content)<=12000):
            raise ValueError('Invalid bounded cognitive episode')
        observed_at=timestamp(observed_at);available_at=timestamp(available_at)
        valid_until=timestamp(valid_until) if valid_until else None
        if observed_at>available_at or (valid_until and valid_until<observed_at):
            raise ValueError('Invalid temporal interval')
        links={name:sorted(set(values)) for name,values in (('support',support),('contradict',contradict))}
        if any(len(v)>64 or any(not isinstance(i,str) or len(i)>128 for i in v) for v in links.values()):
            raise ValueError('Invalid evidence links')
        key=digest(json.dumps([self.scope,domain,source,event_id],sort_keys=True))
        payload={'schema_version':'nucm/2','id':key,'domain':domain,'event_id':event_id,
            'source':source,'observed_at':observed_at,'available_at':available_at,
            'valid_until':valid_until,'content':content,'kind':kind,'logical_type':logical_type,
            'verification':'unverified','uncertainty':'not_calibrated','rule_version':rule_version,
            'relationships':links,'execution_authorized':False}
        encoded=json.dumps(payload,sort_keys=True,allow_nan=False)
        if SECRET.search(encoded) or re.search(r'(?:^|[/\\])\.env(?:\.|$)',source):
            raise PermissionError('Credential-like episode rejected')
        with self.gateway.db() as db:
            old=db.execute('SELECT payload,outbox_id FROM cognitive_episodes_v2 WHERE id=?',(key,)).fetchone()
            if old:
                if old['payload']!=encoded:raise ValueError('Immutable episode conflict; create a revision event')
                return {'id':key,'outbox_id':old['outbox_id'],'duplicate':True}
            # Outbox and canonical episode commit together; no network or embeddings here.
            outbox=self.runtime.enqueue(source='nucm2:'+key,content=content,
                category=logical_type if logical_type in ('working','episodic','semantic','procedural') else 'episodic',
                metadata=payload,_db=db)
            db.execute('INSERT INTO cognitive_episodes_v2 VALUES(?,?,?,?,?,?,?,?)',
                (key,self.scope['namespace'],self.scope['principal'],domain,observed_at,available_at,encoded,outbox))
        return {'id':key,'outbox_id':outbox,'duplicate':False}

    def retrieve(self, *, domain, as_of, limit=20, source=None):
        self.gateway.require('read',**self.scope)
        cutoff=timestamp(as_of)
        if not 1<=limit<=100 or not isinstance(domain,str) or not domain.isidentifier():
            raise ValueError('Invalid bounded temporal query')
        if source is not None and (not isinstance(source,str) or not 0<len(source)<=512):
            raise ValueError('Invalid source filter')
        with self.gateway.db() as db:
            rows=db.execute('''SELECT payload FROM cognitive_episodes_v2
                WHERE namespace=? AND principal=? AND domain=? AND available_at<=?
                AND (? IS NULL OR json_extract(payload,'$.source')=?)
                ORDER BY available_at DESC,id LIMIT ?''',
                (self.scope['namespace'],self.scope['principal'],domain,cutoff,source,source,limit)).fetchall()
        return [json.loads(r['payload']) for r in rows]
