import pytest
from modules.position_cognition_record import PositionIdentity, PositionCognitionLedger


@pytest.fixture
def ledger(tmp_path):
    return PositionCognitionLedger(tmp_path/"positions.sqlite3")


@pytest.fixture
def position():
    return PositionIdentity("mt5","demo-123","broker-position-55","core-order-7")


def entry(**kwargs):
    return {"side":"buy","entry":100.0,"quantity":1.0,"initial_stop":95.,
            "take_profit":115.,"strategy":"breakout_v1",
            "decision_trace_id":"trace-abc","thesis_id":"market-evidence-1",**kwargs}


def test_broker_marks_keep_actual_and_floating_separate(ledger,position):
    ledger.record(position,"entry",1000,entry())
    ledger.record(position,"mark",1010,{"bid":103.,"ask":103.2,"quantity":1.,
                                          "floating_profit":3.,"quote_timestamp":1010})
    ledger.record(position,"mark",1020,{"bid":97.,"ask":97.1,"quantity":1.,
                                          "floating_profit":-3.,"quote_timestamp":1020})
    result=ledger.replay(position)
    assert result["observed_mfe_r"]==pytest.approx(.6)
    assert result["observed_mae_r"]==pytest.approx(-.6)
    assert result["last_floating_profit"]==-3.
    assert result["broker_realized_net"] is None
    assert not result["realized_net_complete"]
    assert not result["execution_authorized"]


def test_partial_close_restart_replay_and_fees(ledger,position):
    ledger.record(position,"entry",1000,entry())
    ledger.record(position,"deal",1100,{"action":"close","quantity":.25,"price":102.,
                                        "realized_net":.44,"commission":-.03,"swap":0.},
                  event_id="deal-1")
    ledger.record(position,"deal",1100,{"action":"close","quantity":.25,"price":102.,
                                        "realized_net":.44,"commission":-.03,"swap":0.},
                  event_id="deal-1")
    a=ledger.replay(position)
    assert a["event_count"]==2
    assert a["position_state"]=="partially_closed"
    assert a["remaining_quantity_from_verified_closes"]==.75
    assert a["broker_realized_net"]==.44
    assert not a["realized_net_complete"]
    restarted=PositionCognitionLedger(ledger.path)
    assert restarted.replay(position)==a
    restarted.record(position,"deal",1200,{"action":"close","quantity":.75,"price":101.,
                                          "realized_net":.63},event_id="deal-2")
    finished=restarted.replay(position)
    assert finished["position_state"]=="closed"
    assert finished["broker_realized_net"]==pytest.approx(1.07)
    assert finished["realized_net_complete"]


def test_absent_fees_and_profit_never_invented(ledger,position):
    ledger.record(position,"entry",1000,entry())
    ledger.record(position,"deal",1200,{"action":"close","quantity":1.0,"price":99.},event_id="deal-2")
    result=ledger.replay(position)
    assert result["position_state"]=="closed"
    assert result["broker_realized_net"] is None
    assert not result["realized_net_complete"]
    assert "commission" not in result["deals"][0]
    assert result["counterfactual_outcomes"] is None


def test_account_and_core_order_are_scoped(ledger,position):
    ledger.record(position,"entry",1000,entry())
    other=PositionIdentity("mt5","demo-456","broker-position-55","core-order-7")
    assert ledger.replay(other)["position_state"]=="unattributed"
    other2=PositionIdentity("mt5","demo-123","broker-position-55","different-order")
    assert ledger.replay(other2)["event_count"]==0
    assert position.key!=other.key and position.key!=other2.key


def test_manual_position_requires_core_entry_evidence(ledger,position):
    ledger.record(position,"mark",1010,{"bid":101.,"ask":101.1,"quantity":.5})
    result=ledger.replay(position)
    assert result["entry"] is None and result["position_state"]=="unattributed"


def test_protection_and_thesis_changes_are_observations(ledger,position):
    ledger.record(position,"entry",1000,entry())
    ledger.record(position,"protection",1100,{"stop_loss":100.5,"take_profit":118.})
    ledger.record(position,"thesis",1200,{"state":"weakening","evidence_id":"bar-xyz"})
    result=ledger.replay(position)
    assert result["protection"]=={"stop_loss":100.5,"take_profit":118.}
    assert result["thesis_state"]=="weakening"
    assert result["latest_thesis_evidence_id"]=="bar-xyz"
    assert result["learning_action"]=="record_only"


def test_identity_conflict_is_detected(ledger,position):
    ledger.record(position,"entry",1000,entry(),event_id="entry")
    with pytest.raises(ValueError,match="Conflicting reuse"):
        ledger.record(position,"entry",1000,{**entry(),"entry":101.},event_id="entry")
    ledger.record(position,"entry",1100,{**entry(),"entry":102.},event_id="entry2")
    with pytest.raises(ValueError,match="Contradictory"):
        ledger.replay(position)


def test_invalid_price_quote_future_and_overclose(ledger,position):
    ledger.record(position,"entry",1000,entry())
    with pytest.raises(ValueError,match="Crossed"):
        ledger.record(position,"mark",1010,{"bid":105.,"ask":104.,"quantity":1.})
    ledger.record(position,"mark",1010,{"bid":102.,"ask":102.1,"quantity":1.,"quote_timestamp":1030})
    with pytest.raises(ValueError,match="future"):
        ledger.replay(position)
    another=PositionIdentity("mt5","a","b","c")
    ledger.record(another,"entry",1000,entry())
    ledger.record(another,"deal",1100,{"action":"close","quantity":1.5,"price":99.})
    with pytest.raises(ValueError,match="exceed"):
        ledger.replay(another)


def test_out_of_order_broker_delivery_replays_by_time(ledger,position):
    ledger.record(position,"deal",1300,{"action":"close","quantity":1.,"price":102.,
                                        "realized_net":2.},event_id="deal-1")
    ledger.record(position,"entry",1000,entry())
    assert ledger.replay(position)["position_state"]=="closed"
    assert ledger.replay(position)["broker_realized_net"]==2.


def test_partial_open_fills_need_broker_reconciled_quantities(ledger, position):
    ledger.record(position,"entry",1000,entry())
    ledger.record(position,"deal",1100,{"action":"open","quantity":.3,
                                        "price":100.,"quantity_after":.3},event_id="fill-a")
    early=ledger.replay(position)
    assert early["position_state"]=="partially_filled"
    assert early["remaining_quantity_from_verified_closes"]==pytest.approx(.3)
    assert early["quantity_evidence"]=="broker_reconciled"
    ledger.record(position,"deal",1200,{"action":"open","quantity":.7,
                                        "price":100.1,"quantity_after":1.},event_id="fill-b")
    result=ledger.replay(position)
    assert result["position_state"]=="open"
    assert result["remaining_quantity_from_verified_closes"]==pytest.approx(1.)


def test_pre_entry_and_post_close_quotes_do_not_contaminate_excursion(ledger, position):
    ledger.record(position,"mark",900,{"bid":150.,"ask":150.1,"quantity":1.})
    ledger.record(position,"entry",1000,entry())
    ledger.record(position,"mark",1100,{"bid":103.,"ask":103.1,"quantity":1.})
    ledger.record(position,"deal",1200,{"action":"close","quantity":1.,"price":104.,
                                          "realized_net":3.8})
    ledger.record(position,"mark",1300,{"bid":150.,"ask":150.1,"quantity":0.})
    result=ledger.replay(position)
    assert result["observed_mfe_r"]==pytest.approx(.6)
    assert result["position_state"]=="closed"
    assert result["last_floating_profit"] is None


def test_rejects_false_or_unverified_broker_numbers(ledger,position):
    with pytest.raises(ValueError):
        ledger.record(position,"entry",1000,{**entry(),"quantity":float("nan")})
    with pytest.raises(ValueError):
        ledger.record(position,"deal",1100,{"action":"close","quantity":True,"price":99.})
