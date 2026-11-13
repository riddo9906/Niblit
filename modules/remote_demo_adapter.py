"""Pinned SSH transport for Core's existing bounded demo sessions.

No retries on POST, direct MT5 fallback, automatic activation, or live mode.
"""
import http.client
import json
from pathlib import Path
import time
from urllib.parse import urlsplit


class RemoteDemoAdapter:
    def __init__(self, profile):
        p=json.loads(Path(profile).read_text(encoding='utf-8-sig'))
        if set(p)!={'schema_version','endpoint','token_file','gateway_id','account','ssh_peer'} or p['schema_version'] not in ('exness-demo/1','mt5-demo/1'):
            raise ValueError('Unsupported remote demo profile')
        u=urlsplit(p['endpoint'])
        if (u.scheme!='http' or u.hostname!='127.0.0.1' or not u.port or u.username or u.password
                or u.path not in ('','/') or u.query or u.fragment):raise ValueError('Pinned loopback SSH transport required')
        a=p['account']
        if (a.get('environment')!='demo' or not ((a.get('server','').startswith('Exness-') and 'exness' in a.get('broker','').lower())
                    or (a.get('server','').startswith('XM') and 'xm' in a.get('broker','').lower())
                    or (a.get('server','').startswith('MetaQuotes-') and 'metaquotes' in a.get('broker','').lower())) or not str(a.get('login','')).isdigit()
                or not Path(p['token_file']).is_absolute()):raise ValueError('Pinned MT5 demo binding required')
        import re
        if not re.fullmatch('[a-f0-9]{64}',p['gateway_id']):raise ValueError('Pinned demo gateway required')
        peer=p['ssh_peer']
        if (set(peer)!={'host','user','key_file','known_hosts_file'}
                or not re.fullmatch('[A-Za-z0-9.-]+',peer['host'])
                or not re.fullmatch('[A-Za-z0-9_-]+',peer['user'])
                or not all(Path(peer[k]).is_absolute() for k in ('key_file','known_hosts_file'))):
            raise ValueError('Pinned SSH peer required')
        self.profile=p;self.url=u;self.last_status=None

    def call(self, action, body=None):
        from modules.ssh_forward_identity import verify_peer
        c=http.client.HTTPConnection('127.0.0.1',self.url.port,timeout=12)
        try:
            c.connect()
            verify_peer(self.profile['ssh_peer'],self.url.port)
            token=Path(self.profile['token_file']).read_text(encoding='ascii').strip()
            import re
            if not re.fullmatch('[a-f0-9]{64}',token):raise PermissionError('Invalid demo credential')
            c.request('POST' if body is not None else 'GET','/demo/'+action,
                      body=json.dumps(body,allow_nan=False) if body is not None else None,
                      headers={'Authorization':'Bearer '+token,'Content-Type':'application/json'})
            r=c.getresponse();raw=r.read(2_000_001)
            if len(raw)>2_000_000:raise ValueError('Demo response exceeded')
            if r.status!=200:raise PermissionError('Remote demo rejected '+action+' ('+str(r.status)+'); no automatic retry')
            payload=json.loads(raw)
            if payload.get('schema_version')!='exness-demo/1' or payload.get('gateway_id')!=self.profile['gateway_id']:
                raise PermissionError('Wrong remote demo gateway')
            return payload['result']
        finally:c.close()

    def status(self):
        try:
            s=self.call('status')
            if (s['account']!=self.profile['account'] or s['funded_execution_enabled'] is not False
                    or type(s['observed_at']) not in (int,float) or not 0<=time.time()-s['observed_at']<15):
                raise PermissionError('Demo identity or freshness failed')
            self.last_status=s
            return {'configured':True,'verified':True,**s}
        except Exception:
            return {'configured':True,'verified':False,'funded_execution_enabled':False,
                    'error':'remote_demo_unavailable','last_verified':self.last_status}

    def checked(self,s):
        if s.get('environment')!='demo' or s.get('account_binding')!=self.profile['account']:
            raise PermissionError('Demo account changed')
        if type(s.get('observed_at')) not in (int,float) or not 0<=time.time()-s['observed_at']<15:
            raise PermissionError('Stale demo observation')
        return s

    def snapshot(self,symbol):return self.checked(self.call('snapshot',{'symbol':symbol}))

    def reconciliation_identity(self):
        r=self.call('identity')
        if r!={'account':self.profile['account']['identity'],'environment':'demo'}:
            raise PermissionError('Wrong demo reconciliation identity')
        return r

    def market(self,symbol):
        r=self.call('market',{'symbol':symbol})
        account=r.get('account',{})
        if any(account.get(k)!=v for k,v in self.profile['account'].items() if k!='login'):
            raise PermissionError('Wrong demo market identity')
        if r.get('symbol')!=symbol or not 0<=time.time()-r.get('checked_at',0)<15:
            raise PermissionError('Stale or wrong demo market')
        return r

    def prepare(self,s,side,limits,position=None):
        self.checked(s)
        return self.call('prepare',{'symbol':s['symbol'],'side':side,'limits':limits,'position':position,
                                    'strategy':s.get('entry_strategy')})

    def submit(self,prepared,guard):
        if not callable(guard):raise PermissionError('Current Core guard required')
        scope=guard()
        if not scope or scope.get('environment')!='demo':raise PermissionError('Explicit Core demo scope required')
        # Once sent, a timeout is UNKNOWN in Core. This call has no retry loop.
        return self.call('submit',{'ticket':prepared['ticket'],'expires':scope['expires']})

    def reconcile(self,order):return self.call('reconcile',{'order':order})
    def cancel_prepared(self,order):return self.call('cancel-prepared',{'order':order})
    def emergency_stop(self):return self.call('emergency-stop',{})
