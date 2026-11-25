import json
import sqlite3

from modules.position_cognition_record import PositionCognitionLedger, PositionIdentity
from scripts.backfill_r14_position_cognition import backfill


def fixture_db():
    db=sqlite3.connect(":memory:")
    db.executescript("""
        CREATE TABLE trading_orders(id TEXT,session_id TEXT,adapter TEXT,account TEXT,
          symbol TEXT,action TEXT,state TEXT,payload TEXT,result TEXT,updated REAL);
        CREATE TABLE trading_events(id TEXT,created REAL,kind TEXT,payload TEXT);
    """)
    return db


def decision():
    return {"side":"buy","strategy":"breakout_v1","bar":1200,
      "selection_reason":"Tested breakout condition",
      "policy_version":"conditions-v2","assessment_complete":True,
      "candidates":[{"strategy":"breakout_v1","side":"buy"},
                    {"strategy":"trend_v1","side":"wait"}],
      "market_thesis":{"evidence_id":"evidence-1","classification":"directional_hypothesis"}}


def populate(db, *, match=True, watch_session="session-A", result_account="demo-A",
             close=True, suffix="A"):
    order_id="order-"+suffix
    core={"prepared":{"risk":2.0},"decision":decision(),
          "context":{"strategy":"breakout_v1","initial_stop":95.}}
    db.execute("INSERT INTO trading_orders VALUES(?,?,?,?,?,?,?,?,?,?)",
        (order_id,"session-"+suffix,"mt5",result_account,"ETHUSDm","open",
         "closed" if close else "open",json.dumps(core),
         json.dumps({"position_id":"broker-"+suffix,"state":"closed" if close else "open"}),
         1900))
    signal={"kind":"signal","session":"session-"+suffix,"symbol":"ETHUSDm",
            "bar":1200,"quote":{"fresh":True,"bid":101. if match else 99.,
                               "ask":101.2,"timestamp":1004}}
    watch={"kind":"position_watch","session":watch_session,"order":order_id,
           "symbol":"ETHUSDm","bar":1200,"observed_at":1006.,
           "mark":101.,"position":{"id":"broker-"+suffix,"side":"buy",
           "entry":100.,"quantity":1.,"stop_loss":95.,"take_profit":120.,"profit":1.}}
    db.execute("INSERT INTO trading_events VALUES(?,?,?,?)",
               ("signal-"+suffix,1005.,"signal",json.dumps(signal)))
    db.execute("INSERT INTO trading_events VALUES(?,?,?,?)",
               ("watch-"+suffix,1006.,"position_watch",json.dumps(watch)))
    if close:
        outcome={"kind":"trading_outcome","order":order_id,"session":"session-"+suffix,
                 "symbol":"ETHUSDm","evidence":{"state":"closed",
                 "position_id":"broker-"+suffix,"realized_net":.8,
                 "exit_fills":[{"deal":777,"price":101.5,"volume":1.}]}}
        db.execute("INSERT INTO trading_events VALUES(?,?,?,?)",
                   ("outcome-"+suffix,1500.,"trading_outcome",json.dumps(outcome)))
    db.commit()


def test_broker_identity_quote_and_actual_close_are_joined(tmp_path):
    db=fixture_db()
    populate(db)
    sidecar=PositionCognitionLedger(tmp_path/"shadow.sqlite3")
    result=backfill(db,sidecar)
    assert result["position_records_created"]==1
    assert result["matched_quotes"]==1
    assert result["close_deals_reconciled"]==1
    record=result["positions"][0]
    assert record["position_state"]=="closed"
    assert record["broker_realized_net"]==.8
    assert record["broker_realized_net_complete"] is True
    assert record["sampled_mfe_r"]==.2
    assert record["trace_origin"]=="retrospective_from_frozen_original_order"
    assert result["source_db_read_only"] is True
    assert result["broker_access_performed"] is False
    assert result["orders_submitted"]==0
    db.close()


def test_repeat_backfill_is_idempotent(tmp_path):
    db=fixture_db()
    populate(db)
    sidecar=PositionCognitionLedger(tmp_path/"shadow.sqlite3")
    first=backfill(db,sidecar)
    second=backfill(db,PositionCognitionLedger(tmp_path/"shadow.sqlite3"))
    assert first==second
    identity=PositionIdentity("mt5","demo-A","broker-A","order-A")
    assert sidecar.replay(identity)["event_count"]==3
    db.close()


def test_unmatched_quote_is_never_interpolated(tmp_path):
    db=fixture_db()
    populate(db,match=False,close=False)
    result=backfill(db,PositionCognitionLedger(tmp_path/"shadow.sqlite3"))
    assert result["position_records_created"]==1
    assert result["matched_quotes"]==0
    assert result["positions"][0]["sampled_mfe_r"] is None
    assert result["positions"][0]["position_state"]=="open"
    db.close()


def test_wrong_watch_session_not_adopted(tmp_path):
    db=fixture_db()
    populate(db,watch_session="unrelated")
    result=backfill(db,PositionCognitionLedger(tmp_path/"shadow.sqlite3"))
    assert result["position_records_created"]==0
    assert result["skipped"]["watch_session_or_symbol_mismatch"]==1
    db.close()


def test_same_broker_position_id_different_account_keeps_separate(tmp_path):
    db=fixture_db()
    populate(db,close=False,suffix="A")
    populate(db,close=False,suffix="B",result_account="demo-B",watch_session="session-B")
    sidecar=PositionCognitionLedger(tmp_path/"shadow.sqlite3")
    result=backfill(db,sidecar)
    assert result["position_records_created"]==2
    assert result["positions"][0]["position_key"]!=result["positions"][1]["position_key"]
    db.close()
