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
from typing import Dict, List, Optional


class MultiFactor(QCAlgorithm):
    """
    Multi-Factor ETF Rotation Strategy.

    Universe:   20 large-cap ETFs spanning equities, bonds, commodities.
    Factors:
      - 12-1 month momentum  (price return 12 months back, exclude last month)
      - 1-month reversal     (negative recent return)
      - Inverse volatility   (20-day std of daily returns, lower is better)
    Scoring:    Equal-weight factor ranks → composite score.
    Portfolio:  Top 5 ETFs, equal-weight, rebalanced monthly.
    Risk:       Max 25% per holding; stop if any holding falls >8% from entry.
    """

    _UNIVERSE = [
        "SPY", "QQQ", "IWM", "EFA", "EEM",
        "TLT", "IEF", "AGG", "LQD", "GLD",
        "SLV", "USO", "VNQ", "XLE", "XLF",
        "XLV", "XLK", "XLU", "XLB", "XLP",
    ]
    _TOP_N        = 5
    _MOM_LONG     = 252    # ~12 months
    _MOM_SKIP     = 21     # skip last month
    _VOL_WINDOW   = 20
    _MAX_HOLD_PCT = 0.24   # per position cap
    _STOP_PCT     = 0.08   # 8% stop below entry

    def initialize(self) -> None:
        self.set_start_date(2016, 1, 1)
        self.set_end_date(2024, 1, 1)
        self.set_cash(200_000)

        if not self.live_mode:
            self.set_brokerage_model(BrokerageName.PAPER_BROKERAGE)

        self._syms: List[Symbol] = []
        for ticker in self._UNIVERSE:
            self._syms.append(self.add_equity(ticker, Resolution.DAILY).symbol)

        self._price_history: Dict[Symbol, deque] = {
            s: deque(maxlen=self._MOM_LONG + 5) for s in self._syms
        }
        self._entry_prices: Dict[Symbol, float] = {}

        # Monthly rebalance schedule
        self.schedule.on(
            self.date_rules.month_start(self._UNIVERSE[0]),
            self.time_rules.after_market_open(self._UNIVERSE[0], 30),
            self._rebalance,
        )

        self.set_warm_up(self._MOM_LONG + 5)

        self._bridge = None
        if _NIBLIT_AVAILABLE and _NiblitBridge is not None:
            try:
                self._bridge = _NiblitBridge()
                self.log("NiblitBridge connected.")
            except Exception as exc:
                self.log(f"NiblitBridge init failed: {exc}")

    def on_data(self, data: Slice) -> None:
        # Accumulate price history
        for sym in self._syms:
            if sym in data.bars:
                self._price_history[sym].append(data.bars[sym].close)

        if self.is_warming_up:
            return

        # Per-position stop loss check
        for sym, entry in list(self._entry_prices.items()):
            if sym in data.bars:
                price = data.bars[sym].close
                if price < entry * (1.0 - self._STOP_PCT):
                    self.liquidate(sym)
                    del self._entry_prices[sym]
                    self.log(f"Stop loss hit: {sym}  @ {price:.2f}  "
                             f"entry={entry:.2f}")

    def _score_universe(self) -> List[tuple]:
        """Return list of (symbol, composite_score) sorted descending."""
        scores = {}
        for sym in self._syms:
            hist = list(self._price_history[sym])
            if len(hist) < self._MOM_LONG:
                continue
            # 12-1 momentum
            p_now   = hist[-1]
            p_skip  = hist[-self._MOM_SKIP]      # price 1 month ago
            p_long  = hist[-self._MOM_LONG]      # price 12 months ago
            mom     = (p_skip / p_long) - 1.0 if p_long != 0 else 0.0
            # 1-month reversal (negative factor)
            rev     = -((p_now / p_skip) - 1.0) if p_skip != 0 else 0.0
            # Inverse volatility
            recent  = hist[-self._VOL_WINDOW:]
            returns = [(recent[i] / recent[i-1]) - 1.0 for i in range(1, len(recent))]
            vol_inv = 0.0
            if returns:
                mu  = sum(returns) / len(returns)
                var = sum((r - mu) ** 2 for r in returns) / len(returns)
                vol_inv = 1.0 / (math.sqrt(var) * math.sqrt(252) + 1e-8)
            scores[sym] = (mom, rev, vol_inv)

        if not scores:
            return []

        # Cross-sectional rank (0=worst, 1=best)
        def rank_factor(key: int) -> Dict[Symbol, float]:
            vals   = [(s, scores[s][key]) for s in scores]
            vals.sort(key=lambda x: x[1])
            n = len(vals)
            return {vals[i][0]: i / (n - 1) if n > 1 else 0.5 for i in range(n)}

        r_mom = rank_factor(0)
        r_rev = rank_factor(1)
        r_vol = rank_factor(2)

        composite = {}
        for sym in scores:
            composite[sym] = (r_mom.get(sym, 0) +
                               r_rev.get(sym, 0) +
                               r_vol.get(sym, 0)) / 3.0

        ranked = sorted(composite.items(), key=lambda x: x[1], reverse=True)
        return ranked

    def _rebalance(self) -> None:
        if self.is_warming_up:
            return

        ranked = self._score_universe()
        if not ranked:
            return

        top_syms = [s for s, _ in ranked[:self._TOP_N]]
        target_wt = 1.0 / len(top_syms) if top_syms else 0.0

        # Niblit adjustment
        if self._bridge is not None:
            try:
                for sym in top_syms:
                    _sig_str = (self._bridge.get_signal() or "HOLD").upper()
                    self.log(f"Niblit {sym}: {_sig_str}")
            except Exception as exc:
                self.log(f"Niblit error: {exc}")

        self.log(f"Rebalance: top={[str(s) for s in top_syms]}")

        # Liquidate positions not in top list
        for sym in list(self._entry_prices.keys()):
            if sym not in top_syms:
                self.liquidate(sym)
                del self._entry_prices[sym]

        # Set target weights
        for sym in top_syms:
            wt = min(target_wt, self._MAX_HOLD_PCT)
            self.set_holdings(sym, wt)
            if sym in self.portfolio and self.portfolio[sym].invested:
                price = self.securities[sym].price
                self._entry_prices[sym] = price

    def on_order_event(self, order_event: OrderEvent) -> None:
        self.log(str(order_event))

    def on_end_of_algorithm(self) -> None:
        self.log(f"Final value: {self.portfolio.total_portfolio_value:.2f}")
