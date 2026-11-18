"""Finite risk values shared by Core and its lightweight broker translator."""
import math


def number(value, name, *, positive=False):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or (positive and value <= 0):
        raise ValueError('Unverified numeric ' + name)
    return float(value)


def fee_resolution(*,symbol,config_hash,private_override=None,engine_override=None,quote=None,replay=None,now):
    """Resolve a fee's meaning, not execution permission or a live fee cache.

    A maker/taker difference is not a conflict. Compare the same liquidity role
    only. Installed-code replay never becomes engine-process verification.
    """
    quote=quote or {};replay=replay or {}
    result={'status':'UNKNOWN','rate':None,'execution_fee_verified':False,
        'running_process_cache_verified':False,'execution_authorized':False,
        'private_override':private_override,'engine_override':engine_override,
        'public_market_rates':{k:(quote.get('public_market') or {}).get(k) for k in ('maker','taker')},
        'public_default_rates':quote.get('public_default_fees'),
        'historical_fees_eligible_for_selection':False}
    def rate(value):
        value=number(value,'fee rate')
        if not 0<=value<=.01:raise ValueError('Invalid fee rate')
        return value
    try:
        known=[rate(v) for v in (private_override,engine_override) if v is not None]
        if len(known)==2 and abs(known[0]-known[1])>1e-12:
            return {**result,'status':'CONFLICT','reason':'File and engine-reported overrides differ'}
        if known:
            return {**result,'status':'EXPLICIT_CONFIGURATION','rate':known[0],
                'selection_source':'engine_reported_override' if engine_override is not None else 'configured_file_override',
                'reason':'Explicit zero is distinguished from fallback zero; current native process/cache still requires binding verification'}
        if not replay:return {**result,'reason':'Public references alone do not verify native fee selection'}
        import datetime
        stamp=datetime.datetime.fromisoformat(replay['observed_at']).timestamp()
        if not 0<=now-stamp<=900:return {**result,'status':'STALE','reason':'Installed fee replay expired'}
        if replay.get('config_sha256')!=config_hash:
            return {**result,'status':'BINDING_MISMATCH','reason':'Replay configuration identity differs'}
        row=next((r for r in replay.get('records',[]) if r.get('symbol')==symbol and r.get('purpose')=='native_entry_bookkeeping'),None)
        if row is None:return {**result,'reason':'Exact native-entry call was not replayed'}
        selected=rate(row['rate']);maker=(quote.get('public_market') or {}).get('maker')
        default=(quote.get('public_default_fees') or {}).get('maker')
        if selected==0 and row.get('market_maker') is None and (row.get('default_fees') or {}).get('maker') is None:
            return {**result,'status':'ZERO_FALLBACK_REJECTED','reason':'Missing fee metadata must not become verified zero'}
        reference=maker if maker is not None else default
        if reference is not None and abs(rate(reference)-selected)>1e-12:
            return {**result,'status':'CONFLICT','reason':'Installed native-maker replay and current public maker reference differ; refresh/reconcile snapshots'}
        return {**result,'status':'INSTALLED_CODE_REPLAY','rate':selected,
            'selection_source':'installed native entry get_fee(symbol, taker_or_maker=maker)',
            'replay_observed_at':replay['observed_at'],'installed_ccxt_version':replay.get('ccxt_version'),
            'method_sha256':replay.get('method_sha256'),
            'reason':'Exact installed code/config replay verified; in-process cached markets and future entry remain unverified'}
    except (ValueError,TypeError,KeyError,StopIteration):
        return {**result,'status':'INVALID','reason':'Invalid/unavailable fee provenance; no zero substitution'}


def linear_exit_estimate(*,entry,bid,ask,quantity,short,entry_fee,closing_rate,funding,stop):
    """Counterfactual at public top-of-book, not a fill or complete cost quote.

    Reuse only observed position costs; never authorize a new entry from them.
    Unknown costs propagate instead of silently becoming zero.
    """
    entry,bid,ask,quantity=[number(v,n,positive=True) for v,n in
        ((entry,'entry'),(bid,'bid'),(ask,'ask'),(quantity,'quantity'))]
    if ask<bid or type(short) is not bool:raise ValueError('Invalid quote or direction')
    price=ask if short else bid
    gross=(entry-price if short else price-entry)*quantity
    result={'exit_price_assumption':price,'spread_cost_at_quantity':(ask-bid)*quantity,
        'gross_if_closed_at_book':gross,'net_excluding_unknown_costs':None,
        'complete_net_outcome':'UNKNOWN','execution_authorized':False,
        'basis':'Linear USDT quantity; displayed top of book, no fill/depth guarantee; slippage and future funding UNKNOWN'}
    if all(v is not None for v in (entry_fee,closing_rate,funding)):
        fee=number(entry_fee,'observed entry fee');rate=number(closing_rate,'historical closing rate')
        credit=number(funding,'observed funding')
        if fee<0 or not 0<=rate<=.01:raise ValueError('Invalid historical fees')
        result.update(estimated_closing_fee=price*quantity*rate,
            net_excluding_unknown_costs=gross-fee-price*quantity*rate+credit)
    if stop is not None:
        stop=number(stop,'recorded stop',positive=True)
        result.update(recorded_stop=stop,stop_crossed=price>=stop if short else price<=stop,
            gross_loss_from_entry_at_exact_stop=max(0,(stop-entry if short else entry-stop)*quantity),
            stop_fill_assumption='Exact recorded stop price; gap/slippage/future funding/commission not bounded')
    return result


def freqtrade_actuals(positions, balance, profit, closed, *, observed_at, mode):
    """Reconcile observed simulation actuals, never authorize an entry.

    Open profit includes an ESTIMATED closing fee, not a realized closing fill.
    Balance.total is already marked equity: adding open profit again is wrong.
    Independently sampled API valuations can differ; retain that discrepancy.
    """
    result={'schema_version':'niblit.trading.actuals/1','platform':'freqtrade',
        'mode':mode,'observed_at':observed_at,'price_as_of':'UNKNOWN',
        'execution_authorized':False,'positions':[],'issues':[],'realized_by_strategy':{}}
    for p in positions:
        row={'trade_id':p.get('trade_id'),'symbol':p.get('pair'),'strategy':p.get('strategy'),
            'entry_tag':p.get('enter_tag'),'side':'short' if p.get('is_short') else 'long',
            'entry_timestamp':p.get('open_date'),'source':'Freqtrade status; original simulation ledger',
            'entry':p.get('open_rate'),'mark':p.get('current_rate'),'quantity':p.get('amount'),
            'unrealized_reported':p.get('profit_abs'),'realized_partial':p.get('realized_profit'),
            'entry_fee_paid':p.get('fee_open_cost'),'closing_fee_paid':p.get('fee_close_cost'),
            'funding_credit':p.get('funding_fees'),'calculation_verified':False}
        try:
            quantity=number(p['amount'],'filled amount',positive=True)
            entry=number(p['open_rate'],'entry fill',positive=True)
            mark=number(p['current_rate'],'valuation mark',positive=True)
            opening_fee=number(p['fee_open_cost'],'entry fee')
            closing_rate=number(p['fee_close'],'estimated closing fee rate')
            funding=number(p['funding_fees'],'funding credit')
            if opening_fee<0 or not 0<=closing_rate<=.01:raise ValueError('Unverified fees')
            gross=(-1 if p.get('is_short') else 1)*(mark-entry)*quantity
            exit_estimate=mark*quantity*closing_rate
            net=gross-opening_fee-exit_estimate+funding
            reported=number(p['profit_abs'],'reported open profit')
            row.update(gross_at_mark=gross,closing_fee_estimate=exit_estimate,
                net_at_mark=net,calculation_verified=abs(net-reported)<=1e-7,
                fee_scope='Observed historical entry cost and closing estimate for THIS position only; not a new-entry fee quote')
            if not row['calculation_verified']:result['issues'].append('position_pnl_mismatch:'+str(p.get('trade_id')))
        except (KeyError,TypeError,ValueError):result['issues'].append('position_actuals_incomplete:'+str(p.get('trade_id')))
        result['positions'].append(row)
    try:
        floating=sum(number(p['profit_abs'],'open profit') for p in positions)
        realized=number(profit['profit_closed_coin'],'closed profit')
        equity=number(balance['total'],'platform marked equity')
        wallet=next(c for c in balance['currencies'] if c.get('currency')==balance.get('stake') and not c.get('is_position'))
        cash=number(wallet['balance'],'cash balance')
        committed=number(wallet['used'],'committed capital');free=number(wallet['free'],'available capital')
        result['capital']={'available':free,'committed':committed,'cash_balance':cash,
            'cash_reconciles':abs(cash-free-committed)<=1e-7,'marked_equity_reported':equity,
            'equity_at_status_marks':cash+floating,'valuation_discrepancy':equity-(cash+floating),
            'starting_capital_reported':balance.get('starting_capital'),
            'net_closed_realized':realized,'open_unrealized':floating,
            'combined_pnl':realized+floating,'currency':balance.get('stake')}
        if abs(equity-cash-floating)>1e-7:result['issues'].append('independently_sampled_valuation_discrepancy; source quote timestamps unavailable')
    except (KeyError,TypeError,ValueError,StopIteration):result['issues'].append('capital_reconciliation_incomplete')
    for trade in closed:
        if trade.get('is_open') is not False:continue
        try:net=number(trade.get('close_profit_abs',trade.get('profit_abs')),'closed net')
        except ValueError:continue
        key=trade.get('strategy') or 'UNKNOWN'
        result['realized_by_strategy'][key]=result['realized_by_strategy'].get(key,0.)+net
    closed_count=sum(t.get('is_open') is False for t in closed)
    reported_count=profit.get('closed_trade_count')
    result['closed_history_records_used']=closed_count
    result['closed_history_complete']=(closed_count==reported_count if type(reported_count) is int else 'UNKNOWN')
    result['strategy_attribution_scope']='Provided closed records; completeness must match provider count before treating as all-history attribution'
    if result['closed_history_complete'] is False:result['issues'].append('partial_closed_history; strategy attribution is limited to provided records')
    result['performance_limit']='Mixed-strategy history and open estimated profit are not a verified strategy return. No probability calibration claimed.'
    return result
