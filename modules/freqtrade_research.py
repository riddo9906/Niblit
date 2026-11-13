"""Read-only Freqtrade parity for the shared strategy/prediction laboratory.

No start, force-enter, force-exit or configuration mutation is available here.
Native strategy activation remains an explicit engine-profile operation.
"""
import hashlib
import json
import sqlite3
import time

from modules.demo_strategy import STRATEGIES
from modules.strategy_manager import assess
from modules.strategy_research import study


class FreqtradeResearch:
    def __init__(self, desk, core_analysis=None, native_analysis=None):
        self.desk=desk
        self.core_analysis=core_analysis
        self.native_analysis=native_analysis
        self.path=desk.path.parent/'freqtrade-research.sqlite3'
        from modules.online_market_study import OnlineMarketStudy
        self.online_study=OnlineMarketStudy(desk.path.parent/'online-market-study.sqlite3')
        with sqlite3.connect(self.path) as db:
            db.execute('CREATE TABLE IF NOT EXISTS reports(id TEXT PRIMARY KEY, available REAL, payload TEXT)')
            db.execute('CREATE TABLE IF NOT EXISTS forecast_outcomes(id TEXT PRIMARY KEY, payload TEXT)')
            db.execute('CREATE TABLE IF NOT EXISTS analysis_decisions(id TEXT PRIMARY KEY, payload TEXT)')

    def recall_analysis(self, identity):
        """Recall an immutable local research decision, including after restart."""
        with sqlite3.connect(self.path) as db:
            row=db.execute('SELECT payload FROM analysis_decisions WHERE id=?',(identity,)).fetchone()
        return json.loads(row[0]) if row else None

    def snapshot(self, pair):
        config=self.desk.configuration()
        if pair not in self.desk.api('whitelist').get('whitelist',[]):
            raise ValueError('Choose a whitelisted Freqtrade pair')
        market=self.desk.market(pair,config)
        candles=market['candles']
        manager=assess(candles)
        fresh=market.get('fresh') is True
        mode='dry-run-research' if config.get('dry_run') is True else 'live-read-only-research'
        manager.update(checked_at=time.time(),risk_checks={'fresh_market':fresh,
            'dry_run':config.get('dry_run') is True,'engine_running':config.get('state')=='running',
            'execution_preflight':'Not performed by this read-only researcher'})
        if not fresh:
            # Preserve the measured candidates, but never advertise an actionable
            # consensus from old candles. This researcher has no order authority.
            manager.update(side='wait',reason='Market data is stale or freshness is unverified; abstain.',
                selection_reason='Fresh completed exchange candles are required for a current signal.',
                abstain_reason='stale_market')
        manager.update(symbol=pair,venue=config.get('exchange'),mode=mode)
        decision_key={k:v for k,v in manager.items() if k!='checked_at'}
        analysis_id=hashlib.sha256(json.dumps(decision_key,sort_keys=True).encode()).hexdigest()
        bar=manager.get('bar')
        identity=json.dumps([config,pair,bar],sort_keys=True)
        with sqlite3.connect(self.path) as db:
            db.execute('INSERT OR IGNORE INTO analysis_decisions VALUES(?,?)',
                       (analysis_id,json.dumps(manager)))
            available={r['timestamp']:r['close'] for r in candles}
            for key,encoded in db.execute('SELECT id,payload FROM reports ORDER BY available DESC LIMIT 500').fetchall():
                previous=json.loads(encoded)
                if previous.get('symbol')!=pair or previous.get('venue')!=config.get('exchange') or not previous.get('forecast'):
                    continue
                expected_mode='dry-run-research' if config.get('dry_run') is True else 'live-read-only-research'
                if previous.get('mode')!=expected_mode: continue
                target=previous['bar']+300
                if target not in available: continue
                realized=available[target]/previous['reference_close']-1
                predicted=previous['forecast']['expected_return']
                outcome={'symbol':pair,'venue':config.get('exchange'),'mode':expected_mode,'target_bar':target,
                         'predicted_return':predicted,'realized_return':realized,
                         'absolute_error':abs(realized-predicted),'notice':'Prediction score, not trade profit.'}
                db.execute('INSERT OR IGNORE INTO forecast_outcomes VALUES(?,?)',(key,json.dumps(outcome)))
            existing=db.execute('SELECT payload FROM reports WHERE id=?',(identity,)).fetchone()
            if existing and fresh:
                research=json.loads(existing[0])
            elif fresh:
                research={**study(candles,generate=manager['side']=='wait'),
                          'symbol':pair,'venue':config.get('exchange'),
                          'mode':'dry-run-research' if config.get('dry_run') is True else 'live-read-only-research',
                          'available_at':time.time(),'spread_assumption':'Current spread unavailable; proxy omits spread and commissions. Not suitable for execution promotion.'}
                db.execute('INSERT INTO reports VALUES(?,?,?)',(identity,time.time(),json.dumps(research)))
            else:
                research={'state':'stale_market','proposals':[],'execution_eligible':False,'reason':'Wait for fresh completed exchange candles'}
            # Legacy rows without venue cannot safely be attributed to a market.
            outcomes=[json.loads(r[0]) for r in db.execute(
                """SELECT payload FROM forecast_outcomes
                   WHERE json_extract(payload,'$.symbol')=?
                     AND json_extract(payload,'$.venue')=?
                     AND json_extract(payload,'$.mode')=?
                   ORDER BY rowid DESC LIMIT 40""",
                (pair,config.get('exchange'),mode))]
        research['online_comparer']=self.online_study.observe(
            json.dumps(['freqtrade',config.get('exchange'),pair,config.get('dry_run'),'M5']),
            candles,market_time=time.time(),fresh=fresh)
        native_result={"state":"not_connected","signal":"ABSTAIN","execution_authorized":False}
        core_result={"state":"not_connected","execution_authorized":False}
        if self.core_analysis is not None and config.get("dry_run") is True:
            # A dry-run account is the existing simulated engine profile, not a
            # broker credential. Scope its journal by existing data location.
            profile=hashlib.sha256(json.dumps(
                [str(self.path.resolve()),config.get("exchange")]).encode()).hexdigest()
            observation={"symbol":pair,"venue":config.get("exchange"),
                "timeframe":config.get("timeframe"),"mode":"dry-run",
                "account_scope":"freqtrade-profile-"+profile,
                "source":market.get("source","freqtrade_analyzed_exchange_candles"),
                "received_at":time.time(),"fresh":fresh,"candles":candles}
            if self.native_analysis is not None:
                native_result=self.native_analysis(observation,config)
                observation["native_strategy"]=native_result
            try:
                core_result=self.core_analysis(observation)
            except Exception as exc:
                core_result={"state":"pending","error_type":type(exc).__name__,
                             "execution_authorized":False}
        return {'running':False,'execution_active':False,'manager':manager,'research':research,
                'core_analysis':core_result,'native_analysis':native_result,
                'strategies':STRATEGIES,'forecast_outcomes':outcomes,
                'analysis_memory':{'id':analysis_id,'saved':True,'store':self.path.name,
                    'scope':'Local research journal; not a verified lesson or Core memory export'},
                'native_engine_strategy':config.get('strategy'),
                'notice':'Research only. Existing native engine strategy and positions are unchanged.'}
