"""Local forecasting and constrained rule synthesis; deliberately no order API.

All labels are next-bar returns. Features at i use only bars through i, and
walk-forward prediction at i uses labels already known at i. Proposal selection
uses a training prefix; the following holdout is not used to select parameters.
This is an exploratory close-to-close study, not a stop/target fill backtest.
"""
import hashlib
import json
import math
import statistics as stats


def feature(prices, i):
    window=prices[i-19:i+1]
    returns=[b/a-1 for a,b in zip(window[:-1],window[1:])]
    dev=stats.pstdev(window)
    return [prices[i]/prices[i-1]-1, prices[i]/prices[i-3]-1,
            prices[i]/prices[i-10]-1,(prices[i]-stats.mean(window))/(dev or 1),stats.pstdev(returns)]


def estimate(samples, x):
    """Training-only scaling and nearest-state empirical next-return estimate."""
    scales=[stats.pstdev([row[0][j] for row in samples]) or 1 for j in range(len(x))]
    neighbors=sorted(samples,key=lambda row:sum(((a-b)/s)**2 for a,b,s in zip(x,row[0],scales)))[:15]
    labels=sorted(row[1] for row in neighbors)
    return stats.mean(labels),labels[int((len(labels)-1)*.1)],labels[int((len(labels)-1)*.9)]


def metrics(values):
    return {'trades':len(values),'net_return_sum':sum(values),
            'mean_net_return':stats.mean(values) if values else None,
            'win_rate':sum(v>0 for v in values)/len(values) if values else None}


def signal(prices, i, rule):
    window=prices[i-rule['lookback']+1:i+1]
    dev=stats.pstdev(window)
    z=(prices[i]-stats.mean(window))/(dev or 1)
    side=1 if z>rule['threshold'] else -1 if z < -rule['threshold'] else 0
    return -side if rule['family']=='reversion' else side


def study(candles, spread_fraction=0., generate=True):
    prices=[float(r['close']) for r in candles[-1000:]]
    stamps=[float(r['timestamp']) for r in candles[-1000:]]
    base={'version':'nearest-state-and-rules-v1','execution_eligible':False,
          'horizon':'next completed M5 close (5 minutes)',
          'limits':'Exploratory recent-window evidence. Not a calibrated probability, guaranteed range or broker fill backtest. No order authority.',
          'proposals':[]}
    if len(prices)<140:
        return {**base,'state':'insufficient_history','reason':'Need 140 contiguous completed M5 candles'}
    if not all(math.isfinite(p) and p>0 for p in prices) or not math.isfinite(spread_fraction) or spread_fraction<0:
        raise ValueError('Invalid research prices or spread')
    if any(b-a!=300 for a,b in zip(stamps[:-1],stamps[1:])):
        return {**base,'state':'history_gap','reason':'No forecast across missing or unordered M5 bars'}
    # Spread is observed now, not historical. 0.5 bp each-way assumed slippage;
    # commission is unknown. Disclose this assumption rather than invent fees.
    cost=spread_fraction+.0001
    samples=[(feature(prices,i),prices[i+1]/prices[i]-1,i) for i in range(20,len(prices)-1)]
    holdout_start=max(80,int(len(prices)*.7))
    predictions=[]
    trace=[]
    for x,y,i in samples:
        if i<holdout_start: continue
        past=[row for row in samples if row[2]<i]
        predicted,_,_=estimate(past,x)
        predictions.append((predicted,y))
        trace.append({'feature_index':i,'max_training_label_index':i,'predicted_return':predicted,
                      'realized_next_return':y,'target_index':i+1})
    predicted,lower,upper=estimate(samples,feature(prices,len(prices)-1))
    mae=stats.mean(abs(p-y) for p,y in predictions)
    baseline=stats.mean(abs(y) for _,y in predictions)
    result={**base,'state':'exploratory','bar':stamps[-1],'reference_close':prices[-1],
            'forecast':{'expected_return':predicted,'neighbor_p10':lower,'neighbor_p90':upper,
                        'training_labels':len(samples),'walk_forward_samples':len(predictions),
                        'walk_forward_mae':mae,'zero_return_baseline_mae':baseline,
                        'improves_zero_baseline':mae<baseline,
                        'direction_accuracy':sum((p>0)==(y>0) for p,y in predictions)/len(predictions),
                        'direction':'up' if predicted>cost else 'down' if predicted < -cost else 'uncertain_after_costs'},
            'cost_assumption':{'observed_spread_fraction':spread_fraction,'round_trip_slippage_fraction':.0001,
                               'total_proxy':cost,'commission':'unknown; not included; validate before promotion'},
            'validation_trace':trace,
            'method':'15 nearest historical states; return/momentum/deviation/volatility features; training-only scaling and expanding walk-forward evaluation.'}
    if not generate: return result
    candidates=[]
    for family in ('momentum','reversion'):
        for lookback in (10,20):
            for threshold in (.75,1.5):
                rule={'family':family,'lookback':lookback,'threshold':threshold}
                training=[];holdout=[]
                for i in range(20,len(prices)-1):
                    side=signal(prices,i,rule)
                    if side:
                        value=side*(prices[i+1]/prices[i]-1)-cost
                        # Purge the boundary label that lands in the holdout.
                        if i+1<holdout_start: training.append(value)
                        elif i>=holdout_start: holdout.append(value)
                train,test=metrics(training),metrics(holdout)
                candidates.append({'id':hashlib.sha256(json.dumps(rule,sort_keys=True).encode()).hexdigest()[:16],
                    'rule':rule,'training':train,'holdout':test,
                    'score':train['mean_net_return'] if train['trades']>=20 else -1.,
                    'hypothesis':'Deviation from a rolling mean may '+('continue with momentum.' if family=='momentum' else 'revert toward the mean.'),
                    'how_created':'Bounded composition of direction family, lookback and deviation threshold; no generated Python execution.',
                    'execution_eligible':False})
    candidates.sort(key=lambda r:r['score'],reverse=True)
    for rank,c in enumerate(candidates):
        c['selected_on_training_only']=rank==0 and c['training']['trades']>=20
        c['assessment']='Research candidate only: needs independent unseen periods, full fees/fill simulation, robustness checks and explicit demo approval.'
        c.pop('score')
    result.update(proposals=candidates,search_trials=len(candidates),
                  selection='Best training-prefix mean net return among rules with 20+ training trades; holdout never changes selection. All trials disclosed.')
    return result
