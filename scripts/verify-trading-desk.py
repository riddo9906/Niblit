"""Read-only acceptance receipt. Never places an order or invokes paid inference."""
from pathlib import Path
import json
import sqlite3
import sys
import time
import httpx
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))

if __name__=='__main__':
    with httpx.Client(trust_env=False,timeout=30) as client:
        data=client.get('http://127.0.0.1:8767/api/snapshot').json()
        config=data.get('configuration',{})
        market=data.get('market') or {}
        receipt={'checked_at':time.time(),'connected':data.get('connected'),
            'configuration':config,'fresh_completed_candles':market.get('fresh'),
            'candle_count':len(market.get('candles',[])),'open_positions':len(data.get('positions',{}).get('data',[])),
            'closed_outcomes':data.get('recorded_outcomes'),'memory_export':data.get('memory'),
            'funded_execution_enabled':data.get('funded_execution_enabled'),
            'orders_submitted_by_acceptance':0,'paid_inference_calls':0}
        with sqlite3.connect(ROOT/'runtime/memory-framework/ledger.sqlite3') as db:
            receipt['outcome_records_projected']=db.execute(
                "SELECT count(*) FROM records WHERE source LIKE 'freqtrade-outcome://%' AND active=1").fetchone()[0]
        try:
            receipt['core_ready']=client.get('http://127.0.0.1:5000/api/memory/framework',timeout=5).status_code==200
        except httpx.HTTPError: receipt['core_ready']=False
        (ROOT/'diagnostics/trading-desk-acceptance.json').write_text(json.dumps(receipt,indent=2),encoding='utf-8')
        print(json.dumps(receipt,indent=2))
