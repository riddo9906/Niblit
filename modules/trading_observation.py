"""Bounded integration of existing observers; no trading transport is exposed.

Only a deployment-owned profile enables collection. Chat cannot supply paths,
accounts, endpoints, symbols, credentials or executable arguments.
"""
import datetime
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import uuid


class ReadOnlyMT5:
    METHODS = frozenset(('account_info','terminal_info','symbols_get','symbol_info',
        'symbol_info_tick','copy_rates_from_pos','positions_get','orders_get',
        'order_calc_margin','order_calc_profit'))

    def __init__(self, api): self.__api=api

    def __getattr__(self,name):
        if name in self.METHODS or name.startswith(('TIMEFRAME_','ACCOUNT_TRADE_MODE_','ORDER_TYPE_')):
            return getattr(self.__api,name)
        raise PermissionError('MT5 operation outside observation allowlist')


def profile():
    path=Path(os.environ['NIBLIT_OBSERVATION_PROFILE'])
    if not path.is_absolute() or path.is_symlink():raise PermissionError('Explicit trusted profile required')
    data=json.loads(path.read_text(encoding='utf-8'))
    if data.get('execution_state')!='DENIED':raise PermissionError('Execution must remain denied')
    return data


def scope():
    return {'namespace':os.environ['NIBLIT_MEMORY_LAB_NAMESPACE'],
            'principal':os.environ['NIBLIT_MEMORY_LAB_PRINCIPAL']}


def gateway():
    from modules.memory_laboratory.context import runtime_gateway
    value=runtime_gateway()
    if value is None:raise PermissionError('Canonical memory unavailable')
    value.require('read',**scope())
    return value


def recall_observations(review=False):
    value=gateway(); reports=[]
    with value.db() as db:
        rows=db.execute("SELECT record_id,timestamp,metadata FROM audit WHERE action=? "
            "AND json_extract(metadata,'$.namespace')=? AND json_extract(metadata,'$.principal')=? "
            "ORDER BY seq DESC LIMIT 6",('trading.execution_review' if review else 'trading.observation',*scope().values())).fetchall()
    for row in rows:
        data=json.loads(row['metadata'])
        reports.append({'platform':data['observation']['platform'],'record_id':row['record_id'],'recorded_at':row['timestamp'],
            'citation':'trading-observation://'+row['record_id'],'observation':data['observation']})
    for platform in ('mt5','freqtrade'):
        selected=[r for r in reports if r['platform']==platform]
        if len(selected)>=2:
            newest,previous=selected[:2]
            if not newest['observation'].get('market_fingerprint') or not previous['observation'].get('market_fingerprint'):
                newest['observation']['findings'].append('Change comparison UNKNOWN: one observation lacks verified market evidence.')
                continue
            changed=newest['observation'].get('market_fingerprint')!=previous['observation'].get('market_fingerprint')
            newest['observation']['findings'].append(
                ('Market/valuation evidence changed' if changed else 'Repeated observation of unchanged market/valuation evidence')+
                '; compared with '+previous['citation']+'. This is not a trade or proof of predictive improvement.')
    return {'status':'recorded_observations' if reports else 'UNKNOWN','reports':reports,
        'execution_state':'DENIED','limitation':'Timestamped observations, not an execution grant or continuous live feed.'}


def observe_trading(review=False,platform='all'):
    if type(review) is not bool or platform not in ('all','mt5','freqtrade'):raise ValueError('Unsupported review scope')
    from modules.permission_manager import PermissionManager
    if not PermissionManager().check('command.observe_trading'):
        raise PermissionError('Observation permission required')
    value=gateway();value.require('ingest',**scope());profile()
    # Fixed source-owned worker and inherited isolated environment; no shell.
    args=[sys.executable,'-B',str(Path(__file__).resolve()),'--collect']
    if review:args+=['--review',platform]
    result=subprocess.run(args,
        capture_output=True,text=True,timeout=150,check=False)
    if result.returncode: return {'error':'observation_worker_failed','execution_state':'DENIED'}
    try:return json.loads(result.stdout.strip().splitlines()[-1])
    except (ValueError,IndexError):return {'error':'invalid_observation_receipt','execution_state':'DENIED'}


def instrument_candidates(bridge,api):
    """Bounded visible-symbol comparison; never selects/activates a symbol."""
    bridge.connect();rows=[];first={}
    priorities={('EUR','USD'):0,('GBP','USD'):1,('USD','JPY'):2,('XAU','USD'):3,('BTC','USD'):4}
    symbols=sorted((v for v in (api.symbols_get() or ()) if v.visible and
        (getattr(v,'currency_base',None),getattr(v,'currency_profit',None)) in priorities),
        key=lambda v:priorities[(v.currency_base,v.currency_profit)])[:6]
    for info in symbols:first[info.name]=api.symbol_info_tick(info.name)
    if symbols:time.sleep(2)
    for info in symbols:
        item={'symbol':info.name,'volume_min':info.volume_min,'volume_step':info.volume_step,
            'trade_mode':info.trade_mode,'execution_authorized':False}
        try:
            tick=api.symbol_info_tick(info.name);prior=first[info.name]
            stamp=(tick.time_msc or tick.time*1000)/1000
            previous=(prior.time_msc or prior.time*1000)/1000
            fresh=0<=time.time()-stamp<=15 and stamp>previous and 0<tick.bid<=tick.ask
            margin=api.order_calc_margin(api.ORDER_TYPE_BUY,info.name,info.volume_min,tick.ask)
            item.update(bid=tick.bid,ask=tick.ask,timestamp=stamp,fresh=fresh,margin_at_minimum=margin,
                eligible_for_proposal_review=fresh and info.trade_mode==4 and 0<info.volume_min<=.01 and margin is not None and margin>=0)
        except Exception as exc:item.update(fresh=False,eligible_for_proposal_review=False,error_type=type(exc).__name__)
        rows.append(item)
    bridge.connect()
    eligible=sorted((v for v in rows if v.get('eligible_for_proposal_review')),key=lambda v:v['margin_at_minimum'])
    return {'candidates':rows,'provisional_symbol':eligible[0]['symbol'] if eligible else None,
        'selection_basis':'Visible supported major FX/gold/BTC candidates, verified advancing UTC quote, minimum compliant size, lowest native margin among qualifying reads; not a safety/profit recommendation',
        'execution_authorized':False,'complete_costs_required':True}


def mt5_execution_review(bridge,api,result):
    from modules.trading_values import number
    from modules.crypto_stops import from_mt5
    from modules.core_trading_sessions import configured_limits
    from modules.trading_session_adapters import mt5_trade_costs,account_exposure
    _,account,terminal=bridge.connect()
    symbol=result['symbol'];info=api.symbol_info(symbol);quote=result['quote']
    specifications={k:getattr(info,k,None) for k in ('trade_mode','trade_exemode','order_mode','filling_mode',
        'trade_contract_size','trade_tick_size','trade_tick_value','volume_min','volume_max','volume_step',
        'point','digits','trade_stops_level','trade_freeze_level','swap_mode','swap_long','swap_short','swap_rollover3days',
        'currency_base','currency_profit','currency_margin','trade_tick_value_profit','trade_tick_value_loss')}
    limits=configured_limits();budget=min(account.equity*limits['risk_fraction'],limits['risk_cash'])
    blockers=['External execution authorization DENIED','No account-scoped execution session or delivery lease',
        'Verified prospective commission, financing and slippage bounds unavailable']
    if info.trade_mode!=4:blockers.append('Symbol is not fully tradable; direction-specific restrictions require verification')
    if result['strategy_comparison'].get('signal') not in ('BUY','SELL'):
        blockers.append('No eligible entry consensus: '+str(result['strategy_comparison'].get('abstain_reason','no qualifying setup')))
    if result['positions']:blockers.append('Current position stop risk requires full account reconciliation before a new entry')
    permissions={'terminal_trade_allowed':terminal.trade_allowed,'python_trading_disabled':terminal.tradeapi_disabled,
        'account_trade_allowed':account.trade_allowed,'account_expert_allowed':getattr(account,'trade_expert',None)}
    if not terminal.trade_allowed or terminal.tradeapi_disabled or not account.trade_allowed:
        blockers.append('Current terminal/account execution permission disabled')
    findings=[f"Native symbol constraints: {json.dumps(specifications,sort_keys=True)}",
        f"Current spread {quote.get('spread')} price units; quote freshness verified at this read={result['fresh']}.",
        'Cost provenance: quote/specification/swap rates are broker observations; margin and P&L are broker-calculated estimates in account currency. Commission schedule is unavailable from inspected APIs; slippage/holding-cost bounds were not supplied.',
        'Margin is collateral, not maximum loss. Existing shared mt5_trade_costs embeds spread in executable prices; spread is not subtracted twice. Exact-stop modeled losses do not guarantee stop fills.',
        f"Candidate policy risk ceiling min(equity × {limits['risk_fraction']}, {limits['risk_cash']}) = {budget:.8f} {account.currency}; not an active account grant."]
    if not result['fresh'] or not 0<=time.time()-quote['timestamp']<=15:blockers.append('Stale/unverified quote')
    scenarios=[]
    for side,kind in (('buy',api.ORDER_TYPE_BUY),('sell',api.ORDER_TYPE_SELL)):
        scenario={'side':side,'volume':specifications['volume_min'],'costs_complete':False,'complete_net_outcome':'UNKNOWN'}
        try:
            volume=number(info.volume_min,'broker minimum volume',positive=True)
            if volume>.01 or info.volume_step<=0:raise ValueError('Minimum size exceeds bounded review profile')
            entry=quote['ask'] if side=='buy' else quote['bid'];reverse=quote['bid'] if side=='buy' else quote['ask']
            margin=number(api.order_calc_margin(kind,symbol,volume,entry),'broker margin')
            selected=next((c['strategy'] for c in result['strategy_comparison'].get('candidates',[]) if c.get('side')==side),'crypto_default')
            protection=from_mt5(api,symbol,info,quote,side,selected)
            shared=mt5_trade_costs(api,account,symbol,side,volume,
                {'price':entry,'stop_loss':protection['stop_loss'],'take_profit':protection['take_profit']},quote)
            spread_pnl=-number(shared['spread_cost_estimate'],'broker spread loss')
            stop=number(shared['gross_at_stop'],'broker stop P&L');target=number(shared['gross_at_target'],'broker target P&L')
            if margin<0 or spread_pnl>0 or stop>=0 or target<=0:raise ValueError('Invalid broker risk calculation')
            costs=shared['net_evaluation']
            scenario.update(margin_estimate=margin,spread_loss_estimate=-spread_pnl,gross_stop_pnl=stop,
                gross_target_pnl=target,protection=protection,net_cost_review=costs,
                shared_cost_evidence=shared,notional_exposure_account_currency=account_exposure(api,info,symbol,volume,entry,account.currency),
                risk_semantics='Margin is collateral, not maximum loss. Exact-stop P&L is modeled, not guaranteed; spread already embedded, not charged twice.',
                margin_fits=margin<=account.margin_free,gross_stop_within_policy=-stop<=budget,
                margin_within_candidate_ceiling=account.margin+margin<=account.equity*limits['max_margin_fraction'],
                assumption='Broker calculations at exact displayed/stop/target prices; not fills; no costs assumed zero')
            if margin>account.margin_free:blockers.append(side+': insufficient margin')
            if account.margin+margin>account.equity*limits['max_margin_fraction']:
                blockers.append(side+': margin exceeds candidate policy ceiling')
            if -stop>budget:blockers.append(side+': gross stop risk exceeds candidate ceiling')
            findings.append(f"Hypothetical {side} {volume} lots: margin {margin:.8f}, spread loss {(-spread_pnl):.8f}, gross stop P&L {stop:.8f}, gross target P&L {target:.8f} {account.currency}. Complete net outcome UNKNOWN.")
        except Exception as exc:
            scenario['error_type']=type(exc).__name__;blockers.append(side+': instrument/cost preflight incomplete')
        scenarios.append(scenario)
    bridge.connect() # Repeat exact demo binding after read-only calculations.
    return {'eligibility':'BLOCKED','execution_authorized':False,'specifications':specifications,
        'scenarios':scenarios,'configured_candidate_limits':limits,'policy_risk_budget':budget,
        'commission':'UNKNOWN','future_financing':'UNKNOWN; broker swap fields retained without an assumed holding period',
        'slippage':'UNKNOWN','broker_order_acceptance':'UNKNOWN; order_check not invoked',
        'terminal_permissions':permissions,
        'filling_flags_reported':[label for bit,label in ((1,'FOK'),(2,'IOC'),(4,'BOC')) if (specifications.get('filling_mode') or 0)&bit],
        'filling_acceptance':'Raw symbol flags only; per-request acceptance UNKNOWN; RETURN not inferred',
        'minimum_stop_distance_price':info.point*info.trade_stops_level,
        'freeze_distance_price':info.point*info.trade_freeze_level,
        'current_margin':account.margin,'free_margin':account.margin_free,
        'open_stop_risk':0 if not result['positions'] else None,
        'account_exposure_basis':'Current native positions in the enclosing receipt; no position means zero open exposure at that read',
        'cost_provenance':[
            {'field':'quote_and_specification','classification':'BROKER_OBSERVED','source':'MT5 symbol_info_tick/symbol_info','asof':quote['timestamp']},
            {'field':'margin','classification':'BROKER_CALCULATED_ESTIMATE','source':'order_calc_margin','currency':account.currency,'maximum_loss':False},
            {'field':'spread_stop_target','classification':'BROKER_CALCULATED_ESTIMATE','source':'existing mt5_trade_costs/order_calc_profit','currency':account.currency,'spread_double_counted':False},
            {'field':'notional_conversion','classification':'BROKER_VALUE_OR_SAME_CURRENCY','source':'existing account_exposure','currency':account.currency},
            {'field':'protective_levels','classification':'MODEL_ESTIMATE','source':'existing crypto ATR/structure policy; exact price fill assumed'},
            {'field':'commission','classification':'UNAVAILABLE_FROM_PROVIDER','source':'No prospective schedule exposed by inspected account/symbol interfaces; historical deals do not establish a future schedule'},
            {'field':'swap_rate','classification':'BROKER_OBSERVED','source':'symbol_info swap_mode/long/short/rollover3days','holding_cost_bound':'UNKNOWN'},
            {'field':'slippage_financing_bound','classification':'REQUIRES_SEPARATE_USER_AUTHORIZATION','source':'No attributable conservative model bound supplied; no guaranteed slippage inferred'}],
        'blockers':blockers,'findings':findings}


def freqtrade_execution_review(desk,positions,config,private,raw_config,actuals,replay=None,config_hash=None,monitor=None):
    from modules.trading_values import linear_exit_estimate,fee_resolution
    from modules.position_intelligence import strategy_ownership
    blockers=['External dry-run/live execution authorization DENIED','No Core account-scoped execution session',
        'Effective prospective simulation fee, future funding and slippage bounds not verified; live account-tier costs also UNKNOWN']
    if config['strategy']!='NiblitCoreManaged':blockers.append('Native strategy ownership differs from Core-managed entry pathway')
    if config['state']!='running':blockers.append('Engine stopped; automatic activation not permitted')
    if len(positions)>=config['max_open_trades']:blockers.append('New-entry position capacity exhausted; this is not exit authorization')
    source_config={k:raw_config.get(k) for k in ('fee','stoploss','minimal_roi','stake_amount',
        'max_open_trades','position_adjustment_enable','tradable_balance_ratio','trading_mode','margin_mode')}
    source_config['private_tradable_balance_ratio']=private.get('tradable_balance_ratio')
    findings=[f"Native strategy {config['strategy']}; Core entry requires NiblitCoreManaged; no ownership transfer performed.",
        f"Simulation/API settings (not exchange account fees): {json.dumps(source_config,sort_keys=True)}.",
        f"Private configured simulation fee override: {private.get('fee','UNKNOWN')}; API prospective fee: {raw_config.get('fee','UNKNOWN')}."]
    pair_reviews=[]
    for position in positions:
        pair=position['pair'];quote=desk.quote(pair,config)
        item={'trade_id':position['trade_id'],'pair':pair,'quote':quote,'pair_rules':None,
            'entry_fee_paid':position.get('fee_open_cost'),'closing_rate_historical_assumption':position.get('fee_close'),
            'funding_recorded':position.get('funding_fees'),'future_funding':'UNKNOWN','slippage':'UNKNOWN'}
        item['public_simulation_fee_reference']={'market':{k:(quote.get('public_market') or {}).get(k) for k in ('maker','taker')},
            'defaults':quote.get('public_default_fees'),'provenance':quote.get('fee_provenance'),
            'effective_native_fee_verified':False}
        item['fee_resolution']=fee_resolution(symbol=pair,config_hash=config_hash,private_override=private.get('fee'),
            engine_override=raw_config.get('fee'),quote=quote,replay=replay,now=time.time())
        verified=next((r['verified'] for r in (monitor or {}).get('positions',[]) if r.get('recorded',{}).get('trade_id')==position['trade_id']),{'state':'unverified'})
        item['strategy_ownership']=strategy_ownership(position,verified,config['strategy'],config['state'])
        resolution=item['fee_resolution'];ownership=item['strategy_ownership']
        findings.append(f"Trade {position['trade_id']} fee source: {resolution['status']}, rate {resolution['rate']}; {resolution.get('reason')}. Native process-cache verification=False; no execution fee grant.")
        findings.append(f"Trade {position['trade_id']} ownership: {ownership['owner']}; historical {ownership['historical_strategy']} retained. Core entry decision {ownership['core_entry_decision']}. Core cannot adopt or close this position from an identifier mapping.")
        try:
            if quote.get('fresh') is not True:raise ValueError('Fresh executable top of book unavailable')
            midpoint=(quote['bid']+quote['ask'])/2
            minimum=desk.minimum_stake(pair,config,midpoint)
            rule=desk.market_rules[1][pair.split(':')[0].replace('/','')]
            item.update(pair_rules={k:rule.get(k) for k in ('symbol','status','contractType','marginAsset','quantityPrecision','pricePrecision','filters')},
                pair_rules_source='https://fapi.binance.com/fapi/v1/exchangeInfo',
                minimum_stake_with_adapter_reserve=minimum,minimum_stake_basis='Existing Desk reserves: minQty × price × 1.05 or minNotional × 1.5; not exchange minimum alone')
            if rule.get('status')!='TRADING':blockers.append(pair+': exchange market not TRADING')
            estimate=linear_exit_estimate(entry=position['open_rate'],bid=quote['bid'],ask=quote['ask'],quantity=position['amount'],
                short=position['is_short'],entry_fee=position.get('fee_open_cost'),closing_rate=position.get('fee_close'),
                funding=position.get('funding_fees'),stop=position.get('stop_loss_abs'))
            item['counterfactual_existing_exit']=estimate
            taker=(quote.get('public_market') or {}).get('taker')
            if taker is None:taker=(quote.get('public_default_fees') or {}).get('taker')
            if taker is not None:
                item['public_taker_exit_assumption']=linear_exit_estimate(entry=position['open_rate'],bid=quote['bid'],ask=quote['ask'],quantity=position['amount'],
                    short=position['is_short'],entry_fee=position.get('fee_open_cost'),closing_rate=taker,
                    funding=position.get('funding_fees'),stop=position.get('stop_loss_abs'))
                item['public_taker_exit_assumption']['fee_scope']='Public taker schedule assumption, not verified native effective fee or account-tier rate'
            findings.append(f"Trade {position['trade_id']} {pair}: public bid/ask {quote['bid']}/{quote['ask']} at {quote.get('timestamp')}; spread cost at existing quantity {estimate['spread_cost_at_quantity']:.8f} USDT; hypothetical net excluding unknown costs {estimate['net_excluding_unknown_costs']}; stop crossed={estimate.get('stop_crossed','UNKNOWN')}. No exit executed.")
            findings.append(f"{pair} public simulation fee reference: maker {(quote.get('public_market') or {}).get('maker')}, taker {(quote.get('public_market') or {}).get('taker')}; effective native new-entry fee UNKNOWN. Not an account-tier fee quote.")
            if 'public_taker_exit_assumption' in item:
                findings.append(f"{pair} public-taker exit assumption: net excluding unknown costs {item['public_taker_exit_assumption']['net_excluding_unknown_costs']} USDT. Historical closing-rate estimate above is a separate scenario; neither is a fill or complete net outcome.")
        except Exception as exc:
            item['error_type']=type(exc).__name__;blockers.append(pair+': quote/rules/cost review incomplete')
            findings.append(f"Trade {position['trade_id']} {pair}: execution quote/cost data UNKNOWN ({type(exc).__name__}); eligibility blocked.")
        pair_reviews.append(item)
    return {'eligibility':'BLOCKED','execution_authorized':False,'environment':'verified stopped dry-run',
        'native_configuration':source_config,'pairs':pair_reviews,'blockers':blockers,'findings':findings,
        'account_actuals_reference':actuals['capital'],'prospective_fee':'Native process cache UNVERIFIED; exact installed initial-maker bookkeeping replay is separately attributed, not a future fill or account-tier quote'}


def collect(review=False,selected='all'):
    if type(review) is not bool or selected not in ('all','mt5','freqtrade'):raise ValueError('Unsupported review scope')
    import httpx
    from modules.observation_supervisor import ObservationJob,ObservationSupervisor
    from modules.trading_desk import Desk
    from modules.desktop_market_intelligence import DesktopMarketIntelligence
    from modules.mt5_bridge import MT5Bridge
    from modules.position_intelligence import PositionIntelligence
    from modules.trading_values import freqtrade_actuals
    p=profile();memory=gateway();memory.require('ingest',**scope())
    run='observation-'+uuid.uuid4().hex
    # No inherited exchange keys or cloud deployment client is used.
    cfg=json.loads(Path(p['freqtrade_config']).read_text(encoding='utf-8'))
    if cfg.get('dry_run') is not True:raise PermissionError('Expected dry-run profile')
    auth=(cfg['api_server']['username'],cfg['api_server']['password'])
    allowed={'show_config','status','balance','profit','trades'}
    def transport(path,payload=None):
        from urllib.parse import urlsplit,parse_qs
        parsed=urlsplit(path)
        if payload is not None or parsed.scheme or parsed.netloc or parsed.path not in allowed|{'pair_candles'}:
            raise PermissionError('Freqtrade operation outside GET allowlist')
        if parsed.fragment or '..' in path:raise PermissionError('Invalid read path')
        with httpx.Client(base_url='http://127.0.0.1:8080/api/v1/',auth=auth,trust_env=False,timeout=8) as client:
            response=client.get(path);response.raise_for_status();return response.json()
    denials=[]
    for action in ('forceenter','forceexit','start','stop','reload_config','cancel_open_order'):
        try:transport(action,{});raise AssertionError('Mutation admitted')
        except PermissionError:denials.append('freqtrade.'+action)
    import MetaTrader5 as native
    api=ReadOnlyMT5(native)
    for action in ('order_send','order_check','login','symbol_select','initialize'):
        try:getattr(api,action);raise AssertionError('MT5 mutation admitted')
        except PermissionError:denials.append('mt5.'+action)
    # initialize can launch a terminal: require the intended image already running.
    import psutil
    expected=str(Path(p['mt5_terminal']).resolve()).casefold()
    running=any((proc.info.get('exe') or '').casefold()==expected for proc in psutil.process_iter(['exe']))
    attached=bool(running and native.initialize(p['mt5_terminal'],timeout=5000))
    class BoundBridge(MT5Bridge):
        def connect(self):
            account,terminal=api.account_info(),api.terminal_info()
            if account is None or terminal is None or not terminal.connected:raise PermissionError('Disconnected MT5')
            identity=self.account_record(api,account,terminal)
            if (identity['identity']!=p['mt5_account'] or identity['environment']!='demo'
                or identity['server']!=p['mt5_server']):raise PermissionError('MT5 binding changed')
            return api,account,terminal
    bridge=BoundBridge(api)
    binding={'identity':p['mt5_account'],'terminal_id':'unavailable'}
    mt_error=None
    try:
        if not attached:raise RuntimeError('Existing MT5 attach failed')
        binding=bridge.connection_record()
        bridge.snapshot(p['mt5_symbol']) # Prime local tick-advancement evidence.
        time.sleep(2)
    except Exception as exc:mt_error=type(exc).__name__
    def core_analysis(observation):
        with httpx.Client(trust_env=False,timeout=25) as client:
            port=int(os.environ.get('NIBLIT_API_PORT','5800'))
            if not 1024<=port<=65535:raise PermissionError('Invalid Core observation callback port')
            response=client.post(f'http://127.0.0.1:{port}/api/trading/analysis',
                headers={'Origin':'http://tauri.localhost' if getattr(sys,'frozen',False) else 'http://127.0.0.1:5183'},json={'observation':observation})
            response.raise_for_status();body=response.json()
        meta=body.get('metadata',{});analysis=meta.get('market_analysis')
        if not isinstance(analysis,dict) or analysis.get('execution_authorized') is not False:
            raise PermissionError('Core analysis-only response unavailable')
        return {'state':'analyzed_by_core','analysis':analysis,'authorization':meta.get('authorization'),
                'memory':meta.get('market_memory'),'trace_id':body.get('trace_id'),'execution_authorized':False}
    desk=Desk(root=Path(p['output_root'])/'observer-runtime',transport=transport)
    monitor=PositionIntelligence(desk,core_analysis,memory,scope(),
        ledger_path=p['freqtrade_ledger'],profile_path=p['freqtrade_config'])
    desktop=DesktopMarketIntelligence(bridge,core_analysis)
    def mt(job):
        if mt_error:raise RuntimeError(mt_error)
        result=desktop.observe(job.symbol,job.account,job.terminal)
        result['account'].pop('login',None)
        snap=bridge.snapshot(job.symbol)
        result['account_actuals']=snap['account'];result['positions']=snap['positions']
        result['pending_order_count']=snap['pending_order_count']
        if review:
            result['execution_review']=mt5_execution_review(bridge,api,result)
            result['instrument_candidates']=instrument_candidates(bridge,api)
            chosen=result['instrument_candidates']['provisional_symbol']
            if chosen and chosen!=job.symbol:
                selected=desktop.observe(chosen,job.account,job.terminal);selected['account'].pop('login',None)
                snapshot=bridge.snapshot(chosen)
                selected.update(account_actuals=snapshot['account'],positions=snapshot['positions'],pending_order_count=snapshot['pending_order_count'])
                selected['execution_review']=mt5_execution_review(bridge,api,selected)
                result['selected_instrument_review']=selected
        return result
    ftidentity_full=hashlib.sha256(Path(p['freqtrade_config']).read_bytes()).hexdigest()
    ftidentity=ftidentity_full[:16]
    def ft(job):
        config=desk.configuration()
        if config.get('dry_run') is not True or config.get('state')!='stopped':
            raise PermissionError('Expected stopped dry-run engine; observer will not change it')
        expected={'exchange':cfg.get('exchange',{}).get('name'),'strategy':cfg.get('strategy'),
                  'timeframe':cfg.get('timeframe') or p.get('freqtrade_timeframe'),'stake_currency':cfg.get('stake_currency'),
                  'max_open_trades':cfg.get('max_open_trades'),'trading_mode':cfg.get('trading_mode')}
        if any(expected[k] is None or config.get(k)!=v for k,v in expected.items()):
            raise PermissionError('Freqtrade API and approved profile binding disagree')
        report=monitor.scan();positions=transport('status');balance=transport('balance');profit=transport('profit')
        history=transport('trades?limit=100')
        actuals=freqtrade_actuals(positions,balance,profit,history.get('trades',[]),
            observed_at=datetime.datetime.now(datetime.timezone.utc).isoformat(),mode='dry-run')
        by_strategy={}
        for trade in history.get('trades',[]):
            if trade.get('is_open') is not False:continue
            item=by_strategy.setdefault(trade.get('strategy','UNKNOWN'),{'net_realized':0.,'wins':0,'losses':0})
            amount=trade.get('close_profit_abs')
            if not isinstance(amount,(int,float)):continue
            item['net_realized']+=amount;item['wins']+=int(amount>0);item['losses']+=int(amount<0)
        actuals['closed_strategy_results']=by_strategy
        actuals['drawdown']={k:profit.get(k) for k in ('max_drawdown','max_drawdown_abs','current_drawdown','current_drawdown_abs')}
        actuals['drawdown_basis']='Platform closed-trade curve; continuous marked-equity drawdown not established'
        actuals['gross_notional_at_status_marks']=sum(x['quantity']*x['mark'] for x in actuals['positions'])
        actuals['net_notional_at_status_marks']=sum(x['quantity']*x['mark']*(-1 if x['side']=='short' else 1) for x in actuals['positions'])
        actuals['position_capacity']={'maximum':config.get('max_open_trades'),'occupied':len(positions)}
        result={'connected':True,'account':{'identity':ftidentity,'terminal_id':'freqtrade-loopback-8080'},
            'symbol':job.symbol,'received_at':time.time(),'fresh':False,'engine_state':config['state'],
            'position_monitor':report,'actuals':actuals,'execution_authorized':False,
            'valuation_asof':'UNKNOWN; API cache marks are distinct from public candle observations'}
        if review:
            replay=None;pin=p.get('native_fee_replay')
            if pin:
                try:
                    location=Path(pin['path']).resolve();root=Path(os.environ['NIBLIT_OBSERVATION_PROFILE']).resolve().parent
                    if not location.is_relative_to(root) or location.stat().st_size>131072:raise PermissionError('Invalid fee evidence path')
                    content=location.read_bytes()
                    if hashlib.sha256(content).hexdigest()!=pin['sha256']:raise PermissionError('Fee evidence hash mismatch')
                    replay=json.loads(content)
                except Exception:replay={'error':'pinned_native_fee_evidence_unavailable_or_invalid'}
            result['execution_review']=freqtrade_execution_review(desk,positions,config,cfg,transport('show_config'),actuals,
                replay,ftidentity_full,report)
        return result
    results=[]
    def sink(job,result):
        ident=run+'.'+job.source+('.execution-review' if review else '')
        # Original source observations remain data. Summaries are never facts.
        payload={'platform':job.source,'observed_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),
            'result':result,'execution_state':'DENIED','denial_checks':denials}
        target=Path(p['output_root'])/(ident+'.json')
        target.write_text(json.dumps(payload,indent=2,allow_nan=False),encoding='utf-8')
        summary=summarize(payload)
        with memory.db() as db:
            memory.audit(db,'trading.execution_review' if review else 'trading.observation',ident,**scope(),observation=summary,
                source_type='operational_observation',evidence_sha256=hashlib.sha256(target.read_bytes()).hexdigest(),
                evidence_path=str(target),execution_state='DENIED')
        results.append({'platform':job.source,'record_id':ident,'citation':'trading-observation://'+ident,'observation':summary})
        return {'id':ident,'queued':False,'persisted':True}
    jobs=[ObservationJob('mt5',p['mt5_symbol'],binding['identity'],binding['terminal_id']),
          ObservationJob('freqtrade','existing-positions',ftidentity,'freqtrade-loopback-8080')]
    supervisor=ObservationSupervisor(jobs,{'mt5':mt,'freqtrade':ft},sink=sink)
    try:
        for source in (('mt5','freqtrade') if selected=='all' else (selected,)):supervisor.poll_source(source)
    finally:native.shutdown() # Release this IPC client only, not the terminal process.
    for job in supervisor.status()['jobs']:
        if selected!='all' and job['source']!=selected:continue
        if job['state']=='observed':continue
        ident=run+'.'+job['source']+'.failed'
        observation={'platform':job['source'],'observed_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),
            'summary':'UNKNOWN — observation failed: '+str(job['error_type']),
            'findings':['No current market or position conclusion established. External execution remains DENIED.']}
        with memory.db() as db:
            memory.audit(db,'trading.execution_review' if review else 'trading.observation',ident,**scope(),observation=observation,
                source_type='failed_operational_observation',execution_state='DENIED')
        results.append({'platform':job['source'],'record_id':ident,'citation':'trading-observation://'+ident,'observation':observation})
    return {'status':'observed' if all(j['state']=='observed' for j in supervisor.status()['jobs'] if selected=='all' or j['source']==selected) else 'partial','reports':results,
        'supervisor':supervisor.status(),'execution_state':'DENIED',
        'limitation':'One bounded observation pass. Native Freqtrade engine stays stopped; no execution or continuous feed.'}


def summarize(payload):
    r=payload['result'];platform=payload['platform'];findings=[]
    if platform=='mt5':
        analysis=r['strategy_comparison'];q=r['quote'];a=r['account_actuals']
        text=f"Demo {a['identity']}; {r['symbol']} bid {q.get('bid')} ask {q.get('ask')}; {len(r['positions'])} positions."
        findings=[f"Broker tick timestamp {q.get('timestamp')}; UTC clock verified {r['utc_clock_verified']}; fresh {r['fresh']}.",
            f"Six-rule assessment: {analysis.get('signal')}; {len(analysis.get('candidates',[]))} evaluators; {analysis.get('abstain_reason','')}.",
            f"Balance {a['balance']} / equity {a['equity']} {a['currency']}; account profit {a['profit']}."]
    else:
        c=r['actuals']['capital'];text=f"Dry-run engine {r['engine_state']}; open unrealized {c['open_unrealized']:.8f}; all-strategy realized {c['net_closed_realized']:.8f} USDT."
        findings=[f"Status-mark equity {c['equity_at_status_marks']:.8f}; API marked equity {c['marked_equity_reported']}; quote as-of UNKNOWN."]
        findings.extend(f"Closed {name}: {values['net_realized']:.8f} USDT, {values['wins']} wins / {values['losses']} losses; platform records, not a future-performance claim."
            for name,values in r['actuals'].get('closed_strategy_results',{}).items())
        for item in r['position_monitor'].get('positions',[]):
            record=item.get('recorded',{});strategies=item.get('strategies',{})
            findings.append(f"Trade {record.get('trade_id')} {record.get('pair')}: {item.get('assessment')}; {item.get('reason')}; {len(strategies.get('candidates',[]))} strategy assessments. Advisory only.")
    findings+=['New external entries, exits, modifications and cloud deployments remain DENIED. No order transport is exposed by this observer.']
    if 'execution_review' in r:
        review=r['execution_review']
        findings.extend(review['findings'])
        findings.append('Eligibility: BLOCKED — '+'; '.join(review['blockers']))
    material=({'quote':r['quote'],'positions':r['positions']} if platform=='mt5' else
        {'positions':r['actuals']['positions'],'marks':r['actuals']['capital']})
    # Receipt time and local age counters are not market changes.
    if platform=='mt5':material['quote']={k:r['quote'].get(k) for k in ('bid','ask','timestamp')}
    fingerprint=hashlib.sha256(json.dumps(material,sort_keys=True,allow_nan=False).encode()).hexdigest()
    return {'platform':platform,'observed_at':payload['observed_at'],'summary':text,'findings':findings,
            'market_fingerprint':fingerprint}


if __name__=='__main__':
    sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
    review='--review' in sys.argv
    selected=sys.argv[sys.argv.index('--review')+1] if review else 'all'
    print(json.dumps(collect(review,selected),allow_nan=False))
