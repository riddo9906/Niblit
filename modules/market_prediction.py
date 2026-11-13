"""Shadow forecasts and causal outcome evaluation; never execution authority.

Directional continuation is a transparent baseline, not a trained probability model.
All observations use their source clock; unverified UTC alignment prevents issuance.
"""
import hashlib
import json
import math
from datetime import datetime, timezone
from statistics import mean

VERSION = 'market-prediction/1'


def stable(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, allow_nan=False).encode()).hexdigest()


def wilson(wins, count):
    if not count:
        return None
    z=1.95996398454; p=wins/count; denominator=1+z*z/count
    center=(p+z*z/(2*count))/denominator
    half=z*math.sqrt(p*(1-p)/count+z*z/(4*count*count))/denominator
    return [max(0,center-half), min(1,center+half)]


def metrics(rows):
    """Scores only genuine probability forecasts; directional rules remain uncalibrated."""
    n=len(rows); wins=sum(r['correct'] for r in rows)
    probabilistic=[r for r in rows if r.get('probability') is not None]
    result={'samples':n,'directional_accuracy':wins/n if n else None,
            'accuracy_95pct_interval':wilson(wins,n),'interval_assumption':'Descriptive Wilson interval assumes independent outcomes; serial/overlapping market outcomes may violate this', 'brier_score':None,'log_loss':None,
            'calibration_error':None,'calibration_status':'UNCALIBRATED — INSUFFICIENT VALIDATION DATA'}
    if probabilistic:
        for r in probabilistic:
            if not 0<r['probability']<1 or r['actual_up'] not in (0,1):
                raise ValueError('Invalid probabilistic outcome')
        result['brier_score']=mean((r['probability']-r['actual_up'])**2 for r in probabilistic)
        result['log_loss']=-mean(r['actual_up']*math.log(r['probability'])+(1-r['actual_up'])*math.log(1-r['probability']) for r in probabilistic)
        bins=[]
        for i in range(10):
            selected=[r for r in probabilistic if min(9,int(r['probability']*10))==i]
            if selected:bins.append({'count':len(selected),'predicted':mean(r['probability'] for r in selected),'observed':mean(r['actual_up'] for r in selected)})
        result['reliability_bins']=bins
        result['calibration_error']=sum(b['count']*abs(b['predicted']-b['observed']) for b in bins)/len(probabilistic)
    return result


def forecast(result, horizon, created_at):
    data=result.get('prediction_inputs') or {}
    bars=data.get('candles') or []
    if horizon not in (300,900,1800):raise ValueError('Unsupported horizon')
    if not result.get('fresh') or not result.get('utc_clock_verified') or len(bars)<7:
        return None
    anchor=bars[-1]['timestamp']+300
    if not anchor<=created_at<anchor+min(horizon,90):return None
    if any(b['timestamp']-a['timestamp']!=300 for a,b in zip(bars[-7:],bars[-6:])):return None
    prices=[float(b['close']) for b in bars[-7:]]
    if any(not math.isfinite(p) or p<=0 for p in prices):raise ValueError('Invalid close')
    identity=result['account']; evidence=result['evidence']['M5']
    material={'schema_version':VERSION,'source':evidence['source'],'snapshot_id':evidence['snapshot_id'],
              'symbol':result['symbol'],'timeframe':'M5','horizon_seconds':horizon,'rule_version':'closed-momentum-baseline/1'}
    return {**material,'id':stable(material),'terminal_id':identity['terminal_id'],
            'account_identity':identity['identity'],'server':identity['server'],
            'environment':identity['environment'],'observation_at':anchor,'created_at':created_at,
            'expires_at':anchor+horizon,'target':'directional_close_change',
            'direction':'up' if prices[-1]>prices[0] else 'down' if prices[-1]<prices[0] else 'flat',
            'probability':None,'uncertainty':'Empirical outcome interval only after evaluation; heuristic has no calibrated probability',
            'calibration_status':'UNCALIBRATED — INSUFFICIENT VALIDATION DATA',
            'reference_close':prices[-1],'input_evidence_ids':[evidence['snapshot_id']],
            'strategy_context':{k:result.get('strategy_comparison',{}).get(k) for k in ('side','selection_reason','assessment_complete')},
            'data_quality':evidence.get('data_quality',{}),'spread_price':(result.get('quote') or {}).get('spread'),
            'commission':None,'slippage':None,'execution_authorized':False,
            'decision':'abstain','reason':'shadow_prediction_no_execution_authority'}


class PredictionLedger:
    """Additive tables in the existing scoped canonical ledger, with durable NUCM links."""
    def __init__(self,memory):
        self.memory=memory; self.gateway=memory.gateway; self.scope=memory.scope; self.last_error=None
        with self.gateway.db() as db:
            db.executescript('''CREATE TABLE IF NOT EXISTS market_predictions_v1(
              id TEXT PRIMARY KEY,namespace TEXT NOT NULL,principal TEXT NOT NULL,
              source TEXT NOT NULL,target_at REAL NOT NULL,payload TEXT NOT NULL,
              outcome TEXT,prediction_episode TEXT,outcome_episode TEXT);
              CREATE INDEX IF NOT EXISTS prediction_pending_v1 ON market_predictions_v1(namespace,principal,source,target_at);''')

    def observe(self,job,result):
        self.gateway.require('ingest',**self.scope)
        source=job.source+':'+job.account+':'+job.terminal+':'+job.symbol
        now=float(result['received_at'])
        if not math.isfinite(now):raise ValueError('Invalid receipt time')
        bars=(result.get('prediction_inputs') or {}).get('candles') or []
        if not result.get('fresh') or not result.get('utc_clock_verified'):
            return {'state':'data_quality_blocked','execution_authorized':False}
        with self.gateway.db() as db:
            pending=db.execute('SELECT id,payload FROM market_predictions_v1 WHERE namespace=? AND principal=? AND source=? AND outcome IS NULL AND target_at<=? ORDER BY target_at LIMIT 64',
                               (self.scope['namespace'],self.scope['principal'],source,now)).fetchall()
        for ident,raw in pending:
            prediction=json.loads(raw)
            target=next((b for b in bars if b['timestamp']+300==prediction['expires_at']),None)
            if target is None:continue  # Missing history is not a zero/flat outcome.
            if target['timestamp']+300>now or prediction['created_at']>=prediction['expires_at']:continue
            close=float(target['close']); delta=close-prediction['reference_close']
            if not math.isfinite(close) or close<=0:raise ValueError('Invalid outcome')
            direction='up' if delta>0 else 'down' if delta<0 else 'flat'
            outcome={'schema_version':'prediction-outcome/1','prediction_id':ident,
                     'evaluated_at':now,'target_at':prediction['expires_at'],'actual_close':close,
                     'actual_up':int(delta>0),'correct':direction==prediction['direction'],
                     'probability':prediction['probability'],'price_change':delta,
                     'outcome_kind':'hypothetical_not_executed','net_outcome':None,
                     'cost_status':'UNKNOWN_COMMISSION_AND_SLIPPAGE','execution_authorized':False}
            with self.gateway.db() as db:
                db.execute('UPDATE market_predictions_v1 SET outcome=? WHERE id=? AND outcome IS NULL',
                           (json.dumps(outcome,sort_keys=True),ident))
        for horizon in (300,900,1800):
            value=forecast(result,horizon,now)
            if value is None:continue
            with self.gateway.db() as db:
                db.execute('INSERT OR IGNORE INTO market_predictions_v1(id,namespace,principal,source,target_at,payload) VALUES(?,?,?,?,?,?)',
                           (value['id'],self.scope['namespace'],self.scope['principal'],source,value['expires_at'],json.dumps(value,sort_keys=True)))
        # Receipt repair is restart-safe: canonical record IDs are deterministic.
        with self.gateway.db() as db:
            repair=db.execute('SELECT id,payload,outcome,prediction_episode,outcome_episode FROM market_predictions_v1 WHERE namespace=? AND principal=? AND source=? AND (prediction_episode IS NULL OR (outcome IS NOT NULL AND outcome_episode IS NULL)) ORDER BY target_at LIMIT 64',
                              (self.scope['namespace'],self.scope['principal'],source)).fetchall()
        for ident,raw,outcome,prediction_episode,outcome_episode in repair:
            value=json.loads(raw)
            if prediction_episode is None:
                stamp=datetime.fromtimestamp(value['created_at'],timezone.utc).isoformat()
                receipt=self.memory.record(domain='trading',event_id=ident,source=source,observed_at=stamp,available_at=stamp,
                    content=raw,kind='prediction',support=value['input_evidence_ids'],rule_version=VERSION)
                with self.gateway.db() as db:db.execute('UPDATE market_predictions_v1 SET prediction_episode=? WHERE id=?',(receipt['id'],ident))
            if outcome is not None and outcome_episode is None:
                value=json.loads(outcome);stamp=datetime.fromtimestamp(value['evaluated_at'],timezone.utc).isoformat()
                receipt=self.memory.record(domain='trading',event_id=ident+':outcome',source=source,observed_at=stamp,available_at=stamp,
                    content=outcome,kind='simulation',support=[ident],rule_version=VERSION)
                with self.gateway.db() as db:db.execute('UPDATE market_predictions_v1 SET outcome_episode=? WHERE id=?',(receipt['id'],ident))
        return {'state':'shadow_only','execution_authorized':False}

    def status(self,now):
        self.gateway.require('read',**self.scope)
        with self.gateway.db() as db:
            rows=db.execute('SELECT payload,outcome,prediction_episode,outcome_episode FROM market_predictions_v1 WHERE namespace=? AND principal=? ORDER BY target_at DESC LIMIT 300',
                            (self.scope['namespace'],self.scope['principal'])).fetchall()
        groups={};recent=[]
        for raw,outcome,episode,outcome_episode in rows:
            value=json.loads(raw); key=(value['terminal_id'],value['symbol'],value['horizon_seconds'])
            group=groups.setdefault(key,{'terminal_id':key[0],'symbol':key[1],'horizon_seconds':key[2],'outcomes':[]})
            if outcome:group['outcomes'].append(json.loads(outcome))
            if len(recent)<12:recent.append({**value,'expired':value['expires_at']<=now,'evaluation':json.loads(outcome) if outcome else None,
                                           'prediction_episode':episode,'outcome_episode':outcome_episode})
        summaries=[{**{k:v for k,v in g.items() if k!='outcomes'},**metrics(g['outcomes'])} for g in groups.values()]
        return {'schema_version':VERSION,'mode':'shadow','recent':recent,'groups':summaries,'error_type':self.last_error,
                'execution_authorized':False,'limitations':['Continuation baseline; not a calibrated decision model',
                'No automatic strategy changes','Missing costs leave hypothetical net outcome UNKNOWN','Recent bounded window; not lifetime statistics']}


def walk_forward(bars,train_size=50,test_size=10,horizon=3,cost_price=None):
    """Purged expanding-window research baseline, no simulated fills or net-profit claim."""
    if min(train_size,test_size,horizon)<=0 or len(bars)>10000:raise ValueError('Invalid bounded replay')
    for a,b in zip(bars,bars[1:]):
        if b['timestamp']-a['timestamp']!=300:raise ValueError('Replay requires contiguous M5 closes')
    if any(not math.isfinite(float(b['close'])) or b['close']<=0 for b in bars):raise ValueError('Invalid replay price')
    folds=[]
    for start in range(train_size+horizon,len(bars)-horizon,test_size):
        train_end=start-horizon
        training=[int(bars[i+horizon]['close']>bars[i]['close']) for i in range(train_end)]
        probability=(sum(training)+1)/(len(training)+2)
        outcomes=[]
        for i in range(start,min(start+test_size,len(bars)-horizon)):
            delta=bars[i+horizon]['close']-bars[i]['close'];actual=int(delta>0)
            outcomes.append({'actual_up':actual,'probability':probability,'correct':int(probability>=.5)==actual})
        folds.append({'train_last_target':bars[train_end-1+horizon]['timestamp']+300,
                      'test_first_prediction':bars[start]['timestamp']+300,'training_samples':len(training),
                      'evaluation':metrics(outcomes),'baseline_probability':.5})
    return {'schema_version':'walk-forward/1','dataset_id':stable(bars),'method':'expanding_purged_chronological',
            'rule_version':'beta-binomial-unconditional/1','folds':folds,'cost_price':cost_price,
            'net_profit':None,'cost_status':'UNKNOWN' if cost_price is None else 'explicit_price_assumption_only',
            'execution_authorized':False,'promotion_authorized':False}
