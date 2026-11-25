"""Read-only inspection of the installed R14 Core's canonical decision evidence.

Retrospectively rebuilds a trace where the frozen version stored strategy votes
but not the later versioned trace ID. Never accesses MT5 or writes Core DB.
"""
from __future__ import annotations
import argparse
import collections
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from modules.market_decision_trace import decision_trace


def _json(raw):
    try:
        payload=json.loads(raw) if isinstance(raw,str) else raw
        return payload if isinstance(payload,dict) else {}
    except (TypeError,ValueError):
        return {}


def inspect_ledger(db, *, max_events=1000):
    """No INSERT/UPDATE/DELETE or network. All counts are within the scan window."""
    if type(max_events) is not int or not 1<=max_events<=10_000:
        raise ValueError("bounded number of events required")
    db.row_factory=sqlite3.Row
    orders=[dict(row) for row in db.execute(
        """SELECT id,session_id,adapter,account,symbol,action,state,payload,result,updated
        FROM trading_orders ORDER BY updated DESC LIMIT 500""")]
    order_map={o["id"]:o for o in orders}
    rows=[dict(row) for row in db.execute(
        """SELECT id,created,kind,payload FROM trading_events
        ORDER BY created DESC LIMIT ?""",(max_events,))]
    count=collections.Counter(row["kind"] for row in rows)
    strategies=collections.Counter()
    chosen=collections.Counter()
    trace_ids=set()
    traced=0
    trace_problems=collections.Counter()
    signal_bars=set()
    for row in rows:
        if row["kind"]!="signal":
            continue
        payload=_json(row["payload"])
        assessment=payload.get("assessment")
        if not isinstance(assessment,dict):
            trace_problems["missing_strategy_assessment"]+=1
            continue
        for candidate in assessment.get("candidates",[]):
            if isinstance(candidate,dict):
                strategies[str(candidate.get("strategy") or "unknown")]+=1
        chosen[str(assessment.get("strategy") or "unknown")]+=1
        try:
            trace=decision_trace(
                assessment, adapter=str(payload.get("adapter") or "unknown"),
                account=str(payload.get("account") or "unknown"),
                symbol=str(payload.get("symbol") or "unknown"),
                environment=str(payload.get("environment") or "unknown"))
        except (ValueError,TypeError,KeyError):
            trace_problems["trace_unavailable"]+=1
            continue
        trace_ids.add(trace["trace_id"])
        signal_bars.add((payload.get("session"),payload.get("symbol"),payload.get("bar")))
        traced+=1
    entry=collections.Counter(o["state"] for o in orders if o["action"]=="open")
    close=collections.Counter(o["state"] for o in orders if o["action"]=="close")
    verified_outcomes=[]
    outcome_incomplete=[]
    for row in rows:
        if row["kind"]!="trading_outcome":continue
        payload=_json(row["payload"])
        original=order_map.get(payload.get("order"))
        perf=payload.get("performance") or {}
        evidence=payload.get("evidence") or {}
        if (not isinstance(perf,dict) or
            not isinstance(evidence,dict) or
            not isinstance(evidence.get("realized_net"),(int,float)) or
            not isinstance(perf.get("net_realized_r"),(int,float)) or
            original is None or original["action"]!="open"):
            outcome_incomplete.append(str(payload.get("order") or "unknown"))
            continue
        order_decision=_json(original["payload"]).get("decision") or {}
        trace_id=None
        if isinstance(order_decision,dict):
            if isinstance(order_decision.get("decision_trace"),dict):
                trace_id=order_decision["decision_trace"].get("trace_id")
            else:
                try:
                    reconstructed=decision_trace(
                        order_decision,adapter=original["adapter"],
                        symbol=original["symbol"],account=original["account"],
                        environment=str(payload.get("environment") or "unknown"))
                    trace_id=reconstructed["trace_id"]
                except (ValueError,KeyError,TypeError):
                    pass
        verified_outcomes.append({
            "order_id":payload.get("order"),
            "symbol":original["symbol"],
            "strategy":payload.get("strategy"),
            "realized_net":evidence["realized_net"],
            "net_realized_r":perf["net_realized_r"],
            "decision_trace_id":trace_id,
            "trace_origin":("frozen_original" if order_decision.get("decision_trace")
                else "retrospective_reconstruction" if trace_id else "unavailable"),
            "broker_result_type":"original_core_broker_reconciled",
            "regime_at_entry":"unknown_in_frozen_runtime",
        })
    reversal=collections.Counter()
    for row in rows:
        if row["kind"]=="position_reversal_evaluation":
            report=_json(row["payload"]).get("report") or {}
            if isinstance(report,dict):
                reversal[str(report.get("action") or "unknown")]+=1
    latest=max((float(row["created"]) for row in rows if row.get("created") is not None),
               default=None)
    return {
        "schema":"niblit.market-cognition-audit/1",
        "read_only_core_db":True,
        "event_scan_limit":max_events,
        "event_rows_scanned":len(rows),
        "order_rows_scanned":len(orders),
        "newest_event_utc":(datetime.fromtimestamp(latest,timezone.utc).isoformat()
                            if latest is not None else None),
        "event_types":dict(count),
        "original_strategy_votes_scanned":dict(strategies),
        "selected_strategies_scanned":dict(chosen),
        "market_decision_traces_reconstructed":traced,
        "unique_decision_trace_ids":len(trace_ids),
        "trace_issues":dict(trace_problems),
        "core_open_order_states":dict(entry),
        "core_close_order_states":dict(close),
        "reversal_evaluation_actions":dict(reversal),
        "broker_verified_outcomes":verified_outcomes,
        "broker_outcomes_with_incomplete_evidence":outcome_incomplete,
        "demonstrated_online_learning":False,
        "adaptive_strategy_rank_ready":False,
        "adaptive_rank_blocker":"Missing broker-verified, regime-at-entry labeled training and forward-validation samples",
        "trace_limitations":"Historical trace IDs are reconstructed from frozen recorded votes; these IDs were not originally executed or emitted by the deployed Core.",
        "broker_position_limitations":"Core order states are not a fresh MT5 terminal account snapshot.",
        "execution_authorized":False,
        "actions_performed":["read_existing_sqlite_events_only"],
    }


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--ledger",required=True,type=Path)
    parser.add_argument("--out",required=True,type=Path)
    parser.add_argument("--limit",type=int,default=1000)
    args=parser.parse_args()
    # read-only and query_only protect the original 1.5 GB Core ledger.
    db=sqlite3.connect("file:"+args.ledger.resolve().as_posix()+"?mode=ro",uri=True,timeout=10)
    try:
        db.execute("PRAGMA query_only=ON")
        result=inspect_ledger(db,max_events=args.limit)
    finally:
        db.close()
    if args.out.resolve()==args.ledger.resolve():
        raise ValueError("Audit destination cannot be Core ledger")
    args.out.parent.mkdir(parents=True,exist_ok=True)
    with args.out.open("x",encoding="utf-8") as handle:
        json.dump(result,handle,indent=2,allow_nan=False)
    print("AUDIT_SAVED="+str(args.out))
    print("SIGNALS="+str(result["event_types"].get("signal",0)))
    print("TRACES="+str(result["market_decision_traces_reconstructed"]))
    print("BROKER_OUTCOMES="+str(len(result["broker_verified_outcomes"])))
    print("ONLINE_LEARNING_VERIFIED=False")


if __name__=="__main__":
    main()
