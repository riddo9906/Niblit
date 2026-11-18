"""Existing Core/adapters with intercepted delivery. Never a broker gateway.

All order-side objects come from the existing offline integration fixture.
Live reads are collected independently through mutation-denying observers.
"""
import hashlib,json,os,sqlite3,subprocess,sys,time,uuid
from pathlib import Path
from types import SimpleNamespace


def runtime():
    from modules.trading_observation import gateway,scope,profile
    return gateway(),scope(),profile()


def recall_environment_preparation():
    """Read scoped preparation evidence; no account grant or broker operation."""
    gateway,scope,_=runtime()
    gateway.require('read',**scope)
    with gateway.db() as db:
        row=db.execute("SELECT metadata FROM audit WHERE action='trading.environment_preparation' "
            "AND json_extract(metadata,'$.namespace')=? AND json_extract(metadata,'$.principal')=? ORDER BY seq DESC LIMIT 1",
            (scope['namespace'],scope['principal'])).fetchone()
    if not row:return {'status':'UNKNOWN','summary':'No scoped environment preparation recorded.',
        'execution_state':'DENIED','external_native_send_count':0}
    return json.loads(row['metadata'])['receipt']


def recall_rehearsal():
    gateway,scope,_=runtime()
    with gateway.db() as db:
        row=db.execute("SELECT record_id,metadata FROM audit WHERE action='trading.execution_rehearsal' "
            "AND json_extract(metadata,'$.namespace')=? AND json_extract(metadata,'$.principal')=? ORDER BY seq DESC LIMIT 1",
            (scope['namespace'],scope['principal'])).fetchone()
    if not row:return {'status':'UNKNOWN','execution_state':'DENIED','summary':'No scoped execution rehearsal recorded.'}
    return json.loads(row['metadata'])['receipt']


def run_rehearsal():
    from modules.permission_manager import PermissionManager
    if not PermissionManager().check('command.run_execution_rehearsal'):raise PermissionError('Rehearsal permission required')
    gateway,scope,_=runtime();gateway.require('ingest',**scope)
    run='execution-rehearsal-'+uuid.uuid4().hex
    completed=subprocess.run([sys.executable,'-B',str(Path(__file__).resolve()),'--worker',run],
        capture_output=True,text=True,timeout=180,check=False)
    if completed.returncode:
        _,_,p=runtime();owned=Path(os.environ['NIBLIT_OBSERVATION_PROFILE']).resolve().parent/'data/execution-rehearsals'/run
        if owned.is_dir():(owned/'worker.stderr.log').write_text(completed.stderr[-16000:],encoding='utf-8')
        return {'status':'FAILED','execution_state':'DENIED','external_native_send_count':0,
            'summary':'Rehearsal worker failed; only fixture order transports exist in the rehearsal. Inspect owned worker evidence.'}
    return json.loads(completed.stdout.strip().splitlines()[-1])


def seed(f,platform,rows):
    """Replay approved deterministic fixture bars; never label them live."""
    factor=.01 if platform=='mt5' else 400
    bar=f.api.bar
    rebased=[{**{k:float(r[k])*factor for k in ('open','high','low','close')},
        'timestamp':bar-(len(rows)-1-i)*300,'volume':float(r.get('volume',10))} for i,r in enumerate(rows)]
    f.api.price=rebased[-1]['close']
    if platform=='mt5':
        f.api.rates=[{**r,'time':r['timestamp'],'tick_volume':int(r['volume'])} for r in rebased]
        f.api.fill_pnl=lambda p,request:f.api.order_calc_profit(p.type,p.symbol,p.volume,p.price_open,request['price'])
    else:
        f.api.candles=rebased
        fee=f.api.config['fee']
        f.api.fill_pnl=lambda p,price:(p['open_rate']-price if p['is_short'] else price-p['open_rate'])*p['amount']-(p['open_rate']+price)*p['amount']*fee


def activate(f,platform,symbol):
    p=f.service.propose(platform,symbol,60,{'max_entries':1})
    f.service.activate(p['id'],p['spec_hash'],threaded=False)
    return p


def detail(f,platform,name,folder,**extra):
    state=f.service.status();orders=state['orders']
    with f.gateway.db() as db:
        events=[dict(r) for r in db.execute('SELECT * FROM trading_events ORDER BY rowid')]
        outbox=db.execute('SELECT count(*) FROM ingestion_outbox').fetchone()[0]
    result={'name':name,'platform':platform,'scope':'INTERCEPTED_ACKNOWLEDGEMENTS; actual Core/adapter/ticket/native-claim logic; deterministic synthetic market inputs',
        'signals':f.bot.manager,'worker_error':f.bot.error,'orders':orders,'events':events,
        'intercepted_delivery_count':len(f.api.sent),'intercepted_requests':f.api.sent,
        'canonical_fixture_outbox_count':outbox,'external_native_send_count':0,
        'authority':'Private fixture ledger and simulated cost assumptions only; no real platform grant',**extra}
    path=folder/'receipt.json';path.write_text(json.dumps(result,indent=2,default=str,allow_nan=False),encoding='utf-8')
    return result


def cases(root,dataset):
    from modules.trading_session_selftest import fixture,freq_fixture
    warmups={s['name']:s['warmup'] for s in dataset['scenarios']}
    results=[]
    for platform,factory,symbol in (('mt5',fixture,'EURUSD'),('freqtrade',freq_fixture,'BTC/USDT:USDT')):
        for side in ('buy','sell'):
            for outcome in ('favorable','adverse'):
                name=side+'-'+outcome;folder=root/platform/name;f=factory(folder)
                seed(f,platform,warmups['long_favorable' if side=='buy' else 'short_favorable'])
                activate(f,platform,symbol);f.bot.step()
                assert len(f.api.sent)==1,(platform,name,f.bot.error,f.bot.manager)
                assert f.bot.manager['side']==side,(platform,name,f.bot.manager)
                f.bot.step();assert len(f.api.sent)==1,'Duplicate entry'
                entry_price=f.api.price
                direction=(1 if side=='buy' else -1)*(1 if outcome=='favorable' else -1)
                f.api.price*=1+direction*.03
                f.bot.step();f.bot.step()
                r=detail(f,platform,name,folder,entry_mark=entry_price,exit_mark=f.api.price,
                    fill_fee_model='MT5 fixed 0.10 per fill; Freqtrade configured synthetic 0.001 each side; no funding. Not broker costs.')
                values=[json.loads(o['result'] or '{}').get('realized_net') for o in r['orders']]
                values=[v for v in values if v is not None]
                assert len(f.api.sent)==2 and values,(platform,name,r['worker_error'],r['orders'])
                assert all((v>0)==(outcome=='favorable') for v in values),(platform,name,values)
                r['verified_net']=values[0]
                if platform=='mt5':
                    opening=f.api.sent[0];closing=f.api.sent[1]
                    expected=f.api.order_calc_profit(opening['type'],symbol,opening['volume'],opening['price'],closing['price'])-.2
                else:
                    trade=f.api.trades[0];expected=f.api.fill_pnl(trade,trade['close_rate'])
                assert abs(expected-values[0])<1e-7,(expected,values)
                r['independent_fill_arithmetic']=expected
                (folder/'receipt.json').write_text(json.dumps(r,indent=2,default=str),encoding='utf-8')
                results.append(r);f.service.shutdown()
        # Organic rule reversal, without changing the execution quote past SL/TP.
        folder=root/platform/'strategy_exit';f=factory(folder);seed(f,platform,warmups['long_favorable'])
        activate(f,platform,symbol);f.bot.step();assert len(f.api.sent)==1
        mark=f.api.price;f.api.bar+=300
        reverse=warmups['short_favorable'];factor=(mark/(.01 if platform=='mt5' else 400))/reverse[-1]['close']
        seed(f,platform,[{**row,**{k:row[k]*factor for k in ('open','high','low','close')}} for row in reverse])
        f.api.price=mark;f.bot.step();f.bot.step()
        r=detail(f,platform,'strategy_exit',folder,exit_test='Later synthetic completed-bar window reverses the entry rule; quote kept near entry, not forced past protective levels')
        assert len(f.api.sent)==2,(platform,r['worker_error'],r['orders'])
        reasons=[json.loads(o['payload']).get('exit_reason') for o in r['orders'] if o['action']=='close']
        assert reasons and any('strateg' in (v or '').lower() or 'trend' in (v or '').lower() for v in reasons),reasons
        r['verified_net']=next(json.loads(o['result'])['realized_net'] for o in r['orders'] if 'realized_net' in json.loads(o['result'] or '{}'))
        if platform=='mt5':
            expected=f.api.order_calc_profit(f.api.sent[0]['type'],symbol,f.api.sent[0]['volume'],f.api.sent[0]['price'],f.api.sent[1]['price'])-.2
        else:expected=f.api.fill_pnl(f.api.trades[0],f.api.trades[0]['close_rate'])
        assert abs(expected-r['verified_net'])<1e-7
        r['passed']=True;results.append(r);f.service.shutdown()
        # Every failure uses the same coordinator and final adapter boundary.
        for fault in ('reject','partial','timeout','missing_costs','insufficient_data','risk_limit','wrong_account','invalid_volume','unsupported_symbol','disagreement'):
            folder=root/platform/fault;f=factory(folder);seed(f,platform,warmups['long_favorable'])
            if fault=='disagreement':seed(f,platform,warmups['disagreement'])
            if fault=='missing_costs':f.service.adapters[platform].cost_model=None
            if fault in ('reject','partial','timeout'):f.api.behavior=fault
            proposal=activate(f,platform,symbol)
            if fault=='insufficient_data':
                if platform=='mt5':f.api.rates=f.api.rates[:10]
                else:f.api.candles=f.api.candles[:10]
            if fault=='risk_limit':
                if platform=='mt5':f.api.account.equity*=.9
                else:f.api.balance_total*=.9
            if fault=='wrong_account':
                if platform=='mt5':f.api.account.login+=1
                else:f.api.config['dry_run']=False
            if fault=='invalid_volume':
                if platform=='mt5':f.api.info.volume_min=.02
                else:f.desk.minimum_stake=lambda *args:1e9
            if fault=='unsupported_symbol':
                if platform=='mt5':f.api.symbol='UNAVAILABLE'
                else:f.api.config['force_entry_enable']=False
            for _ in range(3):f.bot.step()
            r=detail(f,platform,fault,folder)
            expected=1 if fault in ('reject','partial','timeout') else 0
            assert len(f.api.sent)==expected,(platform,fault,r['worker_error'],r['orders'],r['signals'])
            if fault=='disagreement':assert len({c['side'] for c in f.bot.manager['candidates']} & {'buy','sell'})>1
            if fault=='missing_costs':assert 'cost' in (f.bot.error or '').lower(),r
            r['passed']=True;results.append(r);f.service.shutdown()
        # Reopen the existing durable coordinator, retaining simulated broker state.
        folder=root/platform/'restart';f=factory(folder);seed(f,platform,warmups['long_favorable'])
        p=activate(f,platform,symbol);f.bot.step();assert len(f.api.sent)==1
        from modules.core_trading_sessions import CoreTradingSessions
        old=f.service # No shutdown: simulate loss of the non-threaded coordinator.
        f.service=CoreTradingSessions(f.runtime,old.adapters,journal=folder/'demo-learning.sqlite',notify=lambda _:None)
        f.bot=f.service.observe(platform,symbol,threaded=False);f.bot.step();assert len(f.api.sent)==1
        r=detail(f,platform,'restart',folder,recovery='Abrupt coordinator replacement against original SQLite/retained broker-double position; old worker not resumed; no blind resend or implicit scope restoration',
            previous_scope_state=f.service.session(p['id'])['state'])
        assert r['previous_scope_state']=='interrupted',r['previous_scope_state']
        r['passed']=True;results.append(r);f.service.shutdown()
    return results


def captured_gates(root,mt,ft):
    """Use captured native data in existing adapters; no real identity grant."""
    from modules.trading_session_selftest import fixture,freq_fixture
    results=[]
    folder=root/'mt5/captured_market';f=fixture(folder)
    original=mt['result'].get('selected_instrument_review') or mt['result'];symbol=original['symbol'];spec=original['specification']
    f.api.symbol=symbol;f.api.info=SimpleNamespace(**spec,name=symbol,visible=True)
    f.api.rates=[{**r,'time':r['timestamp'],'tick_volume':int(r.get('volume',0))} for r in original['prediction_inputs']['candles']]
    f.api.bar=f.api.rates[-1]['time'];f.api.quote_time=original['quote']['timestamp'];f.api.price=original['quote']['bid']
    a=original['account_actuals']
    f.api.positions=[SimpleNamespace(**p) for p in original['positions']]
    f.api.orders_get=lambda:tuple(SimpleNamespace(symbol=symbol,magic=0) for _ in range(original['pending_order_count']))
    for key,value in {'equity':a['equity'],'balance':a['balance'],'currency':a['currency'],
                      'margin':a['margin'],'margin_free':a['free_margin']}.items():setattr(f.api.account,key,value)
    sample=original['execution_review']['scenarios'][0]
    margin=sample.get('margin_estimate')
    if margin is not None:
        f.api.order_calc_margin=lambda kind,symbol,volume,price:margin*volume/sample['volume']
        f.api.order_check=lambda request:SimpleNamespace(retcode=0,margin=a['margin']+margin,margin_free=a['free_margin'],comment='INTERCEPTED check; captured native margin')
    f.service.adapters['mt5'].cost_model=None
    f.bridge.snapshot(symbol);f.bridge.snapshot(symbol) # Prime local advancement for this captured symbol.
    f.bot=f.service.observe('mt5',symbol,threaded=False)
    p=activate(f,'mt5',symbol);f.bot.step();f.bot.step()
    r=detail(f,'mt5','captured_market',folder,source_observed_at=mt['observed_at'],
        observed_native_identity=original['account']['identity'],
        binding_note='Captured specifications/prices/account totals; OFFLINE_FIXTURE execution identity and simulated acknowledgements. No grant for observed account.',
        scope='Captured real M5 market replay through real Core/MT5 adapter, with complete real costs absent; no synthetic favorable signal injected')
    assert not f.api.sent,(r['signals'],r['worker_error'])
    r['passed']=True;results.append(r);f.service.shutdown()
    folder=root/'freqtrade/captured_capacity';f=freq_fixture(folder);source=ft['result']
    f.api.config.update(state='stopped',strategy='NiblitLabManager',max_open_trades=3,fee=None)
    f.api.balance_total=source['actuals']['capital']['marked_equity_reported']
    f.api.available_override=source['actuals']['capital']['available']
    f.api.trades=[]
    for item in source['position_monitor']['positions']:
        p=dict(item['recorded']);p['has_open_orders']=False;p['profit_abs']=next(x['unrealized_reported'] for x in source['actuals']['positions'] if x['trade_id']==p['trade_id'])
        p['stop_loss_ratio']=-abs(p['stop_loss_abs']/p['open_rate']-1);f.api.trades.append(p)
    snapshot=f.service.adapters['freqtrade'].snapshot('BTC/USDT:USDT')
    proposal=activate(f,'freqtrade','BTC/USDT:USDT');row=f.service.session(proposal['id'])
    try:f.service.risk(row,snapshot,action='open');raise AssertionError('Native full capacity was not enforced')
    except PermissionError as exc:capacity_reason=str(exc)
    try:f.service.adapters['freqtrade'].prepare(snapshot,'buy',row['spec']['limits']);raise AssertionError('Stopped native strategy admitted')
    except PermissionError as exc:adapter_reason=str(exc)
    r=detail(f,'freqtrade','captured_capacity',folder,source_observed_at=ft['observed_at'],
        real_position_ids=[p['trade_id'] for p in f.api.trades],capacity_denial=capacity_reason,adapter_denial=adapter_reason,
        scope='Actual native position/config/capital snapshot in isolated adapter gate; fixture market only for preflight shape. Live public strategy observations are the separate source receipt.')
    assert not f.api.sent and len(f.api.trades)==3
    r['passed']=True;results.append(r);f.service.shutdown()
    return results


_NATIVE_BINANCE_CONTRACT_TEST = '"""Installed Freqtrade/CCXT code; every external operation is a test double."""\nimport copy,hashlib,inspect,json\nfrom unittest.mock import Mock\nimport ccxt, freqtrade\nfrom freqtrade.exchange.binance import Binance\nfrom freqtrade.enums import TradingMode\n\nclass InterceptedCCXT:\n    options={};precisionMode=ccxt.TICK_SIZE\n    def __init__(self,result=None,error=None):self.calls=[];self.result=result;self.error=error\n    def create_order(self,*args):\n        self.calls.append(copy.deepcopy(args))\n        if self.error:raise self.error\n        return copy.deepcopy(self.result)\n\ndef exchange(kind,response,error=None):\n    x=Binance.__new__(Binance)\n    x._config={\'dry_run\':False} # Exercise native private branch, with no real client.\n    x.trading_mode=TradingMode.SPOT if kind==\'spot\' else TradingMode.FUTURES\n    x._params={};x._ft_has={\'order_props_in_contracts\':[\'amount\',\'filled\',\'remaining\']}\n    x._markets={\'BTC/USDT:USDT\':{\'contractSize\':.001}}\n    x._api=InterceptedCCXT(response,error)\n    x.get_precision_amount=Mock(return_value=.001)\n    x.get_precision_price=Mock(return_value=.01)\n    x._lev_prep=Mock() # Margin/leverage mutations explicitly intercepted.\n    x._log_exchange_response=Mock()\n    x.close=Mock() # The fake owns no network/session resources.\n    return x\n\nrecords=[]\nfor kind in (\'spot\',\'usdm\'):\n    symbol=\'BTC/USDT\' if kind==\'spot\' else \'BTC/USDT:USDT\'\n    contracts=.01 if kind==\'spot\' else 10\n    for side in (\'buy\',\'sell\'):\n        for status,filled in ((\'closed\',contracts),(\'open\',contracts/2)):\n            reply={\'id\':\'SIMULATED\',\'symbol\':symbol,\'status\':status,\'average\':100.,\'filled\':filled,\n                   \'amount\':contracts,\'remaining\':contracts-filled,\'fee\':{\'cost\':.001,\'currency\':\'USDT\'}}\n            x=exchange(kind,reply)\n            result=x.create_order(pair=symbol,ordertype=\'limit\',side=side,amount=.01,rate=100.001,\n                leverage=1,time_in_force=\'IOC\',reduceOnly=(kind==\'usdm\' and side==\'sell\'))\n            args=x._api.calls[0]\n            assert len(x._api.calls)==1 and abs(args[3]-contracts)<1e-9 and args[4]==100.\n            assert args[5][\'timeInForce\']==\'IOC\'\n            assert bool(args[5].get(\'reduceOnly\'))==(kind==\'usdm\' and side==\'sell\')\n            assert result[\'status\']==status and abs(result[\'amount\']-.01)<1e-9\n            assert result[\'fee\']==reply[\'fee\']\n            records.append({\'market\':kind,\'side\':side,\'status\':status,\'request\':args,\'acknowledgement\':result,\n                \'leverage_mutations_intercepted\':True,\'external_send_count\':0})\n    for error in (ccxt.InvalidOrder(\'fixture rejection\'),ccxt.InsufficientFunds(\'fixture funds\'),ccxt.RequestTimeout(\'fixture uncertain delivery\')):\n        x=exchange(kind,None,error)\n        try:x.create_order(pair=symbol,ordertype=\'market\',side=\'buy\',amount=.01,rate=100.,leverage=1)\n        except Exception as exc:\n            assert len(x._api.calls)==1 # No blind retry after an unknown outcome.\n            records.append({\'market\':kind,\'failure\':type(error).__name__,\'mapped_error\':type(exc).__name__,\n                            \'attempts\':1,\'external_send_count\':0})\n        else:raise AssertionError(\'Native exchange failure was hidden\')\nprint(json.dumps({\'status\':\'PASSED\',\'scope\':\'Installed Binance.create_order with intercepted CCXT client and synthetic market rules; no credentials, account calls or real exchange delivery\',\n \'freqtrade_version\':freqtrade.__version__,\'ccxt_version\':ccxt.__version__,\n \'native_method_sha256\':hashlib.sha256(inspect.getsource(Binance.create_order).encode()).hexdigest(),\n \'cases\':records,\'external_send_count\':0,\'limitations\':[\'Contract size and precision are controlled fixtures, not current exchange specifications\',\n \'Leverage and margin mutations are intercepted; no account-level permissions or leverage tiers verified\',\n \'Core strategy/risk/expiry/restart monitoring tested separately in the existing shared rehearsal\']}))\n'

def native_exchange_contracts():
    # Fixed installed-runtime test. This is not a general Docker command tool.
    name=os.getenv('NIBLIT_REHEARSAL_FREQTRADE_CONTAINER','')
    if not name:return {'status':'NOT_CONFIGURED','external_send_count':0}
    if not __import__('re').fullmatch(r'niblit-trading-candidate-[0-9]{8}',name):raise PermissionError('Untrusted contract-test container')
    child_env=os.environ.copy()
    # Core's legacy Unix default is not a Windows Docker Desktop endpoint.
    # Preserve the operator's selected Docker context; change only this fixed test child.
    if os.name=='nt' and child_env.get('DOCKER_HOST')=='unix:///var/run/docker.sock':
        child_env.pop('DOCKER_HOST')
    inspected=subprocess.run(['docker','inspect',name],capture_output=True,text=True,check=False,timeout=10,env=child_env)
    if inspected.returncode:raise RuntimeError('Native container inspection unavailable: '+inspected.stderr[-2000:])
    container=json.loads(inspected.stdout)[0]
    if container['Image']!='sha256:9d67afb8eb5f4e1210f4fb067efcbd5e005bd4f1c27f6f3888b8b9fc7f9b5199':
        raise PermissionError('Native runtime image/ownership not verified')
    if not container['State']['Running']:
        return {'status':'UNAVAILABLE','reason':'Pinned isolated test container is stopped; completed Core/adapter evidence is retained','external_send_count':0,'cases':[]}
    expected=Path(os.environ['NIBLIT_FREQTRADE_EXECUTION_CONFIG']).resolve().parent
    mounts=[m for m in container['Mounts'] if m['Destination']=='/freqtrade/user_data']
    if len(mounts)!=1 or Path(mounts[0]['Source']).resolve()!=expected:
        raise PermissionError('Contract-test environment binding changed')
    response=subprocess.run(['docker','exec','-i',name,'python','-B','-'],input=_NATIVE_BINANCE_CONTRACT_TEST,
        capture_output=True,text=True,timeout=60,check=True,env=child_env)
    receipt=json.loads(response.stdout.strip().splitlines()[-1])
    if receipt.get('status')!='PASSED' or receipt.get('external_send_count')!=0:
        raise RuntimeError('Native exchange contract acceptance failed')
    return receipt


def worker(run):
    from modules.trading_observation import collect
    from modules.paper_trading import _replay_manifest
    gateway,scope,p=runtime();gateway.require('ingest',**scope)
    base=Path(os.environ['NIBLIT_OBSERVATION_PROFILE']).resolve().parent
    root=base/'data/execution-rehearsals'/run;root.mkdir(parents=True)
    source=collect(review=True)
    captured={}
    with gateway.db() as db:
        for report in source['reports']:
            row=db.execute("SELECT metadata FROM audit WHERE record_id=? AND action='trading.execution_review'",(report['record_id'],)).fetchone()
            metadata=json.loads(row[0]);path=Path(metadata['evidence_path']).resolve()
            if not path.is_relative_to(Path(p['output_root']).resolve()):raise PermissionError('Source evidence outside owned root')
            content=path.read_bytes()
            if hashlib.sha256(content).hexdigest()!=metadata['evidence_sha256']:raise PermissionError('Source evidence changed')
            captured[report['platform']]=json.loads(content)
    manifest=_replay_manifest();dataset_bytes=Path(manifest['dataset']).read_bytes()
    dataset=json.loads(dataset_bytes)
    try:
        results=cases(root,dataset)
        results+=captured_gates(root,captured['mt5'],captured['freqtrade'])
        status='PASSED'
    except Exception as exc:
        (root/'failure.json').write_text(json.dumps({'type':type(exc).__name__,'error':str(exc)[:4000]}),encoding='utf-8')
        raise
    summaries=[]
    for r in results:
        opening=next((json.loads(o['payload']) for o in r['orders'] if o['action']=='open'),None)
        closing=next((json.loads(o['payload']) for o in r['orders'] if o['action']=='close'),None)
        summaries.append({'platform':r['platform'],'case':r['name'],'intercepted_calls':r['intercepted_delivery_count'],
            'net':r.get('verified_net'),'signal':(r.get('signals') or {}).get('side'),
            'selected_strategy':(r.get('signals') or {}).get('strategy'),
            'eligible_strategies':[c.get('strategy') for c in (r.get('signals') or {}).get('candidates',[]) if c.get('side') in ('buy','sell')],
            'entry_order':r['intercepted_requests'][0] if r['intercepted_requests'] else None,
            'exit_order':r['intercepted_requests'][-1] if len(r['intercepted_requests'])>1 else None,
            'modeled_cost_risk':opening['prepared'].get('costs') if opening else None,
            'exit_reason':closing.get('exit_reason') if closing else None,
            'monitoring_events':sum(e['kind']=='position_watch' for e in r['events']),
            'error':r.get('worker_error'),'passed':True,'receipt':str(root/r['platform']/r['name']/'receipt.json')})
    native=native_exchange_contracts()
    if native.get('status')=='UNAVAILABLE':status='PARTIAL' # Never label an unavailable native contract as passed.
    (root/'binance-native-contracts.json').write_text(json.dumps(native,indent=2),encoding='utf-8')
    receipt={'run_id':run,'status':status,'scope':'Actual existing Core and adapters; broker/platform acknowledgements and deterministic market scenarios are simulated',
        'live_read_observations':source,'dataset_sha256':hashlib.sha256(dataset_bytes).hexdigest(),
        'cases':summaries,'binance_native_contracts':native,'external_native_send_count':0,'execution_state':'DENIED',
        'evidence':'execution-rehearsal://'+run,
        'summary':'Both existing adapter paths rehearsed. All external delivery remains intercepted; no real demo/dry-run execution authorized.',
        'limitations':['Native fee cache/complete real costs remain unverified; simulated cost bounds grant no real authority',
            'Synthetic round trips are not broker execution or profitability evidence',
            'Current native Freqtrade positions and ownership remain untouched']}
    if native.get('status')=='PASSED':
        receipt['summary']+=' Installed Binance Spot/USDM private-order contracts passed '+str(len(native['cases']))+' intercepted cases; no private credentials or exchange orders.'
    final=root/'receipt.json';final.write_text(json.dumps(receipt,indent=2),encoding='utf-8')
    with gateway.db() as db:gateway.audit(db,'trading.execution_rehearsal',run,**scope,receipt=receipt,
        source_type='intercepted_execution_rehearsal',evidence_path=str(final),sha256=hashlib.sha256(final.read_bytes()).hexdigest(),execution_state='DENIED')
    return receipt


if __name__=='__main__':
    sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
    run=sys.argv[2]
    if not __import__('re').fullmatch(r'execution-rehearsal-[0-9a-f]{32}',run):raise ValueError('Invalid owned run identity')
    print(json.dumps(worker(run),default=str))
