"""Cost-aware broker-outcome strategy rankings: research and SHADOW ONLY.

No MT5/Freqtrade connection, trading order, broker authority, or automatic
promotion. The decision timestamp cannot consume not-yet-closed trades.
"""
from __future__ import annotations

import math
import statistics
from collections import defaultdict
from collections.abc import Mapping


def _finite(value):
    if type(value) not in (int,float) or not math.isfinite(value):
        raise ValueError("Non-finite performance record")
    return float(value)


def _summary(samples):
    values=[item["net_realized_r"] for item in samples]
    count=len(values)
    mean=statistics.mean(values)
    stdev=statistics.stdev(values) if count>1 else None
    # Conservative empirical ranking heuristic, NOT a calibrated probability.
    lower=mean-1.96*stdev/math.sqrt(count) if stdev is not None else None
    return {"n":count,"mean_net_r":mean,"std_net_r":stdev,
            "lower_bound_heuristic":lower,
            "median_net_r":statistics.median(values),
            "worst_net_r":min(values),
            "net_r_total":sum(values),
            "unique_broker_trades":count,
            "wins":sum(1 for x in values if x>0),
            "losses":sum(1 for x in values if x<0),
            "flat":sum(1 for x in values if x==0)}


def shadow_rank(*, outcomes, account, symbol, timeframe, regime,
                evaluated_at, train_before, min_train=30, min_validation=10):
    if any(not isinstance(v,str) or not v for v in (account,symbol,timeframe,regime)):
        raise ValueError("Explicit account, market and regime scope required")
    now=_finite(evaluated_at)
    boundary=_finite(train_before)
    if now<=boundary:
        raise ValueError("Train/validation boundary must be before evaluation")
    if type(min_train) is not int or min_train<20 or type(min_validation) is not int or min_validation<10:
        raise ValueError("Insufficient minimum-sample policy")
    if not isinstance(outcomes,(list,tuple)):
        raise ValueError("Broker outcome records required")
    unique=set()
    buckets=defaultdict(lambda:{"train":[],"validation":[]})
    excluded={"unverified_or_cost_unknown":0,"out_of_scope":0,"future_at_evaluation":0}
    for record in outcomes:
        if not isinstance(record,Mapping):
            raise ValueError("Malformed broker outcome")
        # Enforce account separation *before* looking at labels or values.
        if (record.get("account"),record.get("symbol"),record.get("timeframe"),
            record.get("regime"))!=(account,symbol,timeframe,regime):
            excluded["out_of_scope"]+=1
            continue
        ident=record.get("broker_deal_group_id")
        if not isinstance(ident,str) or not ident:
            raise ValueError("Broker outcome identity required")
        if ident in unique:
            raise ValueError("Duplicate reconciled broker outcome")
        unique.add(ident)
        closed=_finite(record.get("closed_at"))
        if closed>=now:
            excluded["future_at_evaluation"]+=1
            continue
        if not (record.get("broker_verified") is True and
                record.get("all_fees_included") is True and
                record.get("actual_fill") is True):
            excluded["unverified_or_cost_unknown"]+=1
            continue
        strategy=record.get("entry_strategy")
        if not isinstance(strategy,str) or not strategy:
            raise ValueError("Missing original broker entry strategy")
        value=_finite(record.get("net_realized_r"))
        bucket="train" if closed<boundary else "validation"
        buckets[strategy][bucket].append({"net_realized_r":value,"closed_at":closed,
                                           "broker_deal_group_id":ident})
    rows=[]
    for strategy, partitions in sorted(buckets.items()):
        training=partitions["train"]
        validation=partitions["validation"]
        enough=len(training)>=min_train and len(validation)>=min_validation
        train_report=_summary(training) if training else None
        validation_report=_summary(validation) if validation else None
        rows.append({
            "entry_strategy":strategy,
            "train":train_report,
            "validation":validation_report,
            "evidence_gate":"eligible_for_shadow_comparison" if enough else "insufficient_broker_outcomes",
            "shadow_rank_score":(validation_report["lower_bound_heuristic"] if enough else None),
            "execution_authorized":False,
            "performance_guarantee":False,
        })
    eligible=[row for row in rows if row["shadow_rank_score"] is not None]
    eligible.sort(key=lambda row:(-row["shadow_rank_score"],row["entry_strategy"]))
    for rank,row in enumerate(eligible,start=1):
        row["shadow_rank"]=rank
    return {
        "schema":"niblit.strategy-performance-shadow/1",
        "scope":{"account":account,"symbol":symbol,"timeframe":timeframe,"regime":regime},
        "evaluated_at":now,"train_before":boundary,
        "minimum_training_outcomes":min_train,"minimum_validation_outcomes":min_validation,
        "counted_verified_records":sum(len(p["train"])+len(p["validation"]) for p in buckets.values()),
        "excluded":excluded,"strategies":rows,
        "shadow_leader":eligible[0]["entry_strategy"] if eligible else None,
        "selection_authority":"none",
        "promotion_authorized":False,
        "statistical_limitations":"Normal-approximation lower-bound heuristic, not a validated confidence interval or profitable edge. Overlap, dependency, drift and sample selection require further tests.",
        "learning_action":"rank_only",
    }
