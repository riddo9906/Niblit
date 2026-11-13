"""Read-only position intelligence. Core authorizes analysis; existing outbox owns evidence."""
import hashlib,json,math,sqlite3,threading,time
from pathlib import Path
from modules.strategy_manager import assess_observation

def digest(value):return hashlib.sha256(json.dumps(value,sort_keys=True,allow_nan=False).encode()).hexdigest()
def number(v):
    if isinstance(v,bool):raise ValueError('Boolean numeric evidence')
    v=float(v)
    if not math.isfinite(v):raise ValueError('Nonfinite numeric evidence')
    return v

def reconcile_position(position,ledger):
    try:
        with sqlite3.connect(Path(ledger).resolve().as_uri()+'?mode=ro',uri=True) as db:
            db.row_factory=sqlite3.Row
            row=db.execute('SELECT * FROM trades WHERE id=?',(position['trade_id'],)).fetchone()
            if not row:return {'state':'missing_engine_record','broker_fill_verified':False}
            fields={'pair':'pair','open_rate':'open_rate','amount':'amount','is_short':'is_short','is_open':'is_open','strategy':'strategy','stake_amount':'stake_amount','leverage':'leverage'}
            matches=all(row[col]==position.get(key) for key,col in fields.items())
            if position.get('is_open') is False:
                # A closed row is not proof of API-reported profit without matching
                # its recorded exit values as well as its entry identity.
                for key in ('close_rate','close_profit_abs','close_date'):
                    if key in row.keys() and position.get(key) is not None:
                        matches=matches and str(row[key])==str(position[key])
            orders=db.execute('SELECT order_id,status,side,filled FROM orders WHERE ft_trade_id=? ORDER BY id',(position['trade_id'],)).fetchall()
            context=None
            if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='trade_custom_data'").fetchone():
                saved=db.execute("SELECT cd_value FROM trade_custom_data WHERE ft_trade_id=? AND cd_key='niblit_exit_context'",(position['trade_id'],)).fetchone()
                if saved:context=json.loads(saved[0])
        return {'state':'matched_engine_record' if matches else 'record_mismatch','recorded_orders':[dict(x) for x in orders],'recorded_entry_context':context,
                'verification_scope':'Local dry-run engine ledger only; not a live broker fill','broker_fill_verified':False}
    except Exception as exc:return {'state':'unavailable','error_type':type(exc).__name__,'broker_fill_verified':False}

def assess_position(position,market,observation,*,analysis=None,reconciliation=None):
    recorded={k:position.get(k) for k in ('trade_id','pair','is_short','open_date','open_timestamp','open_rate','amount','stake_amount','leverage','strategy','enter_tag','fee_open','fee_open_cost','fee_open_currency','fee_close','fee_close_cost','fee_close_currency','funding_fees','stop_loss_abs','initial_stop_loss_abs','realized_profit','is_open')}
    result={'recorded':recorded,'verified':reconciliation or {'state':'unverified'},'estimated':{},'assessment':'ABSTAIN','execution_authorized':False,
            'original_decision_evidence':'Not linked; entry tag is attribution, not proof of Core approval','realized_result_verified':False,'subsequent_observation':None}
    analysis=analysis if analysis is not None else assess_observation(observation)
    analysis=dict(analysis)
    if 'observation' in analysis:analysis['observation']={k:v for k,v in analysis['observation'].items() if k not in ('as_of','age_seconds','received_at')}
    result['strategies']=analysis
    if market.get('fresh') is not True or not analysis.get('assessment_complete'):
        result['reason']=analysis.get('abstain_reason','market_unavailable');return result
    try:
        mark=number(market['last']['close']);entry=number(position['open_rate']);quantity=number(position['amount'])
        if min(mark,entry,quantity)<=0 or not isinstance(position.get('is_short'),bool):raise ValueError('Invalid position')
        if not position['pair'].endswith('/USDT:USDT'):raise ValueError('Only verified linear USDT contract convention supported')
        pnl=(entry-mark if position['is_short'] else mark-entry)*quantity
        estimated={'mark':mark,'mark_type':'completed candle close; not executable quote','source':market['source'],'bar':market['last']['timestamp'],
                   'unrealized_gross_usdt':pnl,'notional_usdt':quantity*mark,'costs_included':False,'realized':False}
        stop=position.get('stop_loss_abs')
        if stop is not None:
            stop=number(stop);estimated['distance_to_recorded_stop_usdt']=(stop-mark if position['is_short'] else mark-stop)*quantity
            estimated['stop_crossed']=mark>=stop if position['is_short'] else mark<=stop
        fee=position.get('fee_close')
        if fee is not None and 0<=number(fee)<=1:estimated['exit_fee_estimate_usdt']=quantity*mark*number(fee)
        result['estimated']=estimated
        signal=analysis.get('signal');opposite='BUY' if position['is_short'] else 'SELL'
        if signal=='ABSTAIN':result.update(assessment='REVIEW',reason=analysis.get('abstain_reason','strategy_disagreement'))
        elif signal==opposite or estimated.get('stop_crossed'):result.update(assessment='EXIT-CANDIDATE',reason='Opposite rule consensus or recorded stop crossed; human review required')
        else:result.update(assessment='HOLD',reason='No complete opposing consensus; continued observation required')
        if result['verified'].get('state')!='matched_engine_record':result.update(assessment='ABSTAIN',reason='Position is not reconciled with engine ledger')
        result['stop_enforcement']='Stop execution is not verified by this read-only observer'
        result['entry_price_comparison']={'mark_change_fraction':mark/entry-1,'basis':'Recorded engine entry versus later public candle; not an executed return'}
        tag=str(position.get('enter_tag') or '').split(':')
        result['entry_condition_comparison']={'entry_context':result['verified'].get('recorded_entry_context'),'entry_conditions_available':bool(result['verified'].get('recorded_entry_context')),'limits':'Entry tag/context is engine evidence, not verified Core approval'}
        result['held_strategy_evaluation']=next((c for c in analysis.get('candidates',[]) if len(tag)>1 and c.get('strategy')==tag[1]),None)
    except (KeyError,TypeError,ValueError,OverflowError) as exc:result.update(assessment='ABSTAIN',reason='Invalid or unsupported valuation evidence',error_type=type(exc).__name__)
    return result

def assess_entry_thesis(position, market, observation, strategies, reconciliation, quote, previous=None):
    """Adapt the original exit evaluator; its close condition is not a grant.

    Only a copy of recorded entry context is advanced. Continuation belongs to
    the observer's already scoped acknowledged cache, never the engine record.
    """
    from copy import deepcopy
    from modules.demo_strategy import STRATEGIES
    from modules.position_exit_policy import assess_exit
    result = {'state':'not_eligible', 'recommendation':'ABSTAIN',
              'execution_authorized':False, 'policy':'position_exit_policy.assess_exit'}
    context = reconciliation.get('recorded_entry_context')
    if reconciliation.get('state') != 'matched_engine_record':
        return {**result, 'reason':'Position ledger is not reconciled'}
    if not isinstance(context,dict) or context.get('strategy') not in STRATEGIES:
        return {**result, 'reason':'No recognized recorded entry thesis; manual management required'}
    tag = str(position.get('enter_tag') or '').split(':')
    if len(tag)>1 and tag[1] != context['strategy']:
        return {**result, 'reason':'Recorded strategy attribution conflicts with entry context'}
    identity = digest([position.get(k) for k in ('trade_id','pair','open_timestamp','open_rate','amount','is_short')] + [context])
    prior = previous if isinstance(previous,dict) and previous.get('context_identity')==identity else {}
    working = deepcopy(prior.get('monitor_context') or context)
    result.update(context_identity=identity, monitor_context=working,
                  reason='Fresh compatible quote and complete strategy comparison required')
    if market.get('fresh') is not True or not strategies.get('assessment_complete'):
        return {**result,'state':'unavailable','reason':'Stale market or incomplete strategy comparison'}
    try:
        if not isinstance(quote,dict) or quote.get('fresh') is not True:
            raise ValueError('Quote unavailable or stale')
        if quote.get('symbol')!=position['pair'] or quote.get('venue')!=observation['venue']:
            raise ValueError('Quote instrument or venue mismatch')
        if quote.get('source')!='ccxt_public_order_book':
            raise ValueError('Authentic public top-of-book source required')
        stamp=number(quote['timestamp']);received=number(quote['received_at'])
        bid=number(quote['bid']);ask=number(quote['ask']);now=time.time()
        if min(stamp,bid,ask)<=0 or ask<bid or not -5<=now-stamp<=15 or not stamp-5<=received<=now+5:
            raise ValueError('Invalid or stale quote evidence')
        if stamp < prior.get('last_quote_timestamp',0):
            raise ValueError('Out-of-order quote evidence')
        if not isinstance(position.get('is_short'),bool):
            raise ValueError('Unknown position direction')
        evaluated=assess_exit({'type':1 if position['is_short'] else 0,'price_open':position['open_rate']},
                              market['candles'],quote,working)
        if 'evidence' not in evaluated:
            return {**result,'state':'unavailable','reason':evaluated['reason']}
        return {**result,'state':'evaluated','recommendation':'EXIT-CANDIDATE' if evaluated['action']=='close' else 'HOLD',
                'reason':evaluated['reason'],'evidence':evaluated['evidence'],
                'limits':evaluated['limits'],'last_quote_timestamp':stamp,
                'quote':{k:quote[k] for k in ('symbol','venue','source','timestamp','bid','ask')},
                'monitor_context':working, 'context_storage':'Observer continuation only; original engine context unchanged'}
    except (KeyError,TypeError,ValueError,OverflowError) as exc:
        return {**result,'state':'unavailable','reason':str(exc) if type(exc) is ValueError else type(exc).__name__,
                'last_quote_timestamp':prior.get('last_quote_timestamp',0)}

class PositionIntelligence:
    """One Core-scheduler job; existing Desk reads and Core memory contracts only."""
    def __init__(self,desk,core_analysis,gateway=None,scope=None):
        self.desk=desk;self.core_analysis=core_analysis;self.gateway=gateway;self.scope=scope or {'namespace':'desktop','principal':'desktop_operator'}
        self.lock=threading.Lock();self.tick_lock=threading.Lock();self.cursor=0;self.stop_event=threading.Event();self.scheduler=None;self.task_id=None;self.owner_file=None;self.scan_count=0;self.latest={'state':'not_observed','positions':[],'execution_authorized':False}
        if gateway:
            with gateway.db() as db:db.execute('CREATE TABLE IF NOT EXISTS position_monitor_cache(id TEXT PRIMARY KEY,payload TEXT NOT NULL)')
    def cache(self,key,value=None):
        if not self.gateway:return None
        self.gateway.require('ingest' if value is not None else 'read',**self.scope)
        with self.gateway.db() as db:
            if value is not None:db.execute('INSERT INTO position_monitor_cache VALUES(?,?) ON CONFLICT(id) DO UPDATE SET payload=excluded.payload',(key,json.dumps(value,sort_keys=True,allow_nan=False)))
            row=db.execute('SELECT payload FROM position_monitor_cache WHERE id=?',(key,)).fetchone()
        return json.loads(row[0]) if row else None
    def closed_outcomes(self,profile,config,open_ids,deadline):
        if not self.gateway:return {'state':'memory_unavailable','events':[]}
        self.gateway.require('read',**self.scope)
        with self.gateway.db() as db:
            rows=db.execute("SELECT id,payload FROM position_monitor_cache WHERE json_extract(payload,'$.scope.account_scope')=? AND json_extract(payload,'$.scope.mode')='dry-run' AND json_extract(payload,'$.scope.principal')=? AND json_extract(payload,'$.scope.namespace')=? ORDER BY rowid DESC LIMIT 64",('freqtrade-profile-'+profile,self.scope['principal'],self.scope['namespace'])).fetchall()
        previous={}
        for key,encoded in rows:
            record=json.loads(encoded);ident=record['recorded'].get('trade_id')
            if ident not in previous:previous[ident]=(key,record)
        if not any(ident not in open_ids for ident in previous):return {'state':'no_removed_positions','events':[]}
        history=self.desk.api('trades?limit=100').get('trades',[]);events=[]
        for closed in history:
            if self.stop_event.is_set() or time.monotonic()>deadline:break
            ident=closed.get('trade_id')
            if closed.get('is_open') is not False or ident not in previous or ident in open_ids:continue
            key,old=previous[ident]
            if closed.get('pair')!=old['recorded'].get('pair') or closed.get('open_timestamp')!=old['recorded'].get('open_timestamp'):continue
            proof=reconcile_position(closed,self.desk.root.parent/'freqtrade/user_data/tradesv3.sqlite')
            opposite='buy' if closed.get('is_short') else 'sell'
            filled=any(o.get('status') in ('closed','filled') and o.get('side')==opposite and float(o.get('filled') or 0)>0 for o in proof.get('recorded_orders',[]))
            event={'trade_id':ident,'pair':closed['pair'],'recorded':{k:closed.get(k) for k in ('strategy','enter_tag','open_rate','amount','stake_amount','leverage','open_timestamp','close_timestamp','close_date','close_rate','profit_abs','close_profit_abs','realized_profit','fee_open_cost','fee_close_cost','funding_fees','exit_reason')},'verification':'engine_confirmed_simulated_close' if proof['state']=='matched_engine_record' and filled else 'unreconciled_close','live_broker_result_verified':False,'execution_authorized':False}
            if old.get('closed_outcome')==event:
                events.append({**event,'memory':old.get('_memory_receipt'),'cached':True});continue
            observation={'symbol':closed['pair'],'venue':config['exchange'],'timeframe':config['timeframe'],'mode':'dry-run','account_scope':'freqtrade-profile-'+profile,'source':'freqtrade_engine_ledger','received_at':time.time(),'fresh':False,'candles':[],
                'position_outcome':event,'previous_episode':old.get('_memory_receipt')}
            response=self.core_analysis(observation);receipt=response.get('memory')
            if receipt and receipt.get('queued'):
                saved={**old,'closed_outcome':event,'_memory_receipt':{k:receipt.get(k) for k in ('id','namespace','source')}};self.cache(key,saved)
            events.append({**event,'memory':receipt,'core_authorization':response.get('authorization')})
        return {'state':'observed','events':events,'missing_history_ids':[ident for ident in previous if ident not in open_ids and not any(e['trade_id']==ident for e in events)]}

    def scan(self):
        if not self.lock.acquire(False):return {'state':'scan_busy','execution_authorized':False}
        try:
            config=self.desk.configuration()
            if config.get('dry_run') is not True:
                self.latest={'state':'unsupported_execution_mode','positions':[],'execution_authorized':False};return self.latest
            profile_path=self.desk.root.parent/'freqtrade/user_data/config.json'
            profile=digest([str(self.desk.root.resolve()),config.get('exchange'),'dry-run',hashlib.sha256(profile_path.read_bytes()).hexdigest() if profile_path.exists() else 'missing_profile'])
            raw=self.desk.api('status');unique={};duplicates=set()
            for p in raw:
                ident=p.get('trade_id')
                if ident in unique:duplicates.add(ident)
                else:unique[ident]=p
            reports=[];deadline=time.monotonic()+90
            items=list(unique.values())
            start=self.cursor%len(items) if items else 0
            ordered=items[start:]+items[:start]
            attempted=0
            for position in ordered[:32]:
                if self.stop_event.is_set() or time.monotonic()>deadline:break
                attempted+=1
                try:
                    pair=position['pair'];market=self.desk.market(pair,config)
                    observation={'symbol':pair,'venue':config['exchange'],'timeframe':config['timeframe'],'mode':'dry-run','account_scope':'freqtrade-profile-'+profile,
                        'source':market.get('source','unavailable'),'received_at':time.time(),'fresh':market.get('fresh') is True,'candles':market.get('candles',[])}
                    verification=reconcile_position(position,self.desk.root.parent/'freqtrade/user_data/tradesv3.sqlite')
                    report=assess_position(position,market,observation,reconciliation=verification)
                    report['scope']={'account_scope':observation['account_scope'],'mode':'dry-run','venue':config['exchange'],'symbol':pair,'principal':self.scope['principal'],'namespace':self.scope['namespace']}
                    report['strategy_inventory']={'core_m5_rules':{'invoked':len(report['strategies'].get('candidates',[])),'policy_version':report['strategies'].get('policy_version'),'abstain_reason':report['strategies'].get('abstain_reason')},'freqtrade_native_wrapper':'Shared audited kernel; native execution callbacks not invoked','lean_1h':'Not eligible for this M5 evaluation','confidence':'Not provided by rule strategies'}
                    key=digest([self.scope,profile,'dry-run',pair,position['trade_id'],position.get('open_timestamp'),position.get('enter_tag'),report['strategies'].get('policy_version')])
                    previous=self.cache(key)
                    if previous and previous.get('recorded')==report['recorded']:
                        prior=previous.get('estimated',{});current=report['estimated']
                        if prior.get('bar')==current.get('bar'):report['subsequent_observation']=previous.get('subsequent_observation')
                        elif current.get('bar',0)>prior.get('bar',float('inf')) and prior.get('mark'):
                            report['subsequent_observation']={'previous_bar':prior['bar'],'current_bar':current['bar'],'public_mark_return':current['mark']/prior['mark']-1,'elapsed_seconds':current['bar']-prior['bar'],'previous_episode':previous.get('_memory_receipt'),'previous_strategy_signal':previous.get('strategies',{}).get('signal'),'unrealized_gross_delta_estimate':current.get('unrealized_gross_usdt',0)-prior.get('unrealized_gross_usdt',0),'verification':'later market observation; not an executed profit','realized':False}
                    quote=None
                    if verification.get('recorded_entry_context') and not self.stop_event.is_set():
                        try:quote=self.desk.quote(pair,config)
                        except Exception as exc:quote={'fresh':False,'reason':type(exc).__name__}
                    thesis=assess_entry_thesis(position,market,observation,report['strategies'],verification,quote,
                                               (previous or {}).get('entry_thesis'))
                    report['entry_thesis']=thesis
                    if thesis['recommendation']=='EXIT-CANDIDATE' and report['assessment']=='HOLD':
                        report.update(assessment='EXIT-CANDIDATE',reason=thesis['reason']+'; advisory only')
                    if position['trade_id'] in duplicates:report.update(assessment='ABSTAIN',reason='Duplicate position records')
                    observation['position_intelligence']=report
                    if self.stop_event.is_set():break
                    core=self.core_analysis(observation)
                    if (core.get('authorization') or {}).get('allowed') is not True:
                        report.update(assessment='ABSTAIN',reason='Core authorization denied or unavailable')
                        report['entry_thesis'].update(recommendation='ABSTAIN',core_denied=True)
                    report['core']={'state':core.get('state'),'authorization':core.get('authorization'),'memory':core.get('memory')}
                    if (core.get('memory') or {}).get('queued'):
                        saved={k:v for k,v in report.items() if k!='core'}
                        saved['_memory_receipt']={k:core['memory'].get(k) for k in ('id','namespace','source')}
                        self.cache(key,saved)
                    reports.append(report)
                except Exception as exc:reports.append({'recorded':{'trade_id':position.get('trade_id'),'pair':position.get('pair')},'assessment':'ABSTAIN','error_type':type(exc).__name__,'execution_authorized':False})
            self.cursor=(start+max(1,attempted))%len(items) if items else 0
            try:outcomes=self.closed_outcomes(profile,config,set(unique),deadline)
            except Exception as exc:outcomes={'state':'unavailable','error_type':type(exc).__name__,'events':[]}
            self.scan_count+=1
            self.latest={'scan_sequence':self.scan_count,'state':'cancelled' if self.stop_event.is_set() else 'observed','checked_at':time.time(),'positions':reports,'duplicates':list(duplicates),'input_count':len(raw),'omitted_count':max(0,len(unique)-attempted),'closed_outcomes':outcomes,'execution_authorized':False,'engine_state':config.get('state')}
            return self.latest
        except Exception as exc:
            self.latest={"state":"unavailable","positions":[],"error_type":type(exc).__name__,"execution_authorized":False};return self.latest
        finally:self.lock.release()
    def start(self,scheduler,interval=120):
        if self.scheduler is not None:return False
        path=self.desk.root/'runtime/trading-desk/position-observer.lock';path.parent.mkdir(parents=True,exist_ok=True);f=path.open('a+b');f.seek(0)
        try:
            if __import__('os').name=='nt':
                import msvcrt
                if path.stat().st_size==0:f.write(b'0');f.flush();f.seek(0)
                msvcrt.locking(f.fileno(),msvcrt.LK_NBLCK,1)
            else:
                import fcntl;fcntl.flock(f.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
        except OSError:f.close();return False
        self.owner_file=f;self.scheduler=scheduler;self.stop_event.clear()
        def work():
            try:
                if not self.stop_event.is_set():self.scan()
            except Exception as exc:self.latest={'state':'recoverable_failure','error_type':type(exc).__name__,'execution_authorized':False}
            finally:
                if not self.stop_event.is_set():
                    self.scheduler.prune_completed('position-observation',keep=2)
                    self.task_id=self.scheduler.submit(tick,label='position-observation',priority=7,delay_secs=max(30,interval))
                elif self.owner_file:self.owner_file.close();self.owner_file=None
                self.tick_lock.release()
        def tick():
            if self.stop_event.is_set() or not self.tick_lock.acquire(False):return
            threading.Thread(target=work,name='PositionObservationPass',daemon=True).start()
        self.task_id=scheduler.submit(tick,label='position-observation',priority=7,delay_secs=2);return True
    def stop(self):
        self.stop_event.set()
        if self.scheduler and self.task_id:self.scheduler.cancel(self.task_id)
        if not self.lock.locked() and not self.tick_lock.locked() and self.owner_file:self.owner_file.close();self.owner_file=None
