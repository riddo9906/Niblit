"""One-off correction backed by inspected engine logs; not an order resender."""
from pathlib import Path
import json
import sqlite3

ROOT=Path(__file__).resolve().parents[1]
TICKET='ABgCizXdW5fN_4Ym1BOOKCy4r3sPBfSP'
if __name__=='__main__':
    with sqlite3.connect(ROOT/'runtime/trading-desk/orders.sqlite3') as db:
        db.row_factory=sqlite3.Row
        row=db.execute('SELECT * FROM tickets WHERE id=?',(TICKET,)).fetchone()
        if row is None or row['state']!='unknown':
            print('No unresolved matching ticket to correct')
        else:
            intent=json.loads(row['payload'])['intent']
            assert intent['pair']=='BTC/USDT:USDT' and intent['stake']==20 and intent['action']=='enter_long'
            evidence={'message':'Engine rejected entry: requested stake below the exchange minimum',
                'previous_result':json.loads(row['result']),
                'evidence':{'source':'docker logs freqtrade, inspected 2026-10-29',
                    'timestamp_utc':'2026-10-29T16:43:51Z','required_stake':85.482075,
                    'requested_stake':20,'engine_error':'API Error calling: Failed to enter position for BTC/USDT:USDT.',
                    'reason':'Adjusted stake exceeds 30% of requested stake; execute_entry returned false'}}
            db.execute("UPDATE tickets SET state='rejected',result=? WHERE id=? AND state='unknown'",
                (json.dumps(evidence),TICKET))
            print('Known engine rejection reconciled with preserved previous result and log evidence; no order sent')
