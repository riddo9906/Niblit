import json
import sqlite3

from scripts.inspect_market_cognition import inspect_ledger


def ledger():
    db=sqlite3.connect(":memory:")
    db.executescript("""
    CREATE TABLE trading_orders(
        id TEXT,session_id TEXT,adapter TEXT,account TEXT,symbol TEXT,
        action TEXT,state TEXT,payload TEXT,result TEXT,updated REAL);
    CREATE TABLE trading_events(id TEXT,created REAL,kind TEXT,payload TEXT);
    """)
    return db


def assessment():
    return {"side":"buy","strategy":"breakout_v1","bar":1230,
        "selection_reason":"Registered breakout rules qualify",
        "policy_version":"conditions-v2","assessment_complete":True,
        "candidates":[{"strategy":"breakout_v1","side":"buy"},
                      {"strategy":"ema_pullback_v1","side":"wait"}],
        "market_thesis":{"evidence_id":"test-evidence","classification":"directional_hypothesis"}}


def event(db, kind, body, number=1):
    db.execute("INSERT INTO trading_events VALUES(?,?,?,?)",
               (f"event-{kind}-{number}",float(number),kind,json.dumps(body)))


def order(db):
    payload={"decision":assessment(),"context":{"strategy":"breakout_v1"},
             "prepared":{"risk":2.0}}
    db.execute("INSERT INTO trading_orders VALUES(?,?,?,?,?,?,?,?,?,?)",
        ("order-1","session-1","mt5","demo-A","ETHUSDm",
         "open","closed",json.dumps(payload),json.dumps({"realized_net":1.0}),3.0))


def test_reconstructs_trace_without_claiming_it_was_live_integrated():
    db=ledger()
    order(db)
    event(db,"signal",{"kind":"signal","adapter":"mt5","account":"demo-A",
        "environment":"demo","symbol":"ETHUSDm","session":"session-1",
        "bar":1230,"assessment":assessment()})
    event(db,"trading_outcome",{"kind":"trading_outcome","order":"order-1",
        "strategy":"breakout_v1","environment":"demo",
        "performance":{"net_realized_r":.5},
        "evidence":{"realized_net":1.0}},2)
    db.commit()
    report=inspect_ledger(db)
    assert report["market_decision_traces_reconstructed"]==1
    assert report["unique_decision_trace_ids"]==1
    outcome=report["broker_verified_outcomes"][0]
    assert outcome["trace_origin"]=="retrospective_reconstruction"
    assert outcome["decision_trace_id"] is not None
    assert outcome["realized_net"]==1
    assert not report["demonstrated_online_learning"]
    assert not report["execution_authorized"]
    db.close()


def test_missing_broker_outcome_proof_is_excluded():
    db=ledger()
    order(db)
    event(db,"trading_outcome",{"kind":"trading_outcome","order":"order-1",
        "performance":{"net_realized_r":.5},"evidence":{}},3)
    db.commit()
    report=inspect_ledger(db)
    assert report["broker_verified_outcomes"]==[]
    assert report["broker_outcomes_with_incomplete_evidence"]==["order-1"]
    db.close()


def test_scanned_window_is_bounded_and_no_writes_occur():
    db=ledger()
    for i in range(1,11):
        event(db,"position_reversal_evaluation",{
            "kind":"position_reversal_evaluation","report":{"action":"hold"}},i)
    db.commit()
    before=db.total_changes
    report=inspect_ledger(db,max_events=5)
    assert report["event_rows_scanned"]==5
    assert report["reversal_evaluation_actions"]["hold"]==5
    assert db.total_changes==before
    db.close()


def test_rejects_unbounded_inspection():
    import pytest
    db=ledger()
    with pytest.raises(ValueError):
        inspect_ledger(db,max_events=100_000)
    db.close()
