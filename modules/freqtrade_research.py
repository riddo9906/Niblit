"""Read-only Freqtrade parity for the shared strategy/prediction laboratory.

No start, force-enter, force-exit or configuration mutation is available here.
Native strategy activation remains an explicit engine-profile operation.
"""
import json
import sqlite3
import time

from modules.demo_strategy import STRATEGIES
from modules.strategy_manager import assess
from modules.strategy_research import study


class FreqtradeResearch:
    def __init__(self, desk):
        self.desk=desk
        self.path=desk.path.parent/'freqtrade-research.sqlite3'
        from modules.online_market_study import OnlineMarketStudy
        self.online_study=OnlineMarketStudy(desk.path.parent/'online-market-study.sqlite3')
        with sqlite3.connect(self.path) as db:
            db.execute('CREATE TABLE IF NOT EXISTS reports(id TEXT PRIMARY KEY, available REAL, payload TEXT)')
            db.execute('CREATE TABLE IF NOT EXISTS forecast_outcomes(id TEXT PRIMARY KEY, payload TEXT)')

    def snapshot(self, pair):
        config=self.desk.configuration()
        if pair not in self.desk.api('whitelist').get('whitelist',[]):
            raise ValueError('Choose a whitelisted Freqtrade pair')
        market=self.desk.market(pair,config)
        candles=market['candles']
        manager=assess(candles)
        bar=manager.get('bar')
        identity=json.dumps([config,pair,bar],sort_keys=True)
        with sqlite3.connect(self.path) as db:
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
                outcome={'symbol':pair,'mode':expected_mode,'target_bar':target,
                         'predicted_return':predicted,'realized_return':realized,
                         'absolute_error':abs(realized-predicted),'notice':'Prediction score, not trade profit.'}
                db.execute('INSERT OR IGNORE INTO forecast_outcomes VALUES(?,?)',(key,json.dumps(outcome)))
            existing=db.execute('SELECT payload FROM reports WHERE id=?',(identity,)).fetchone()
            if existing:
                research=json.loads(existing[0])
            elif market['fresh']:
                research={**study(candles,generate=manager['side']=='wait'),
                          'symbol':pair,'venue':config.get('exchange'),
                          'mode':'dry-run-research' if config.get('dry_run') is True else 'live-read-only-research',
                          'available_at':time.time(),'spread_assumption':'Current spread unavailable; proxy omits spread and commissions. Not suitable for execution promotion.'}
                db.execute('INSERT INTO reports VALUES(?,?,?)',(identity,time.time(),json.dumps(research)))
            else:
                research={'state':'stale_market','proposals':[],'execution_eligible':False,'reason':'Wait for fresh completed exchange candles'}
            outcomes=[json.loads(r[0]) for r in db.execute('SELECT payload FROM forecast_outcomes ORDER BY rowid DESC LIMIT 40')]
        manager.update(checked_at=time.time(),risk_checks={'fresh_market':market['fresh'],
            'dry_run':config.get('dry_run') is True,'engine_running':config.get('state')=='running',
            'execution_preflight':'Not performed by this read-only researcher'})
        research['online_comparer']=self.online_study.observe(
            json.dumps(['freqtrade',config.get('exchange'),pair,config.get('dry_run'),'M5']),
            candles,market_time=time.time(),fresh=market['fresh'])
        return {'running':False,'execution_active':False,'manager':manager,'research':research,
                'strategies':STRATEGIES,'forecast_outcomes':outcomes,
                'native_engine_strategy':config.get('strategy'),
                'notice':'Research only. Existing native engine strategy and positions are unchanged.'}
