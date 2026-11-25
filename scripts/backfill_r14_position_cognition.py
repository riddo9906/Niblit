"""Backfill historical R14 position cognition into a separate SQLite sidecar.

Reads the canonical Core ledger ONLY in SQLite mode=ro. The sidecar records
original evidence and exact same-cycle executable quote matches. No MT5 API,
order management, historical fills invented from candles, or Core DB writes.
"""
from __future__ import annotations
import argparse
import json
import math
import sqlite3
from collections import defaultdict
from pathlib import Path

from modules.market_decision_trace import decision_trace
from modules.position_cognition_record import PositionIdentity, PositionCognitionLedger


def _obj(raw):
    try:
        value=json.loads(raw) if isinstance(raw,str) else raw
        return value if isinstance(value,dict) else {}
    except (TypeError,ValueError):
        return {}


def _numeric(value):
    return type(value) in (int,float) and math.isfinite(value)


def backfill(core, sidecar):
    """Best effort evidence ingestion, explicit skips, repeatable/idempotent."""
    core.row_factory=sqlite3.Row
    orders=[dict(r) for r in core.execute("""SELECT id,session_id,adapter,account,symbol,
        action,state,payload,result,updated FROM trading_orders
        WHERE action='open' AND adapter='mt5' ORDER BY updated DESC LIMIT 500""")]
    events=[dict(r) for r in core.execute("""SELECT id,created,kind,payload FROM trading_events
        WHERE kind IN ('signal','position_watch','trading_outcome')
        ORDER BY created DESC LIMIT 10000""")]
    signals=defaultdict(list)
    watches=defaultdict(list)
    outcomes=defaultdict(list)
    for row in events:
        event=_obj(row["payload"])
        if row["kind"]=="signal":
            signals[(event.get("session"),event.get("symbol"),event.get("bar"))].append(event)
        elif row["kind"]=="position_watch":
            watches[event.get("order")].append((row,event))
        elif row["kind"]=="trading_outcome":
            outcomes[event.get("order")].append((row,event))
    report={
        "schema":"niblit.position-cognition-backfill/1","source_db_read_only":True,
        "sidecar_db_is_separate":True,"orders_inspected":len(orders),
        "position_records_created":0,"matched_quotes":0,
        "close_deals_reconciled":0,"skipped":defaultdict(int),
        "positions":[],"orders_submitted":0,"broker_access_performed":False,
        "source":"core_sqlite_evidence_not_fresh_broker_snapshot",
    }
    for order in orders:
        result=_obj(order["result"])
        payload=_obj(order["payload"])
        observation=watches.get(order["id"],[])
        if not observation or not result.get("position_id"):
            report["skipped"]["no_matched_owned_position_watch"]+=1
            continue
        observation.sort(key=lambda a:(a[1].get("observed_at",a[0]["created"]),a[0]["id"]))
        first=observation[0][1]
        if (first.get("session")!=order["session_id"] or
                first.get("symbol")!=order["symbol"]):
            report["skipped"]["watch_session_or_symbol_mismatch"]+=1
            continue
        native=first.get("position") or {}
        ctx=payload.get("context") or {}
        decision=payload.get("decision") or {}
        if not (isinstance(native,dict) and native.get("id") is not None and
                str(native["id"])==str(result["position_id"])):
            report["skipped"]["broker_identity_mismatch"]+=1
            continue
        try:
            evidence=decision_trace(decision,adapter=order["adapter"],
                account=order["account"],symbol=order["symbol"],
                environment=str(first.get("environment") or "demo"))
            identity=PositionIdentity(str(order["adapter"]),str(order["account"]),
                str(result["position_id"]),str(order["id"]))
            entry={
                "side":native["side"],"entry":native["entry"],
                "quantity":native["quantity"],"initial_stop":ctx["initial_stop"],
                "take_profit":native.get("take_profit"),
                "strategy":ctx["strategy"],"decision_trace_id":evidence["trace_id"],
                "thesis_id":(decision.get("market_thesis") or {}).get("evidence_id"),
                "evidence_provenance":"first_core_owned_position_watch",
            }
            sidecar.record(identity,"entry",float(first.get("observed_at",observation[0][0]["created"])),
                           entry,event_id="entry:"+order["id"])
        except (KeyError,TypeError,ValueError) as exc:
            report["skipped"]["incomplete_entry_or_trace"]+=1
            continue
        matched=0
        protect=0
        first_stop=native.get("stop_loss")
        first_target=native.get("take_profit")
        for event_row,watch in observation:
            position=watch.get("position") or {}
            if (watch.get("session")!=order["session_id"] or
                watch.get("symbol")!=order["symbol"] or
                str(position.get("id"))!=str(result["position_id"])):
                report["skipped"]["watch_ownership_mismatch"]+=1
                continue
            observed_at=watch.get("observed_at",event_row["created"])
            mark=watch.get("mark")
            position=watch.get("position") or {}
            if not _numeric(observed_at) or not _numeric(mark):
                continue
            candidates=signals[(watch.get("session"),watch.get("symbol"),watch.get("bar"))]
            match=None
            for candidate in candidates:
                quote=candidate.get("quote") or {}
                if not isinstance(quote,dict) or quote.get("fresh") is not True:
                    continue
                bid,ask,stamp=quote.get("bid"),quote.get("ask"),quote.get("timestamp")
                if not all(_numeric(v) for v in (bid,ask,stamp)):
                    continue
                if not (0<=observed_at-stamp<=60 and ask>=bid>0):
                    continue
                executable=bid if position.get("side")=="buy" else ask
                if abs(executable-mark)<=1e-6:
                    match=quote
                    break
            if match is not None:
                record={"bid":match["bid"],"ask":match["ask"],
                        "quantity":position["quantity"],
                        "quote_timestamp":match["timestamp"],
                        "floating_profit":position.get("profit")}
                try:
                    sidecar.record(identity,"mark",float(observed_at),record,
                                   event_id="mark:"+event_row["id"])
                    matched+=1
                except (ValueError,TypeError,KeyError):
                    report["skipped"]["invalid_or_inconsistent_mark"]+=1
            stop=position.get("stop_loss")
            target=position.get("take_profit")
            if stop!=first_stop or target!=first_target:
                try:
                    sidecar.record(identity,"protection",float(observed_at),
                        {"stop_loss":stop,"take_profit":target},
                        event_id="protection:"+event_row["id"])
                    protect+=1
                except (ValueError,TypeError):
                    report["skipped"]["invalid_protection_change"]+=1
                first_stop,first_target=stop,target
        closes=0
        for outcome_row,outcome in outcomes.get(order["id"],[]):
            evidence=outcome.get("evidence") or {}
            if (outcome.get("session")!=order["session_id"] or
                outcome.get("symbol")!=order["symbol"] or
                str(evidence.get("position_id"))!=str(result["position_id"])):
                report["skipped"]["close_ownership_mismatch"]+=1
                continue
            if not isinstance(evidence,dict) or evidence.get("state")!="closed":
                continue
            fills=evidence.get("exit_fills")
            realized=evidence.get("realized_net")
            if not isinstance(fills,list) or not _numeric(realized) or not fills:
                report["skipped"]["unattributed_exit_fills"]+=1
                continue
            volumes=[];prices=[]
            for fill in fills:
                if (not isinstance(fill,dict) or
                    not _numeric(fill.get("volume")) or
                    not _numeric(fill.get("price")) or
                    fill["volume"]<=0 or fill["price"]<=0):
                    volumes=[];break
                volumes.append(float(fill["volume"]))
                prices.append(float(fill["price"]))
            if not volumes:
                report["skipped"]["invalid_exit_deals"]+=1
                continue
            size=sum(volumes)
            weighted=sum(a*b for a,b in zip(volumes,prices))/size
            try:
                sidecar.record(identity,"deal",float(outcome_row["created"]),
                    {"action":"close","quantity":size,"price":weighted,
                     "realized_net":float(realized),
                     "evidence_provenance":"broker_reconciled_core_exit_fills",
                     "broker_fills_count":len(fills)},
                    event_id="broker-close:"+outcome_row["id"])
                closes+=1
            except (ValueError,TypeError):
                report["skipped"]["invalid_reconciled_close"]+=1
        try:
            reconstructed=sidecar.replay(identity)
        except (ValueError,TypeError):
            report["skipped"]["replay_validation_error"]+=1
            continue
        report["position_records_created"]+=1
        report["matched_quotes"]+=matched
        report["close_deals_reconciled"]+=closes
        report["positions"].append({
            "position_key":identity.key,"symbol":order["symbol"],
            "original_strategy":ctx["strategy"],"observations_matched":matched,
            "position_state":reconstructed["position_state"],
            "reconciled_close_count":closes,
            "sampled_mfe_r":reconstructed["observed_mfe_r"],
            "sampled_mae_r":reconstructed["observed_mae_r"],
            "broker_realized_net":reconstructed["broker_realized_net"],
            "broker_realized_net_complete":reconstructed["realized_net_complete"],
            "thesis_evidence_id":entry.get("thesis_id"),
            "trace_origin":"retrospective_from_frozen_original_order",
            "position_identity_verified":True,
        })
    report["skipped"]=dict(report["skipped"])
    return report


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--core",type=Path,required=True)
    parser.add_argument("--sidecar",type=Path,required=True)
    parser.add_argument("--report",type=Path,required=True)
    args=parser.parse_args()
    if len({args.core.resolve(),args.sidecar.resolve(),args.report.resolve()})!=3:
        raise ValueError("Core, sidecar and report must be distinct files")
    db=sqlite3.connect("file:"+args.core.resolve().as_posix()+"?mode=ro",uri=True)
    try:
        db.execute("PRAGMA query_only=ON")
        sidecar=PositionCognitionLedger(args.sidecar)
        result=backfill(db,sidecar)
    finally:
        db.close()
    args.report.parent.mkdir(parents=True,exist_ok=True)
    with args.report.open("x",encoding="utf-8") as h:
        json.dump(result,h,indent=2,allow_nan=False)
    print("POSITION_RECORDS="+str(result["position_records_created"]))
    print("EXACT_BID_ASK_MATCHES="+str(result["matched_quotes"]))
    print("BROKER_CLOSES="+str(result["close_deals_reconciled"]))
    print("CORE_LEDGER_READ_ONLY=True")
    print("REPORT="+str(args.report))


if __name__=="__main__":
    main()
