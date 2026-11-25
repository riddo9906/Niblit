"""Broker-quote shadow counterfactual evaluation (never order execution).

Alternatives are assessed *after* the decision horizon using subsequent
recorded executable bid/ask samples. Results are modelled observations, not
actual fills, not training labels available at the original decision time.
"""
from __future__ import annotations
import hashlib
import json
import math
from collections.abc import Mapping


def _number(value, name, *, positive=False):
    if type(value) not in (int, float) or not math.isfinite(value):
        raise ValueError("Invalid "+name)
    value=float(value)
    if positive and value <= 0:
        raise ValueError("Invalid "+name)
    return value


def _hash(value):
    return hashlib.sha256(json.dumps(value,allow_nan=False,sort_keys=True,
                          separators=(",", ":")).encode()).hexdigest()


def shadow_compare(*, decision_trace: Mapping, observed_bidask: list[Mapping],
                   decision_at: float, horizon_seconds: int,
                   quantity: float, stop_distance: float,
                   target_distance: float | None = None,
                   round_trip_cost_cash: float | None = None,
                   cash_per_price_unit: float | None = None,
                   max_gap_seconds: float = 300) -> dict:
    """Evaluate registered alternatives including WAIT, with no hindsight selection.

    Quote timestamp = observation time; the first quote at/after decision_at is
    an *assumed* entry, and the horizon quote is an *assumed* exit. Stop/TP
    touches are detected only at sampled executable quotes. No claim about
    intervening highs/lows or order fill probability.
    """
    if not isinstance(decision_trace, Mapping) or not decision_trace.get("trace_id"):
        raise ValueError("Original decision trace required")
    start=_number(decision_at,"decision timestamp",positive=True)
    if type(horizon_seconds) is not int or not 60<=horizon_seconds<=86400:
        raise ValueError("Unsupported observed holding horizon")
    units=_number(quantity,"quantity",positive=True)
    stop=_number(stop_distance,"stop distance",positive=True)
    target=_number(target_distance,"target distance",positive=True) if target_distance is not None else None
    gap=_number(max_gap_seconds,"gap tolerance",positive=True)
    cost=_number(round_trip_cost_cash,"round trip cash cost") if round_trip_cost_cash is not None else None
    if cost is not None and cost<0:
        raise ValueError("Cash trading cost cannot be negative")
    factor=_number(cash_per_price_unit,"cash conversion per price unit",positive=True) if cash_per_price_unit is not None else None
    if not isinstance(observed_bidask,(list,tuple)):
        raise ValueError("Broker quote series required")
    quotes=[]
    for q in observed_bidask:
        if not isinstance(q,Mapping):raise ValueError("Malformed quote")
        ts=_number(q.get("timestamp"),"quote timestamp",positive=True)
        bid=_number(q.get("bid"),"executable bid",positive=True)
        ask=_number(q.get("ask"),"executable ask",positive=True)
        if ask<bid:raise ValueError("Crossed broker quote")
        if quotes and ts<=quotes[-1]["timestamp"]:
            raise ValueError("Quote chronology must strictly increase")
        quotes.append({"timestamp":ts,"bid":bid,"ask":ask})
    end_at=start+horizon_seconds
    observed=[q for q in quotes if start<=q["timestamp"]<=end_at]
    full=bool(observed and observed[0]["timestamp"]-start<=gap
              and end_at-observed[-1]["timestamp"]<=gap
              and all(b["timestamp"]-a["timestamp"]<=gap for a,b in zip(observed,observed[1:])))
    reason=None if full else "Missing beginning, end, or intermediate executable quotes"
    votes=decision_trace.get("strategy_votes")
    if not isinstance(votes,list):
        raise ValueError("Trace is missing original strategy votes")
    alternatives=[{"strategy":"WAIT","side":"wait"}]
    seen={"WAIT:wait"}
    for vote in votes:
        if not isinstance(vote,Mapping):raise ValueError("Invalid original strategy vote")
        name=str(vote.get("strategy") or "")
        side=vote.get("side")
        if side not in ("buy","sell","wait"):raise ValueError("Invalid strategy direction")
        key=name+":"+side
        if name and key not in seen:
            alternatives.append({"strategy":name,"side":side})
            seen.add(key)
    result=[]
    for candidate in alternatives:
        side=candidate["side"]
        basis={"strategy":candidate["strategy"],"side":side,
               "evaluation":"hypothetical_quote_path_only","broker_fill_verified":False,
               "execution_authorized":False,"observed_horizon_complete":full,
               "entry_assumption":"first sampled executable quote at or after decision",
               "exit_assumption":"first sampled stop or target; otherwise end-of-horizon quote",
               "counterfactual_r":None,"modelled_gross_cash":None,
               "modelled_net_cash":None,"price_costs_complete":False}
        if side=="wait":
            basis.update(observed_horizon_complete=full,
                         evaluation="no_trade_benchmark",counterfactual_r=0.,
                         modelled_gross_cash=0., modelled_net_cash=0.,
                         price_costs_complete=True)
            result.append(basis)
            continue
        if not full:
            result.append({**basis,"reason":reason})
            continue
        sign=1 if side=="buy" else -1
        entry=observed[0]["ask"] if sign==1 else observed[0]["bid"]
        exit_price=None
        trigger="horizon"
        exit_at=observed[-1]["timestamp"]
        for quote in observed[1:]:
            execution_price=quote["bid"] if sign==1 else quote["ask"]
            movement=sign*(execution_price-entry)
            if movement<=-stop:
                exit_price=execution_price
                exit_at=quote["timestamp"]
                trigger="sampled_stop_touch"
                break
            if target is not None and movement>=target:
                exit_price=execution_price
                exit_at=quote["timestamp"]
                trigger="sampled_target_touch"
                break
        if exit_price is None:
            exit_price=observed[-1]["bid"] if sign==1 else observed[-1]["ask"]
        price_gain=sign*(exit_price-entry)
        gross=(price_gain*units*factor) if factor is not None else None
        net=gross-cost if gross is not None and cost is not None else None
        basis.update(
            entry_quote_timestamp=observed[0]["timestamp"],entry_assumed_price=entry,
            exit_quote_timestamp=exit_at,exit_assumed_price=exit_price,
            sampled_exit_reason=trigger, counterfactual_r=price_gain/stop,
            gross_price_gain_per_unit=price_gain,
            modelled_gross_cash=gross,modelled_net_cash=net,
            price_costs_complete=(net is not None),
            quote_count=len(observed))
        result.append(basis)
    return {
        "schema":"niblit.market-counterfactual-shadow/1",
        "decision_trace_id":decision_trace["trace_id"],
        "decision_timestamp":start,
        "evaluation_horizon_end":end_at,
        "quotes_complete":full,"quote_gap_reason":reason,
        "quote_evidence_id":_hash(observed),
        "alternatives":result,
        "actual_broker_outcome":None,
        "learning_action":"shadow_only",
        "execution_authorized":False,
        "fill_model":"sampled_executable_quote_assumptions_not_broker_deals",
    }
