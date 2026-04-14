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

from collections import deque
from typing import Dict, List, Optional


class DualMomentum(QCAlgorithm):
    """
    Dual Momentum Rotation – Antonacci (2014).

    Universe:     SPY (US equities), EFA (international), AGG (bonds), BIL (T-bills).
    Absolute Mom: Asset's 12-month return > BIL (risk-free) → absolute positive.
    Relative Mom: Rank risky assets (SPY, EFA, AGG) by 12-month return.
    Logic:
        1. Compute 12-month total return for each asset.
        2. Best risky asset = highest return among SPY, EFA, AGG.
        3. If best risky asset also beats BIL → hold best risky asset.
        4. Else (absolute momentum negative) → hold BIL (risk-off).
    Rebalance:    Monthly.
    """

    _RISKY  = ["SPY", "EFA", "AGG"]
    _RF     = "BIL"                  # risk-free / cash proxy
    _LOOKBACK = 252                  # ~12 months
    _ALL    = ["SPY", "EFA", "AGG", "BIL"]

    def initialize(self) -> None:
        self.set_start_date(2010, 1, 1)
        self.set_end_date(2024, 1, 1)
        self.set_cash(100_000)

        if not self.live_mode:
            self.set_brokerage_model(BrokerageName.PAPER_BROKERAGE)

        self._syms: Dict[str, Symbol] = {}
        for ticker in self._ALL:
            self._syms[ticker] = self.add_equity(ticker, Resolution.DAILY).symbol

        self._price_hist: Dict[Symbol, deque] = {
            s: deque(maxlen=self._LOOKBACK + 2) for s in self._syms.values()
        }

        self.set_warm_up(self._LOOKBACK + 5)

        self._held_ticker: Optional[str] = None

        # Monthly rebalance
        self.schedule.on(
            self.date_rules.month_start(self._ALL[0]),
            self.time_rules.after_market_open(self._ALL[0], 30),
            self._rebalance,
        )

        self._bridge = None
        if _NIBLIT_AVAILABLE and _NiblitBridge is not None:
            try:
                self._bridge = _NiblitBridge()
                self.log("NiblitBridge connected.")
            except Exception as exc:
                self.log(f"NiblitBridge init failed: {exc}")

    # ------------------------------------------------------------------ #
    def on_data(self, data: Slice) -> None:
        for ticker, sym in self._syms.items():
            if sym in data.bars:
                self._price_hist[sym].append(data.bars[sym].close)

    # ------------------------------------------------------------------ #
    def _twelve_month_return(self, ticker: str) -> Optional[float]:
        """Returns 12-month price return or None if insufficient data."""
        sym  = self._syms[ticker]
        hist = list(self._price_hist[sym])
        if len(hist) < self._LOOKBACK:
            return None
        p_now  = hist[-1]
        p_year = hist[-self._LOOKBACK]
        return (p_now / p_year) - 1.0 if p_year != 0 else None

    def _rebalance(self) -> None:
        if self.is_warming_up:
            return

        # Compute 12-month returns
        returns: Dict[str, Optional[float]] = {}
        for ticker in self._ALL:
            returns[ticker] = self._twelve_month_return(ticker)

        if any(r is None for r in returns.values()):
            self.log("Insufficient history for rebalance – skipping.")
            return

        rf_return = returns[self._RF]

        # Rank risky assets by absolute return
        risky_returns = {t: returns[t] for t in self._RISKY}
        best_risky  = max(risky_returns, key=lambda t: risky_returns[t])
        best_return = risky_returns[best_risky]

        # Dual momentum decision
        if best_return > rf_return:
            target = best_risky
            reason = f"abs+rel mom → {best_risky}  ret={best_return*100:.1f}%"
        else:
            target = self._RF
            reason = (f"abs mom negative ({best_return*100:.1f}% < "
                      f"{rf_return*100:.1f}%) → risk-off BIL")

        # Niblit opinion (logged; only flips risk-off if high confidence)
        if self._bridge is not None:
            try:
                act = (self._bridge.get_signal() or "HOLD").upper()
                conf = self._bridge.get_confidence()
                self.log(f"Niblit {best_risky}: {act} conf={conf:.3f}")
                # If Niblit strongly disagrees and model says risk-on → go risk-off
                if target != self._RF and act == "SELL" and conf > 0.8:
                    target = self._RF
                    reason += "  [Niblit override → BIL]"
            except Exception as exc:
                self.log(f"Niblit error: {exc}")

        self.log(f"Dual momentum: {reason}  → holding {target}")

        # Execute trade
        if self._held_ticker and self._held_ticker != target:
            self.liquidate(self._syms[self._held_ticker])
            self.log(f"Liquidated {self._held_ticker}")

        if target != self._held_ticker:
            self.set_holdings(self._syms[target], 0.99)
            self._held_ticker = target
            self.log(f"New holding: {target}")

    def on_order_event(self, order_event: OrderEvent) -> None:
        self.log(str(order_event))

    def on_end_of_algorithm(self) -> None:
        self.log(f"Final value: {self.portfolio.total_portfolio_value:.2f}  "
                 f"holding={self._held_ticker}")
