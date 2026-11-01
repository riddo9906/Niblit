"""Read-only HTTP acceptance receipt. No credentials, inference or order submission."""
import json
from pathlib import Path
import time
import httpx

ROOT=Path(__file__).resolve().parents[1]
if __name__=='__main__':
    with httpx.Client(trust_env=False,timeout=15) as client:
        response=client.get('http://127.0.0.1:8767/api/mt5/snapshot')
        response.raise_for_status()
        data=response.json()
    receipt={'checked_at':time.time(),'connected':data.get('connected'),
        'server':data.get('account',{}).get('server'),'account_mode':data.get('account',{}).get('mode'),
        'currency':data.get('account',{}).get('currency'),'symbol':data.get('symbol'),
        'quote_advancement_observed':data.get('quote',{}).get('fresh'),
        'freshness_basis':data.get('quote',{}).get('freshness_basis'),
        'completed_candles':len(data.get('candles',[])),
        'position_count':len(data.get('positions',[])),'pending_order_count':data.get('pending_order_count'),
        'capabilities':data.get('capabilities'),'paid_inference_calls':0,'orders_submitted':0}
    path=ROOT/'diagnostics/mt5-connection-acceptance.json'
    path.write_text(json.dumps(receipt,indent=2),encoding='utf-8')
    print(json.dumps(receipt,indent=2))
