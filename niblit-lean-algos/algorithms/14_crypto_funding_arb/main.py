# region imports
from AlgorithmImports import *
# endregion

# Optional Niblit bridge
try:
    import sys as _sys, os as _os
    _sys.path.insert(0, _os.path.join(_os.path.dirname(__file__), '..', '..', 'niblit_bridge'))
    from connector import NiblitBridge as _NiblitBridge
    _NIBLIT_AVAILABLE = True
except Exception:
    _NIBLIT_AVAILABLE = False
    _NiblitBridge = None

import math
from collections import deque
from typing import Dict


# ──────────────────────────────────────────────────────────────────────────────
#  Simulated Funding Rate Model
# ──────────────────────────────────────────────────────────────────────────────

class _FundingModel:
    """
    Simulated perpetual-futures funding rate estimator.

    Real exchanges charge / pay funding every 8 hours.
    We approximate using the relationship between price momentum and
    an open-interest proxy (rolling volume change).

    Positive funding  → longs pay shorts (market is bullish, trim longs).
    Negative funding  → shorts pay longs (market is bearish, trim shorts).
    """

    _FUNDING_INTERVAL_H = 8      # hours
    _BASE_RATE          = 0.0001 # 0.01% per 8h (Binance default)

    def __init__(self, window: int = 24) -> None:
        self._window = window
        self._returns: deque = deque(maxlen=window)
        self._volumes: deque = deque(maxlen=window)

    def update(self, close: float, volume: float, prev_close: float) -> None:
        if prev_close > 0:
            self._returns.append((close - prev_close) / prev_close)
        self._volumes.append(volume)

    def estimated_rate(self) -> float:
        """Return estimated 8-hour funding rate as decimal."""
        if len(self._returns) < 5:
            return self._BASE_RATE
        avg_ret  = sum(self._returns) / len(self._returns)
        # Positive returns → positive funding premium
        premium  = avg_ret * 10.0   # scale factor
        rate     = self._BASE_RATE + premium
        return max(-0.005, min(0.005, rate))   # cap at ±0.5% per 8h

    def daily_cost(self, position_value: float) -> float:
        """Total daily funding cost for a given position value."""
        rate_8h = self.estimated_rate()
        return abs(rate_8h) * 3 * position_value   # 3 intervals/day


# ──────────────────────────────────────────────────────────────────────────────
#  Algorithm
# ──────────────────────────────────────────────────────────────────────────────
class CryptoFundingArb(QCAlgorithm):
    """
    Crypto Momentum Strategy with Funding Awareness.

    Assets:   BTC and ETH (crypto equities via QuantConnect).
    Signal:   RSI + MACD crossover (per asset).
    Funding:  Estimate perpetual funding rate; reduce position size when
              funding cost erodes expected profit.
    Risk:     ATR stop; max 15% risk per trade; max 60% allocated total.
    """

    _SYMBOLS        = ["BTCUSD", "ETHUSD"]
    _ATR_MULT       = 1.5
    _RISK_PCT       = 0.015
    _MAX_ALLOC      = 0.60
    _FUNDING_THRESH = 0.003    # 0.3% daily funding → reduce size by 50%

    def initialize(self) -> None:
        self.set_start_date(2021, 1, 1)
        self.set_end_date(2024, 1, 1)
        self.set_cash(100_000)

        if not self.live_mode:
            self.set_brokerage_model(BrokerageName.PAPER_BROKERAGE)

        self._syms     = []
        self._rsi:     Dict = {}
        self._macd:    Dict = {}
        self._atr:     Dict = {}
        self._funding: Dict = {}

        for ticker in self._SYMBOLS:
            sym = self.add_crypto(ticker, Resolution.DAILY).symbol
            self._syms.append(sym)
            self._rsi[sym]     = self.rsi(sym, 14, Resolution.DAILY)
            self._macd[sym]    = self.macd(sym, 12, 26, 9,
                                           MovingAverageType.EXPONENTIAL,
                                           Resolution.DAILY)
            self._atr[sym]     = self.atr(sym, 14, Resolution.DAILY)
            self._funding[sym] = _FundingModel(window=24)

        self.set_warm_up(60)

        self._prev_prices: Dict = {}
        self._stop_prices: Dict = {}
        self._positions:   Dict = {s: 0 for s in self._syms}

        self._bridge = None
        if _NIBLIT_AVAILABLE and _NiblitBridge is not None:
            try:
                self._bridge = _NiblitBridge()
                self.log("NiblitBridge connected.")
            except Exception as exc:
                self.log(f"NiblitBridge init failed: {exc}")

    def on_data(self, data: Slice) -> None:
        if self.is_warming_up:
            return

        for sym in self._syms:
            if sym not in data.bars:
                continue
            bar = data.bars[sym]
            self._process_asset(sym, bar)

    def _process_asset(self, sym: Symbol, bar: TradeBar) -> None:
        price  = bar.close
        volume = bar.volume

        if not (self._rsi[sym].is_ready and self._macd[sym].is_ready
                and self._atr[sym].is_ready):
            self._prev_prices[sym] = price
            return

        prev_price = self._prev_prices.get(sym, price)
        self._funding[sym].update(price, volume, prev_price)
        self._prev_prices[sym] = price

        rsi       = self._rsi[sym].current.value
        macd_val  = self._macd[sym].current.value
        sig_val   = self._macd[sym].signal.current.value
        atr       = self._atr[sym].current.value
        fund_rate = self._funding[sym].estimated_rate()
        daily_cost= self._funding[sym].daily_cost(
            self.portfolio[sym].holdings_value if self.portfolio[sym].invested else 1.0
        )

        self.log(f"{sym}  RSI={rsi:.1f}  MACD={macd_val:.2f}  "
                 f"funding_8h={fund_rate*100:.3f}%  daily_cost={daily_cost:.2f}")

        # Stop loss
        stop = self._stop_prices.get(sym, 0.0)
        pos  = self._positions[sym]
        if pos != 0 and stop > 0:
            stop_hit = (pos == 1 and price <= stop) or (pos == -1 and price >= stop)
            if stop_hit:
                self.liquidate(sym)
                self._positions[sym]   = 0
                self._stop_prices[sym] = 0.0
                self.log(f"Stop hit {sym} @ {price:.2f}")
                return

        # Signals
        bull_signal = rsi < 60 and macd_val > sig_val and rsi > 30
        bear_exit   = rsi > 65 or macd_val < sig_val

        # Funding cost penalty: reduce size when funding is expensive
        funding_penalty = self._FUNDING_THRESH
        size_mult = 0.5 if abs(fund_rate) * 3 > funding_penalty else 1.0

        # Niblit signal
        niblit_boost = 1.0
        if self._bridge is not None:
            try:
                act = (self._bridge.get_signal() or "HOLD").upper()
                conf = self._bridge.get_confidence()
                if act == "BUY":
                    niblit_boost = 1.0 + 0.2 * conf
                elif act == "SELL":
                    niblit_boost = max(0.3, 1.0 - 0.3 * conf)
                self.log(f"Niblit {sym}: {act} conf={conf:.3f}")
            except Exception as exc:
                self.log(f"Niblit error: {exc}")

        equity    = self.portfolio.total_portfolio_value
        stop_dist = self._ATR_MULT * atr

        if bull_signal and pos == 0:
            dollar_risk = equity * self._RISK_PCT * size_mult * niblit_boost
            # Total crypto allocation cap
            crypto_alloc = sum(
                self.portfolio[s].holdings_value for s in self._syms
                if self.portfolio[s].invested
            ) / equity
            if crypto_alloc >= self._MAX_ALLOC:
                return
            qty = round((dollar_risk / stop_dist), 6) if stop_dist > 0 else 0
            if qty > 0:
                self.market_order(sym, qty)
                self._stop_prices[sym] = price - stop_dist
                self._positions[sym]   = 1
                self.log(f"BUY {qty:.6f} {sym} @ {price:.2f}  "
                         f"size_mult={size_mult:.2f}  niblit_boost={niblit_boost:.2f}")

        elif bear_exit and pos == 1:
            self.liquidate(sym)
            self._positions[sym]   = 0
            self._stop_prices[sym] = 0.0
            self.log(f"EXIT {sym} @ {price:.2f}")

    def on_order_event(self, order_event: OrderEvent) -> None:
        self.log(str(order_event))

    def on_end_of_algorithm(self) -> None:
        self.log(f"Final value: {self.portfolio.total_portfolio_value:.2f}")
