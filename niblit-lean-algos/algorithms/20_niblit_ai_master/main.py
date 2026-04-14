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

import json
import math
import os
from collections import deque
from typing import Optional


# ──────────────────────────────────────────────────────────────────────────────
#  Niblit AI Master Algorithm
#
#  This is the flagship integration algorithm.  It:
#    1. Reads NiblitBridge for signal (BUY/SELL/HOLD), confidence,
#       regime and risk_pct.
#    2. Runs EMA 9/21 crossover as an internal fallback signal.
#    3. Runs RSI(14) as a trend/momentum filter.
#    4. Combines signals:  70% Niblit weight + 30% internal weight.
#    5. Uses Niblit-suggested risk_pct for position sizing.
#    6. Logs all Niblit values every bar.
#    7. Supports BTC, ETH and SPY via NIBLIT_SYMBOL env var.
#    8. Writes back performance to a JSON results file for Niblit to read.
# ──────────────────────────────────────────────────────────────────────────────

_NIBLIT_WEIGHT   = 0.70
_INTERNAL_WEIGHT = 0.30
_DEFAULT_RISK    = 0.02
_ATR_MULT        = 1.5
_RESULTS_FILE    = "niblit_algo_results.json"   # written relative to working dir


def _resolve_symbol() -> str:
    """Read NIBLIT_SYMBOL env var; default to SPY."""
    return os.environ.get("NIBLIT_SYMBOL", "SPY").upper()


class NiblitAiMaster(QCAlgorithm):
    """
    Niblit AI Master Algorithm.

    Flagship integration between QuantConnect LEAN and the Niblit AI brain.
    All signal weighting, regime handling and risk sizing is driven
    primarily by NiblitBridge with an internal EMA/RSI fallback.
    """

    def initialize(self) -> None:
        self.set_start_date(2022, 1, 1)
        self.set_end_date(2024, 6, 1)
        self.set_cash(100_000)

        if not self.live_mode:
            self.set_brokerage_model(BrokerageName.PAPER_BROKERAGE)

        # Resolve symbol from environment variable
        self._ticker = _resolve_symbol()
        self.log(f"NiblitAiMaster starting with symbol={self._ticker}")

        # Add asset (crypto or equity)
        if self._ticker in ("BTCUSD", "BTCUSDT", "ETHUSD", "ETHUSDT"):
            self._sym = self.add_crypto(self._ticker.replace("USDT", "USD"),
                                        Resolution.DAILY).symbol
            self._is_crypto = True
        else:
            self._sym = self.add_equity(self._ticker, Resolution.DAILY).symbol
            self._is_crypto = False

        # Internal indicators
        self._ema9  = self.ema(self._sym, 9,  Resolution.DAILY)
        self._ema21 = self.ema(self._sym, 21, Resolution.DAILY)
        self._rsi   = self.rsi(self._sym, 14, Resolution.DAILY)
        self._atr   = self.atr(self._sym, 14, Resolution.DAILY)
        self._sma50 = self.sma(self._sym, 50, Resolution.DAILY)

        self.set_warm_up(55)

        # NiblitBridge
        self._bridge: Optional[object] = None
        if _NIBLIT_AVAILABLE and _NiblitBridge is not None:
            try:
                self._bridge = _NiblitBridge()
                self.log("NiblitBridge connected successfully.")
            except Exception as exc:
                self.log(f"NiblitBridge connection failed: {exc}")

        # State
        self._stop_price: float = 0.0
        self._position:   int   = 0      # +1 long, -1 short, 0 flat
        self._entry_price: float = 0.0
        self._bar_count:   int   = 0

        # Performance tracking for JSON write-back
        self._trade_count:  int   = 0
        self._win_count:    int   = 0
        self._total_pnl:    float = 0.0

        # Rolling price buffer for return calculation (write-back)
        self._price_buf: deque = deque(maxlen=252)

    # ------------------------------------------------------------------ #
    #  Main bar handler                                                    #
    # ------------------------------------------------------------------ #
    def on_data(self, data: Slice) -> None:
        if self.is_warming_up:
            return
        if self._sym not in data.bars:
            return
        if not (self._ema9.is_ready and self._ema21.is_ready
                and self._rsi.is_ready and self._atr.is_ready):
            return

        self._bar_count += 1
        price = data.bars[self._sym].close
        self._price_buf.append(price)

        ema9  = self._ema9.current.value
        ema21 = self._ema21.current.value
        rsi   = self._rsi.current.value
        atr   = self._atr.current.value
        sma50 = self._sma50.current.value if self._sma50.is_ready else price

        # ---- Step 1: NiblitBridge signal --------------------------------
        niblit_action     = "HOLD"
        niblit_confidence = 0.5
        niblit_regime     = "unknown"
        niblit_risk_pct   = _DEFAULT_RISK

        if self._bridge is not None:
            try:
                sig           = self._bridge.get_full()
                _raw_signal   = sig.get("signal") if sig else None
                niblit_action = (_raw_signal or "HOLD").upper()
                niblit_confidence = float(sig.get("confidence", 0.5)) if sig else 0.5
                niblit_regime     = sig.get("regime", "unknown") if sig else "unknown"
                niblit_risk_pct   = float(sig.get("risk_pct", _DEFAULT_RISK)) if sig else _DEFAULT_RISK
                self.log(
                    f"[Niblit] action={niblit_action}  "
                    f"confidence={niblit_confidence:.3f}  "
                    f"regime={niblit_regime}  "
                    f"risk_pct={niblit_risk_pct:.4f}"
                )
            except Exception as exc:
                self.log(f"NiblitBridge signal error: {exc}")

        # ---- Step 2: Internal EMA + RSI signal --------------------------
        ema_bull  = ema9 > ema21
        ema_bear  = ema9 < ema21
        rsi_ok_long  = 30 < rsi < 70   # not extreme
        rsi_ok_short = 30 < rsi < 70
        trend_up     = price > sma50
        trend_down   = price < sma50

        # Internal signal: +1 = bullish, -1 = bearish, 0 = neutral
        if ema_bull and rsi_ok_long and trend_up:
            internal_score = 1.0
        elif ema_bear and rsi_ok_short and trend_down:
            internal_score = -1.0
        else:
            internal_score = 0.0

        # ---- Step 3: Weighted combination --------------------------------
        niblit_score = (1.0 if niblit_action == "BUY"
                        else -1.0 if niblit_action == "SELL"
                        else 0.0) * niblit_confidence

        combined_score = (_NIBLIT_WEIGHT   * niblit_score +
                          _INTERNAL_WEIGHT * internal_score)

        self.log(
            f"[Signal] price={price:.4f}  EMA9={ema9:.4f}  EMA21={ema21:.4f}  "
            f"RSI={rsi:.1f}  internal={internal_score:.2f}  "
            f"niblit={niblit_score:.2f}  combined={combined_score:.3f}  "
            f"regime={niblit_regime}"
        )

        # ---- Step 4: Risk sizing using Niblit-suggested risk_pct ---------
        equity    = self.portfolio.total_portfolio_value
        stop_dist = _ATR_MULT * atr if atr > 0 else price * 0.02
        risk_pct  = max(0.005, min(0.05, niblit_risk_pct))   # clamp 0.5–5%

        # ---- Step 5: Stop loss check ------------------------------------
        if self._position != 0 and self._stop_price > 0:
            stop_hit = (self._position ==  1 and price <= self._stop_price) or \
                       (self._position == -1 and price >= self._stop_price)
            if stop_hit:
                pnl = (price - self._entry_price) * self._position
                self._record_trade(pnl)
                self.liquidate(self._sym)
                self._position    = 0
                self._stop_price  = 0.0
                self._entry_price = 0.0
                self.log(f"Stop loss hit @ {price:.4f}  pnl={pnl:.2f}")
                return

        # ---- Step 6: Regime-based risk override -------------------------
        # In 'ranging' regime: cut size in half; in 'volatile' regime: flat
        if niblit_regime in ("ranging", "sideways"):
            risk_pct *= 0.5
            self.log(f"Regime '{niblit_regime}': risk reduced to {risk_pct:.4f}")
        elif niblit_regime in ("volatile", "crash", "bear"):
            # Exit any existing long and stay flat
            if self._position == 1:
                pnl = (price - self._entry_price)
                self._record_trade(pnl)
                self.liquidate(self._sym)
                self._position    = 0
                self._stop_price  = 0.0
                self._entry_price = 0.0
                self.log(f"Regime '{niblit_regime}': forced exit @ {price:.4f}")
            return

        # ---- Step 7: Trade execution ------------------------------------
        want_long  = combined_score > 0.20
        want_short = combined_score < -0.20

        if want_long and self._position != 1:
            # Close any short first
            if self._position == -1:
                pnl = (self._entry_price - price)
                self._record_trade(pnl)
                self.liquidate(self._sym)
                self._entry_price = 0.0

            qty = self._compute_qty(equity, risk_pct, stop_dist, price)
            if qty > 0:
                self.market_order(self._sym, qty)
                self._stop_price  = price - stop_dist
                self._position    = 1
                self._entry_price = price
                self.log(f"LONG {qty} @ {price:.4f}  stop={self._stop_price:.4f}  "
                         f"risk_pct={risk_pct:.4f}  combined={combined_score:.3f}")

        elif want_short and self._position != -1:
            # Close any long first
            if self._position == 1:
                pnl = (price - self._entry_price)
                self._record_trade(pnl)
                self.liquidate(self._sym)
                self._entry_price = 0.0

            qty = self._compute_qty(equity, risk_pct, stop_dist, price)
            if qty > 0:
                self.market_order(self._sym, -qty)
                self._stop_price  = price + stop_dist
                self._position    = -1
                self._entry_price = price
                self.log(f"SHORT {qty} @ {price:.4f}  stop={self._stop_price:.4f}  "
                         f"risk_pct={risk_pct:.4f}  combined={combined_score:.3f}")

        elif not want_long and not want_short and self._position != 0:
            # Signal went neutral → exit
            pnl = (price - self._entry_price) * self._position
            self._record_trade(pnl)
            self.liquidate(self._sym)
            self._position    = 0
            self._stop_price  = 0.0
            self._entry_price = 0.0
            self.log(f"Signal neutral → flat @ {price:.4f}  pnl={pnl:.2f}")

    # ------------------------------------------------------------------ #
    #  Helpers                                                             #
    # ------------------------------------------------------------------ #
    def _compute_qty(self, equity: float, risk_pct: float,
                     stop_dist: float, price: float):
        """Compute position quantity respecting risk and portfolio limits."""
        if stop_dist <= 0 or price <= 0:
            return 0
        dollar_risk  = equity * risk_pct
        max_from_risk = dollar_risk / stop_dist
        max_from_cap  = (equity * 0.35) / price
        qty_raw = min(max_from_risk, max_from_cap)
        if self._is_crypto:
            return round(qty_raw, 6)
        return int(qty_raw)

    def _record_trade(self, pnl: float) -> None:
        self._trade_count += 1
        self._total_pnl   += pnl
        if pnl > 0:
            self._win_count += 1

    def _write_results(self) -> None:
        """Write performance stats to JSON file for Niblit to consume."""
        equity       = self.portfolio.total_portfolio_value
        win_rate     = (self._win_count / self._trade_count
                        if self._trade_count > 0 else 0.0)
        prices       = list(self._price_buf)
        total_return = 0.0
        if len(prices) >= 2 and prices[0] != 0:
            total_return = (prices[-1] / prices[0]) - 1.0

        results = {
            "symbol":        self._ticker,
            "final_equity":  round(equity, 2),
            "total_pnl":     round(self._total_pnl, 2),
            "trade_count":   self._trade_count,
            "win_count":     self._win_count,
            "win_rate":      round(win_rate, 4),
            "total_return":  round(total_return, 4),
            "bar_count":     self._bar_count,
            "niblit_available": _NIBLIT_AVAILABLE,
        }

        try:
            results_path = os.path.join(
                os.path.dirname(os.path.abspath(__file__)),
                _RESULTS_FILE,
            )
            with open(results_path, "w") as fh:
                json.dump(results, fh, indent=2)
            self.log(f"Results written to {results_path}")
        except Exception as exc:
            self.log(f"Could not write results file: {exc}")

    # ------------------------------------------------------------------ #
    #  Event hooks                                                         #
    # ------------------------------------------------------------------ #
    def on_order_event(self, order_event: OrderEvent) -> None:
        self.log(str(order_event))

    def on_end_of_algorithm(self) -> None:
        # Final exit
        if self._position != 0:
            price = self.securities[self._sym].price
            pnl   = (price - self._entry_price) * self._position
            self._record_trade(pnl)

        win_rate = (self._win_count / self._trade_count
                    if self._trade_count > 0 else 0.0)
        self.log(
            f"=== NiblitAiMaster Final Report ===\n"
            f"  Portfolio value : {self.portfolio.total_portfolio_value:.2f}\n"
            f"  Total P&L       : {self._total_pnl:.2f}\n"
            f"  Trades          : {self._trade_count}\n"
            f"  Win rate        : {win_rate*100:.1f}%\n"
            f"  NiblitBridge    : {'connected' if self._bridge else 'unavailable'}"
        )

        # Write performance JSON for Niblit ingestion
        self._write_results()
