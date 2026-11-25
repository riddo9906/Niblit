"""Pure venue/account route descriptors for deterministic execution plans.

Routing is a decision-data operation. Transport creation and order submission
remain external to this module; no credentials, side effects or broker SDK.
"""
import hashlib
import json
from dataclasses import dataclass

ROUTE_SCHEMA = "niblit.execution-route/1"
VENUES = {"mt5": {"demo", "live"}, "freqtrade": {"dry-run", "live"}}
ACTION_MAP = {"buy": "buy", "sell": "sell", "long": "buy", "short": "sell"}


@dataclass(frozen=True)
class VenueBinding:
    adapter: str
    environment: str
    account: str
    symbol: str
    instrument: str
    currency: str
    identity: str

    def __post_init__(self):
        if self.adapter not in VENUES or self.environment not in VENUES[self.adapter]:
            raise ValueError("Unsupported venue/environment combination")
        if not all(isinstance(v, str) and v.strip() for v in
                   (self.account, self.symbol, self.instrument, self.currency, self.identity)):
            raise ValueError("Full account and instrument binding required")
        if self.adapter == "mt5" and not self.identity.startswith("mt5:"):
            raise ValueError("MT5 server and terminal identity required")
        if self.adapter == "freqtrade" and not self.identity.startswith("freqtrade:"):
            raise ValueError("Freqtrade exchange/config identity required")


def resolve_route(binding, decision, *, risk_profile, feed_identity, plan_hash):
    """Return an immutable, content-addressed route description.

    Caller supplies a separately verified account binding and broker-valued
    trade plan. This function does not create a broker transport, decide
    whether to execute or infer eligibility from profitable demo outcomes.
    """
    if not isinstance(binding, VenueBinding) or not isinstance(decision, dict):
        raise ValueError("Binding and decision required")
    if decision.get("side") not in ACTION_MAP:
        raise ValueError("No directional execution route for WAIT")
    if decision.get("symbol") != binding.symbol:
        raise ValueError("Decision instrument differs from selected venue")
    if decision.get("venue") not in (None, binding.adapter):
        raise ValueError("Decision venue differs from selected venue")
    if not isinstance(plan_hash, str) or len(plan_hash) != 64 or any(c not in "0123456789abcdef" for c in plan_hash):
        raise ValueError("Exact canonical plan hash required")
    if not isinstance(feed_identity, str) or not feed_identity.strip():
        raise ValueError("Market feed identity required")
    if not isinstance(risk_profile, str) or not risk_profile.strip():
        raise ValueError("Risk profile revision required")
    item = {
        "schema": ROUTE_SCHEMA,
        "adapter": binding.adapter,
        "environment": binding.environment,
        "account": binding.account,
        "symbol": binding.symbol,
        "instrument": binding.instrument,
        "currency": binding.currency,
        "identity": binding.identity,
        "side": ACTION_MAP[decision["side"]],
        "feed_identity": feed_identity,
        "risk_profile": risk_profile,
        "source_plan_hash": plan_hash,
        "execution_stage": "ROUTE_DESCRIPTION",
        "broker_order_id": None,
        "prediction_claim": "none",
    }
    normalized = json.dumps(item, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return {**item, "route_hash": hashlib.sha256(normalized.encode()).hexdigest()}


def route_difference(left, right):
    """Explain which exact binding dimensions separate two proposed routes."""
    if not isinstance(left, dict) or not isinstance(right, dict):
        raise ValueError("Two route records required")
    fields = ("adapter", "environment", "account", "symbol", "instrument",
              "currency", "identity", "feed_identity", "risk_profile", "source_plan_hash")
    return {field: (left.get(field), right.get(field)) for field in fields
            if left.get(field) != right.get(field)}
