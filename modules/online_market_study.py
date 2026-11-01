"""Prequential market comparer. Forecast first; score only later observations.

The small fixed predictor menu is the only tuning surface. No order API, LLM,
generated code, mutable risk limit, or platform manipulation capability exists.
"""
import hashlib
import json
import math
import sqlite3
import statistics as stats
import threading
import time

GATE = threading.Lock()
MODELS = ('zero', 'momentum_5', 'momentum_20', 'reversion_5')


def forecasts(prices):
    returns=[b/a-1 for a,b in zip(prices[:-1],prices[1:])]
    short=stats.mean(returns[-5:]);long=stats.mean(returns[-20:])
    return {'zero':0.,'momentum_5':short,'momentum_20':long,'reversion_5':-short}


def choose(rows):
    """Select on an older prefix; require improvement on a later suffix.

    These samples are immutable live-issued shadow forecasts, not refits on the
    present history. Reused holdouts are disclosed; this is not final validation.
    """
    rows=rows[-100:]
    base={'selected':'zero','execution_eligible':False,'samples':len(rows),
          'tunable':list(MODELS),'reason':'Need 40 settled shadow forecasts before adaptation'}
    if len(rows)<40:return base
    split=int(len(rows)*.7);train=rows[:split];test=rows[split:]
    def mae(group,model):return stats.mean(abs(r['predictions'][model]-r['realized']) for r in group)
    ranked=sorted(MODELS,key=lambda m:(mae(train,m),MODELS.index(m)))
    candidate=ranked[0];baseline=mae(test,'zero');candidate_error=mae(test,candidate)
    accepted=candidate!='zero' and baseline>0 and candidate_error<.9*baseline
    return {**base,'selected':candidate if accepted else 'zero','candidate':candidate,
        'training_samples':len(train),'later_check_samples':len(test),
        'training_mae':{m:mae(train,m) for m in MODELS},
        'later_check_mae':{m:mae(test,m) for m in MODELS},
        'reason':'Candidate improved later error by over 10%; research forecast only' if accepted else 'No sufficient later improvement; retain zero-change baseline',
        'validation_limit':'Repeated adaptive monitoring reuses observations. Requires a separate untouched period and costs/fills validation before execution.'}


class OnlineMarketStudy:
    def __init__(self,path):
        self.path=str(path)
        with sqlite3.connect(self.path) as db:
            db.execute('CREATE TABLE IF NOT EXISTS online_predictions(stream TEXT,bar REAL,issued REAL,payload TEXT,PRIMARY KEY(stream,bar))')
            db.execute('CREATE TABLE IF NOT EXISTS online_results(stream TEXT,bar REAL,settled REAL,payload TEXT,PRIMARY KEY(stream,bar))')

    def observe(self,stream,candles,*,market_time,fresh):
        if not GATE.acquire(blocking=False):return {'state':'busy','queued':False,'execution_eligible':False}
        try:return self._observe(stream,candles,market_time,fresh)
        finally:GATE.release()

    def _observe(self,stream,candles,market_time,fresh):
        if not isinstance(stream,str) or not 1<=len(stream)<=300:raise ValueError('Explicit bounded environment identity required')
        rows=candles[-500:]
        prices=[float(r['close']) for r in rows];stamps=[float(r['timestamp']) for r in rows]
        if len(rows)<25:return {'state':'insufficient_history','execution_eligible':False}
        if not all(math.isfinite(v) for v in [*prices,*stamps,float(market_time)]) or min(prices)<=0:raise ValueError('Non-finite market observation')
        if any(b-a!=300 for a,b in zip(stamps[:-1],stamps[1:])):return {'state':'history_gap','execution_eligible':False}
        if not fresh or not 300<=market_time-stamps[-1]<600:return {'state':'stale_or_unfinished','execution_eligible':False}
        available=dict(zip(stamps,prices));bar=stamps[-1]
        with sqlite3.connect(self.path,timeout=5) as db:
            # Score existing issued forecasts before selecting the next version.
            prior=db.execute('SELECT bar,payload FROM online_predictions WHERE stream=? AND bar<? ORDER BY bar DESC LIMIT 500',(stream,bar)).fetchall()
            for origin,encoded in prior:
                record=json.loads(encoded);target=origin+300
                if target not in available or market_time<target+300:continue
                realized=available[target]/record['reference_close']-1
                result={**record,'realized':realized,'absolute_error':abs(record['expected_return']-realized),
                        'baseline_error':abs(realized),'interval_hit':record['lower']<=realized<=record['upper'],
                        'notice':'Return forecast score, not realized trade profit'}
                db.execute('INSERT OR IGNORE INTO online_results VALUES(?,?,?,?)',(stream,origin,time.time(),json.dumps(result)))
            settled=[json.loads(r[0]) for r in db.execute('SELECT payload FROM online_results WHERE stream=? ORDER BY bar DESC LIMIT 100',(stream,)).fetchall()][::-1]
            existing=db.execute('SELECT payload FROM online_predictions WHERE stream=? AND bar=?',(stream,bar)).fetchone()
            manager=choose(settled)
            if existing:
                record=json.loads(existing[0])
            else:
                predicted=forecasts(prices);selected=manager['selected']
                returns=[b/a-1 for a,b in zip(prices[-21:-1],prices[-20:])]
                sigma=stats.pstdev(returns)
                residuals=sorted(abs(r['predictions'][selected]-r['realized']) for r in settled[-60:])
                width=residuals[int(.8*(len(residuals)-1))] if len(residuals)>=20 else 2*sigma
                value=predicted[selected]
                record={'bar':bar,'target_bar':bar+300,'reference_close':prices[-1],
                    'predictions':predicted,'selected':selected,'expected_return':value,
                    'lower':value-width,'upper':value+width,
                    'interval_method':'past residual 80th percentile' if len(residuals)>=20 else 'uncalibrated two-sigma proxy',
                    'pattern':'rising_recently' if predicted['momentum_5']>0 else 'falling_recently' if predicted['momentum_5']<0 else 'flat',
                    'input_hash':hashlib.sha256(json.dumps(rows,sort_keys=True).encode()).hexdigest(),
                    'manager_at_issue':manager,'execution_eligible':False}
                db.execute('INSERT INTO online_predictions VALUES(?,?,?,?)',(stream,bar,time.time(),json.dumps(record)))
        recent=settled[-20:];older=settled[-60:-20]
        recent_mae=stats.mean(r['absolute_error'] for r in recent) if recent else None
        older_mae=stats.mean(r['absolute_error'] for r in older) if older else None
        groups={}
        for pattern in ('rising_recently','falling_recently','flat'):
            subset=[r for r in settled if r['pattern']==pattern]
            groups[pattern]={'samples':len(subset),'mae':stats.mean(r['absolute_error'] for r in subset) if subset else None}
        return {'state':'observing','stream':stream,'forecast':record,'manager':manager,
                'settled':len(settled),'recent_mae':recent_mae,
                'baseline_mae':stats.mean(r['baseline_error'] for r in recent) if recent else None,
                'empirical_interval_coverage':stats.mean(r['interval_hit'] for r in recent) if recent else None,
                'error_drift':bool(older_mae and recent_mae>1.5*older_mae),
                'patterns':groups,'execution_eligible':False,
                'decision_support':{'action':'observe_or_abstain','reason':'Forecast research cannot authorize orders or change risk controls'},
                'limits':'No causal market influence inferred. No profit guarantee. Fixed four-predictor research menu; zero paid inference.'}
