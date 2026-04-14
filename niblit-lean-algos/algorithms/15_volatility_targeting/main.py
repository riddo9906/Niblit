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
from typing import Dict, List


class VolatilityTargeting(QCAlgorithm):
    """
    Volatility-Targeted Portfolio.

    Assets:      SPY (equities), TLT (bonds), GLD (gold), IEF (intermediate bonds).
    Target Vol:  10% annualized portfolio volatility.
    Sizing:      weight_i = (target_vol / realized_vol_i) / num_assets
                 Each asset sized independently; total capped at 100%.
    Vol window:  20 trading days of daily returns.
    Rebalance:   Monthly + on significant vol shift (>20% change).
    """

    _ASSETS         = ["SPY", "TLT", "GLD", "IEF"]
    _TARGET_VOL     = 0.10        # 10% annualized
    _VOL_WINDOW     = 20
    _ANNUALISE      = math.sqrt(252)
    _REBALANCE_TOL  = 0.20        # rebalance if vol changes >20%
    _MAX_ALLOC      = 0.40        # cap per asset
    _MIN_ALLOC      = 0.05        # floor per asset

    def initialize(self) -> None:
        self.set_start_date(2016, 1, 1)
        self.set_end_date(2024, 1, 1)
        self.set_cash(200_000)

        if not self.live_mode:
            self.set_brokerage_model(BrokerageName.PAPER_BROKERAGE)

        self._syms: List[Symbol] = []
        for ticker in self._ASSETS:
            self._syms.append(self.add_equity(ticker, Resolution.DAILY).symbol)

        self._price_hist: Dict[Symbol, deque] = {
            s: deque(maxlen=self._VOL_WINDOW + 1) for s in self._syms
        }
        self._last_vols: Dict[Symbol, float] = {s: 0.0 for s in self._syms}

        self.set_warm_up(self._VOL_WINDOW + 5)

        # Monthly rebalance
        self.schedule.on(
            self.date_rules.month_start(self._ASSETS[0]),
            self.time_rules.after_market_open(self._ASSETS[0], 30),
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
        for sym in self._syms:
            if sym in data.bars:
                self._price_hist[sym].append(data.bars[sym].close)

        if self.is_warming_up:
            return

        # Intra-month vol shift check → early rebalance
        for sym in self._syms:
            new_vol = self._realized_vol(sym)
            old_vol = self._last_vols.get(sym, 0.0)
            if old_vol > 0 and abs(new_vol - old_vol) / old_vol > self._REBALANCE_TOL:
                self.log(f"Vol shift detected for {sym}: "
                         f"{old_vol:.3f} → {new_vol:.3f}  Rebalancing.")
                self._rebalance()
                return

    # ------------------------------------------------------------------ #
    def _realized_vol(self, sym: Symbol) -> float:
        """Annualized realized volatility from rolling daily returns."""
        hist = list(self._price_hist[sym])
        if len(hist) < 5:
            return 0.20   # default 20% if insufficient data
        returns = [(hist[i] / hist[i-1]) - 1.0 for i in range(1, len(hist))]
        mu  = sum(returns) / len(returns)
        var = sum((r - mu) ** 2 for r in returns) / len(returns)
        return math.sqrt(var) * self._ANNUALISE

    def _target_weight(self, sym: Symbol) -> float:
        """
        Compute vol-targeted weight for one asset:
            w = target_vol / (n_assets * realized_vol)
        Clipped to [MIN_ALLOC, MAX_ALLOC].
        """
        vol = self._realized_vol(sym)
        if vol <= 0:
            return self._MIN_ALLOC
        w = self._TARGET_VOL / (len(self._syms) * vol)
        return max(self._MIN_ALLOC, min(self._MAX_ALLOC, w))

    def _rebalance(self) -> None:
        if self.is_warming_up:
            return

        weights: Dict[Symbol, float] = {}
        for sym in self._syms:
            weights[sym] = self._target_weight(sym)
            self._last_vols[sym] = self._realized_vol(sym)

        # Normalise so total allocation ≤ 100%
        total_w = sum(weights.values())
        if total_w > 1.0:
            for sym in weights:
                weights[sym] /= total_w

        # Niblit override log
        if self._bridge is not None:
            try:
                for sym in self._syms:
                    act = (self._bridge.get_signal() or "HOLD").upper()
                    # If Niblit says SELL, halve the weight
                    if act == "SELL":
                        weights[sym] *= 0.5
                self.log("Niblit overrides applied.")
            except Exception as exc:
                self.log(f"Niblit error: {exc}")

        log_parts = [f"{sym}={w:.3f}" for sym, w in weights.items()]
        self.log(f"Rebalance: {', '.join(log_parts)}")

        for sym, w in weights.items():
            self.set_holdings(sym, w)

    def on_order_event(self, order_event: OrderEvent) -> None:
        self.log(str(order_event))

    def on_end_of_algorithm(self) -> None:
        final = self.portfolio.total_portfolio_value
        vols  = {str(s): f"{self._realized_vol(s)*100:.1f}%" for s in self._syms}
        self.log(f"Final value: {final:.2f}  vols={vols}")
