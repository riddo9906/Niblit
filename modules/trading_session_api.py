import os
"""Local operator routes for Core's bounded trading sessions; no model tools."""
import secrets
from typing import Literal
from fastapi import Request,HTTPException
from pydantic import BaseModel,Field


class Proposal(BaseModel):
    model_config={'extra':'forbid'}
    adapter:Literal['mt5','freqtrade','exness_demo']
    symbol:str=Field(min_length=1,max_length=80)
    seconds:int=Field(default=1800,ge=60,le=3600)
    limits:dict[str,float]=Field(default_factory=dict)
    close_order_id:str|None=Field(default=None,pattern=r'^[a-f0-9]{64}$')


class Activation(BaseModel):
    model_config={'extra':'forbid'}
    id:str=Field(pattern=r'^[a-f0-9]{32}$')
    spec_hash:str=Field(pattern=r'^[a-f0-9]{64}$')
    acknowledgement:Literal['ACTIVATE_BOUNDED_DEMO_SESSION']
    clear_emergency_stop:bool=False


class Stop(BaseModel):
    model_config={'extra':'forbid'}
    id:str|None=None
    emergency:bool=False


class NativeReceipt(BaseModel):
    model_config={'extra':'forbid'}
    ticket:str=Field(pattern=r'^[A-Za-z0-9_-]{32}$')
    symbol:str=Field(min_length=1,max_length=80)
    side:Literal['long','short']
    amount:float=Field(gt=0,allow_inf_nan=False)
    rate:float=Field(gt=0,allow_inf_nan=False)
    stoploss:float=Field(lt=0,ge=-.01,allow_inf_nan=False)
    minimal_roi:dict
    fee:float=Field(ge=0,le=.01,allow_inf_nan=False)
    account_binding:str=Field(pattern=r'^[a-f0-9]{64}$')


def demo_control_policy(status):
    locked=os.getenv('NIBLIT_DESKTOP_OBSERVATION_ONLY')=='1'
    mt5_enabled=os.getenv('NIBLIT_MT5_DEMO_DELIVERY_ENABLED')=='1'
    ft_enabled=os.getenv('NIBLIT_FREQTRADE_DEMO_DELIVERY_ENABLED')=='1'
    # The remote MT5 demo uses a separately pinned and verified gateway, not
    # the local MT5 delivery flag. Verification is only eligibility to review:
    # it never creates a session or bypasses the gateway's final broker checks.
    remote=status.get('remote_demo') or {}
    remote_enabled=remote.get('configured') is True and remote.get('verified') is True
    delivery_authorized=(not locked) and (mt5_enabled or ft_enabled or remote_enabled)
    delivery_blocker=(None if delivery_authorized else
        'Installed desktop is observation-only' if locked else
        'No verified demo delivery transport configured; local MT5/Freqtrade delivery is off and the remote demo gateway is absent or unverified')
    return {'mode':'observation_and_intercepted_rehearsal' if locked else 'scoped_demo_only',
        'review_available':True,'activation_available':not locked,
        'delivery_authorized':delivery_authorized,'delivery_blocker':delivery_blocker,
        'funded_execution_available':False,
        'emergency_stopped':bool(status.get('emergency_stopped')),
        'platform_delivery_enabled':{'mt5':mt5_enabled,'freqtrade':ft_enabled,'exness_demo':remote_enabled},
        'blocker':None if not locked else 'Deployment observation-only lock; no scope activation permitted',
        'stop_notice':'Review and simulation do not clear the emergency stop.'}


def demo_readiness(control,adapter,symbol,limits=None):
    """Existing adapters/consensus and draft inspection only. No ticket or grant."""
    import time,uuid
    from modules.core_trading_sessions import scoped_limits
    from modules.strategy_manager import assess_with_context
    state=control.status();policy=demo_control_policy(state)
    blockers=[]
    def block(code,reason):blockers.append({'code':code,'reason':str(reason)[:500]})
    if not policy['activation_available']:block('deployment_lock',policy['blocker'])
    if not policy['platform_delivery_enabled'].get(adapter,False):block('platform_delivery_disabled','This platform demo transport is not explicitly enabled; no implicit cross-platform permission')
    if policy['emergency_stopped']:block('emergency_stop','Persisted stop is latched; only an explicit future operator action may reset it')
    result={'id':'demo-review-'+uuid.uuid4().hex,'observed_at':time.time(),'adapter':adapter,'symbol':symbol,
        'policy':policy,'blockers':blockers,'execution_authorized':False,'activation_eligible':False,
        'review_only':True,'order_ticket_created':False,'external_send_count':0,
        'monitoring':{'contract_available':False,'running':False},'risk_approval':'NOT_GRANTED'}
    try:
        if adapter not in control.adapters:raise PermissionError('Platform adapter unavailable')
        a=control.adapters[adapter];snap=a.snapshot(symbol)
        result.update(account=snap['account'],environment=snap['environment'],quote=snap.get('quote'),
            account_binding={k:v for k,v in snap.get('account_binding',{}).items() if k!='login'},
            exposure={k:snap.get(k) for k in ('currency','equity','available','margin','exposure','open_risk')},
            positions=snap.get('positions',[]),limits=scoped_limits(adapter,snap,limits))
        active=any(r.get('state')=='active' and all(r.get('spec',{}).get(k)==v for k,v in
            {'adapter':adapter,'symbol':symbol,'account':snap['account'],'environment':snap['environment']}.items()) for r in state.get('sessions',[]))
        if not active:block('no_scoped_authority','No active account-bound session for this platform and instrument')
        claims=[o for o in state.get('orders',[]) if o.get('instrument')==snap['instrument'] and o.get('action')=='open'
            and o.get('state') in ('prepared','sending','unknown','submitted','open','partial')]
        result['order_receipts']=[{k:o.get(k) for k in ('id','adapter','symbol','state','updated')} for o in claims]
        if claims:block('outstanding_claim','Existing position or unresolved delivery claim; reconcile its original account before another entry. No blind retry.')
        if snap['environment'] not in ('demo','dry-run','simulation'):block('wrong_environment','Funded or unknown account cannot authorize demo execution')
        try:control.validate_snapshot(snap,symbol)
        except (ValueError,PermissionError) as exc:block('market_validation',exc)
        config=snap.get('configuration',{})
        if adapter=='freqtrade':
            result['controller']={'environment':snap['environment'],'strategy':config.get('strategy'),'engine_state':config.get('state'),
                'native_callback':'Authenticated Core claim required; callback is not permission',
                'fee':snap.get('protections',{}).get('fee'),
                'fee_provenance':'Isolated engine show_config response; prospective costs require the separate bound profile',
                'native_capacity':config.get('max_open_trades')}
            if config.get('strategy')!='NiblitCoreManaged':block('strategy_mismatch','Execution adapter requires CoreManaged; historical Lab positions are not adopted')
            if config.get('state')!='running':block('engine_stopped','Isolated Freqtrade engine is stopped; it will not be started automatically')
            capacity=config.get('max_open_trades')
            if isinstance(capacity,int) and capacity>=0 and len(snap.get('positions',[]))>=capacity:block('position_capacity','Native position capacity is occupied')
        decision=assess_with_context(snap.get('candles',[]),snap.get('market_context'))
        result['consensus']=decision
        if decision.get('side') not in ('buy','sell'):
            block('consensus_abstention',decision.get('selection_reason') or 'No eligible entry signal')
            block('entry_preflight_pending','No qualifying direction; a complete entry risk/cost preflight has not been established')
        if adapter=='exness_demo':
            # Remote demo prepares a broker-bound ticket only after activation.
            # Never call prepare() from a read-only readiness review, and never
            # claim a completed cost/risk preflight before that gateway check.
            result['remote_order_preflight']='PENDING_AT_EXECUTION'
            result['risk_approval']='NOT_GRANTED_REMOTE_PREFLIGHT_PENDING'
        elif not getattr(a,'cost_schedule',None):
            block('missing_cost_bounds','No approved complete prospective cost profile is configured')
        if adapter!='exness_demo' and decision.get('side') in ('buy','sell') and snap['environment'] in ('demo','dry-run','simulation'):
            try:
                draft=a.draft_entry(snap,decision['side'],result['limits'])
                result['draft']={k:v for k,v in draft.items() if k not in ('ticket','expected')}
                if not draft.get('costs',{}).get('costs_complete'):block('incomplete_costs','Existing cost/risk preflight remains incomplete')
                row={'id':result['id'],'spec':{'adapter':adapter,'symbol':symbol,'environment':snap['environment'],'limits':result['limits']},
                    'initial_equity':snap['equity'],'peak_equity':snap['equity']}
                try:
                    control.risk(row,snap,draft,record=False)
                    result['risk_approval']='PREFLIGHT_PASSED_NOT_EXECUTION_PERMISSION'
                except (ValueError,PermissionError) as exc:block('risk_preflight',exc)
            except (ValueError,PermissionError) as exc:block('entry_preflight',exc)
        result['monitoring']={'contract_available':callable(getattr(a,'reconcile',None)),
            'running':any(o.get('adapter')==adapter and o.get('symbol')==symbol and o.get('running') for o in state.get('observers',[])),
            'exit_authority':'Only exact Core-owned positions within an approved scope; historical positions remain untouched'}
        authorization_codes={'deployment_lock','platform_delivery_disabled','wrong_environment','market_validation','strategy_mismatch','engine_stopped','position_capacity','missing_cost_bounds','incomplete_costs','entry_preflight','entry_preflight_pending','risk_preflight','outstanding_claim'}
        result['activation_eligible']=not any(b['code'] in authorization_codes for b in blockers)
    except (ValueError,PermissionError,KeyError) as exc:block('unavailable_or_unverified',exc)
    except Exception as exc:block('dependency_unavailable',type(exc).__name__)
    evidence=control.emit('demo_readiness_review',{**result,'environment':result.get('environment','UNKNOWN'),
        'scope':'readiness only; no ticket, grant, stop reset or delivery'})
    result['evidence']={'event_id':evidence,'source':'trading-event://'+evidence}
    return result


def register_trading_routes(app,provider,*,native_callback=None):
    allowed={'http://127.0.0.1:5000','http://localhost:5000','http://127.0.0.1:8767',
             'http://localhost:8767','http://127.0.0.1:5173','http://localhost:5173',
             'tauri://localhost','http://tauri.localhost','https://tauri.localhost'}
    port=int(os.getenv('NIBLIT_API_PORT','5000'))
    if not 1024<=port<=65535:raise ValueError('Invalid local Core port')
    allowed.update({f'http://127.0.0.1:{port}',f'http://localhost:{port}'})
    # Authenticated native receipt scope is configured independently of browser authority.
    native_config=os.getenv('NIBLIT_FREQTRADE_EXECUTION_CONFIG','').strip()
    native_token=os.getenv('NIBLIT_NATIVE_CALLBACK_TOKEN_FILE','').strip()
    if bool(native_config)!=bool(native_token):raise ValueError('Complete native callback binding required')
    if native_config:
        import json,re
        from pathlib import Path
        from modules.freqtrade_core_claim import account_binding
        config=json.loads(Path(native_config).read_text(encoding='utf-8'))
        if config.get('dry_run') is not True or config.get('strategy')!='NiblitCoreManaged':
            raise PermissionError('Native callback requires isolated CoreManaged dry-run configuration')
        token=Path(native_token).read_text(encoding='utf-8').strip()
        if not re.fullmatch(r'[A-Za-z0-9_-]{32,128}',token):raise ValueError('Invalid native callback credential')
        app.state.niblit_native_callback=(f'host.docker.internal:{port}',token,account_binding(config))
    def service(request,mutation=False,*,safe_control=False):
        if mutation and not safe_control and os.getenv('NIBLIT_DESKTOP_OBSERVATION_ONLY')=='1':
            raise HTTPException(403,'EXECUTION_DENIED: installed desktop is observation-only')
        origin=request.headers.get('origin')
        if request.headers.get('host','') not in (f'127.0.0.1:{port}',f'localhost:{port}','testserver') or (origin is not None and origin not in allowed):
            raise HTTPException(403,'Local Core operator UI required')
        control=provider()
        if control is None:raise HTTPException(503,'Canonical trading control unavailable; execution blocked')
        if mutation and (origin not in allowed or not secrets.compare_digest(request.headers.get('x-niblit-trading-nonce',''),control.nonce)):
            raise HTTPException(403,'Explicit human operator session required')
        return control
    def run(fn):
        try:return fn()
        except HTTPException:raise
        except PermissionError as exc:raise HTTPException(403,str(exc))
        except ValueError as exc:raise HTTPException(409,str(exc))
        except Exception:raise HTTPException(503,'Trading dependency unavailable; no automatic retry')
    @app.post('/api/trading/native-entry-receipt')
    def native_receipt(body:NativeReceipt,request:Request):
        # Native bot callback consumes a sending claim; it cannot activate a
        # session or mint permission. It must not require a browser Origin.
        def apply():
            callback_scope=native_callback or getattr(app.state,'niblit_native_callback',None)
            if callback_scope is None:
                control=service(request)
            else:
                # Explicit installation-owned native scope; never applies to operator routes.
                expected_host,expected_token,expected_binding=callback_scope
                if (request.headers.get('host')!=expected_host or request.headers.get('origin') is not None
                        or not expected_token or not secrets.compare_digest(
                            request.headers.get('x-niblit-native-token',''),expected_token)
                        or not secrets.compare_digest(body.account_binding,expected_binding)):
                    raise HTTPException(403,'Native callback scope denied')
                control=getattr(app.state,'niblit_native_provider',provider)()
                if control is None:raise HTTPException(503,'Canonical native control unavailable')
            return control.native_entry_receipt(body.model_dump())
        return run(apply)

    @app.get('/api/trading/software-readiness')
    def software_readiness(request:Request):
        def apply():
            service(request) # Existing local operator boundary; no private account request.
            import hashlib,json
            from pathlib import Path
            configured=os.getenv('NIBLIT_FREQTRADE_EXECUTION_CONFIG','')
            cfg=json.loads(Path(configured).read_text(encoding='utf-8')) if configured else {}
            from modules.trading_execution_rehearsal import recall_rehearsal
            receipt=recall_rehearsal()
            native=receipt.get('binance_native_contracts',{})
            return {'execution_authorized':False,'mode':'intercepted software validation',
                'mt5':{'cost_profile_configured':bool(os.getenv('NIBLIT_MT5_COST_PROFILE')),
                    'unknown_costs_block_entry':True,'binding':'account/server/terminal/symbol/side/size/expiry'},
                'freqtrade':{'explicit_controller_binding':bool(configured),
                    'environment':'dry-run' if cfg.get('dry_run') is True else 'UNKNOWN',
                    'strategy':cfg.get('strategy','UNKNOWN'),'api':os.getenv('NIBLIT_FREQTRADE_EXECUTION_API','UNKNOWN'),
                    'callback':cfg.get('niblit_core_callback_url','UNKNOWN')},
                'binance':{'backend':'existing Freqtrade Binance/CCXT implementation',
                    'markets':['Spot','linear USDM futures'],'private_account_verified':False,
                    'native_contract_test':native.get('status','NOT_RUN'),
                    'intercepted_cases':len(native.get('cases',[]))},
                'last_rehearsal':{'id':receipt.get('run_id'),'status':receipt.get('status'),
                    'external_native_send_count':receipt.get('external_native_send_count'),
                    'evidence':receipt.get('evidence')},
                'safety':'No private exchange credentials are loaded by the contract test. Separate operational activation required.'}
        return run(apply)

    @app.get('/api/trading/sessions')
    def status(request:Request):
        def apply():
            result=service(request).status()
            result['execution_controls']=demo_control_policy(result)
            return result
        return run(apply)
    @app.post('/api/trading/sessions/readiness')
    def readiness(body:Proposal,request:Request):
        return run(lambda:demo_readiness(service(request,True,safe_control=True),body.adapter,body.symbol,body.limits))

    @app.get('/api/trading/exness-demo/market')
    def demo_market(request:Request,symbol:str='BTCUSDm'):
        def apply():
            control=service(request)
            if 'exness_demo' not in control.adapters:raise PermissionError('Exness demo is not configured')
            return control.adapters['exness_demo'].market(symbol)
        return run(apply)
    @app.post('/api/trading/sessions/observe')
    def observe(body:Proposal,request:Request):
        def apply():
            control=service(request,True,safe_control=True);control.observe(body.adapter,body.symbol)
            return {'observation_started':True,'execution_started':False}
        return run(apply)
    @app.post('/api/trading/sessions/propose')
    def propose(body:Proposal,request:Request):
        return run(lambda:service(request,True,safe_control=True).propose(body.adapter,body.symbol,body.seconds,body.limits,close_order_id=body.close_order_id))
    @app.post('/api/trading/sessions/activate')
    def activate(body:Activation,request:Request):
        return run(lambda:service(request,True).activate(body.id,body.spec_hash,clear_stop=body.clear_emergency_stop))
    @app.post('/api/trading/sessions/stop')
    def stop(body:Stop,request:Request):
        return run(lambda:service(request,True,safe_control=True).stop(body.id,emergency=body.emergency))
    @app.post('/api/trading/sessions/alerts/{ident}/delivered')
    def delivered(ident:str,request:Request):
        return run(lambda:service(request,True).acknowledge_alert(ident) or {'recorded':True})


def register_market_desk(app,factory):
    """Serve the bundled desk on the authoritative Core, without another port."""
    import threading
    class HostedDesk:
        def __init__(self):self.inner=None;self.lock=threading.Lock()
        async def __call__(self,scope,receive,send):
            if self.inner is None:
                with self.lock:
                    if self.inner is None:self.inner=factory()
            await self.inner(scope,receive,send)
        def shutdown(self):
            if self.inner is not None:
                worker=self.inner.state.demo_autotrader;worker.stop()
                if worker.worker:worker.worker.join(timeout=20)
    hosted=HostedDesk();app.mount('/market-desk',hosted)
    return hosted
