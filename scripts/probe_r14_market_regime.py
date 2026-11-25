"""Read-only native MT5 regime probe. Never imports order submission code."""
import json
from modules.mt5_bridge import MT5Bridge
from modules.market_regime_evidence import observe_regime

bridge=MT5Bridge()
snapshot=bridge.snapshot("ETHUSDm",include_context=True)
assert snapshot["connected"] is True
assert snapshot["symbol"]=="ETHUSDm"
candles=snapshot["candles"]
quote=snapshot["quote"]
account=snapshot["account"]
account_scope=str(account.get("identity") or account.get("server") or "mt5-demo-snapshot")
result=observe_regime(symbol="ETHUSDm",account=account_scope,
    cutoff=snapshot["checked_at"],candles_by_timeframe={"M5":candles},quote=quote)
features=result["timeframes"]["M5"]["features"]
print("NATIVE_MT5_DEMO=",account.get("mode")=="demo")
print("CANDLES=",len(candles))
print("BROKER_QUOTE_FRESH=",quote.get("fresh"))
print("MARKET_REGIME=",result["regime"])
print("REGIME_UNCERTAINTY=",result["uncertainty"])
print("EVIDENCE_ID=",result["evidence_id"][:20])
for k in ("atr14","adx14","rsi14","ema20","ema50","bollinger_width_fraction"):
 print(k+"=",features.get(k))
print("MISSING_TIMEFRAMES=",",".join(x for x,d in result["timeframes"].items() if d["status"]=="missing"))
print("ENTRY_AUTHORIZED=",result["execution_authorized"])
print("BROKER_ORDERS_SENT=0")
