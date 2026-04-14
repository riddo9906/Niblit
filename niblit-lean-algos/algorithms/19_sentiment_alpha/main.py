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
from typing import List, Dict


# ──────────────────────────────────────────────────────────────────────────────
#  Sentiment word lists (minimal; easily expandable)
# ──────────────────────────────────────────────────────────────────────────────

_POSITIVE_WORDS = {
    "beat", "beats", "surge", "surges", "surging", "growth", "profit",
    "profits", "record", "rally", "rallies", "strong", "upgrade",
    "upgraded", "buy", "bullish", "positive", "outperform", "rise",
    "rising", "gain", "gains", "higher", "increase", "increased",
    "accelerate", "expand", "expansion", "revenue", "exceed", "exceeded",
    "upside", "momentum", "recovery", "improve", "improved", "opportunity",
}

_NEGATIVE_WORDS = {
    "miss", "misses", "decline", "declines", "declining", "loss", "losses",
    "layoff", "layoffs", "downgrade", "downgraded", "sell", "bearish",
    "negative", "underperform", "fall", "falling", "drop", "drops",
    "lower", "decrease", "decreased", "decelerate", "contract",
    "contraction", "debt", "disappoint", "disappointed", "downside",
    "warning", "risk", "risks", "lawsuit", "investigation", "default",
    "recession", "weak", "weaker", "cut", "cuts", "inflation",
}


def _score_text(text: str) -> float:
    """
    Score a text string using positive/negative word lists.
    Returns a float in approximately [-1, +1].
    """
    words = text.lower().split()
    pos = sum(1 for w in words if w in _POSITIVE_WORDS)
    neg = sum(1 for w in words if w in _NEGATIVE_WORDS)
    total = pos + neg
    if total == 0:
        return 0.0
    return (pos - neg) / total


# ──────────────────────────────────────────────────────────────────────────────
#  Algorithm
# ──────────────────────────────────────────────────────────────────────────────
class SentimentAlpha(QCAlgorithm):
    """
    Sentiment-Driven Alpha Strategy.

    Parses QuantConnect Tiingo News data (free tier).
    Computes rolling 5-day sentiment score per asset.
    Combines with RSI(14) for confirmation.

    Entry:   Sentiment score > +threshold AND RSI < 65 (not overbought) → LONG.
             Sentiment score < -threshold AND RSI > 35 (not oversold)  → flat.
    Exit:    Sentiment fades below exit_threshold OR RSI extreme.
    """

    _SYMBOL          = "SPY"
    _SENTIMENT_WINDOW = 5        # days of news to average
    _ENTRY_THRESH    = 0.20      # sentiment score entry threshold
    _EXIT_THRESH     = 0.05      # exit when sentiment fades
    _RISK_PCT        = 0.02
    _ATR_MULT        = 1.5

    def initialize(self) -> None:
        self.set_start_date(2020, 1, 1)
        self.set_end_date(2024, 1, 1)
        self.set_cash(100_000)

        if not self.live_mode:
            self.set_brokerage_model(BrokerageName.PAPER_BROKERAGE)

        self._sym = self.add_equity(self._SYMBOL, Resolution.DAILY).symbol

        # Add Tiingo News data
        try:
            self._news_sym = self.add_data(TiingoNews, self._SYMBOL,
                                           Resolution.DAILY).symbol
            self._has_news = True
        except Exception:
            # Fallback: no live news feed available (backtest without news)
            self._has_news = False
            self.log("Tiingo News not available – using RSI only.")

        self._rsi = self.rsi(self._sym, 14, Resolution.DAILY)
        self._atr = self.atr(self._sym, 14, Resolution.DAILY)

        self.set_warm_up(30)

        # Rolling daily sentiment scores
        self._daily_scores: deque = deque(maxlen=self._SENTIMENT_WINDOW)
        self._today_scores:  List[float] = []    # accumulate intraday news scores

        self._stop_price: float = 0.0
        self._position:   int   = 0

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

        # Consume news articles
        if self._has_news and self._news_sym in data:
            articles = data[self._news_sym]
            if isinstance(articles, list):
                news_list = articles
            else:
                news_list = [articles]
            for article in news_list:
                try:
                    text  = (article.title or "") + " " + (article.description or "")
                    score = _score_text(text)
                    self._today_scores.append(score)
                    self.log(f"News: '{article.title[:60]}...'  score={score:.3f}")
                except Exception:
                    pass

        # Process equity bar
        if self._sym not in data.bars:
            return
        if not (self._rsi.is_ready and self._atr.is_ready):
            return

        price = data.bars[self._sym].close
        rsi   = self._rsi.current.value
        atr   = self._atr.current.value

        # Flush today's news scores to daily buffer
        if self._today_scores:
            day_score = sum(self._today_scores) / len(self._today_scores)
        else:
            day_score = 0.0   # neutral if no news today
        self._daily_scores.append(day_score)
        self._today_scores.clear()

        # Rolling 5-day sentiment
        rolling_sentiment = (sum(self._daily_scores) / len(self._daily_scores)
                             if self._daily_scores else 0.0)

        self.log(f"Sentiment={rolling_sentiment:.3f}  RSI={rsi:.1f}")

        # Niblit overlay
        niblit_sentiment_boost = 0.0
        if self._bridge is not None:
            try:
                act = (self._bridge.get_signal() or "HOLD").upper()
                conf = self._bridge.get_confidence()
                if act == "BUY":
                    niblit_sentiment_boost = 0.10 * conf
                elif act == "SELL":
                    niblit_sentiment_boost = -0.10 * conf
                self.log(f"Niblit: {act} conf={conf:.3f}")
            except Exception as exc:
                self.log(f"Niblit error: {exc}")

        combined_sentiment = rolling_sentiment + niblit_sentiment_boost

        # Stop loss
        if self._position != 0 and self._stop_price > 0:
            if self._position == 1 and price <= self._stop_price:
                self.liquidate(self._sym)
                self._position   = 0
                self._stop_price = 0.0
                self.log(f"Stop triggered @ {price:.2f}")
                return

        # Exit: sentiment faded
        if self._position == 1 and combined_sentiment < self._EXIT_THRESH:
            self.liquidate(self._sym)
            self._position   = 0
            self._stop_price = 0.0
            self.log(f"Sentiment exit: score={combined_sentiment:.3f}")
            return

        # RSI-based exit
        if self._position == 1 and rsi > 75:
            self.liquidate(self._sym)
            self._position   = 0
            self._stop_price = 0.0
            self.log(f"RSI overbought exit: RSI={rsi:.1f}")
            return

        # Entry: positive sentiment + RSI not overbought
        if (combined_sentiment >= self._ENTRY_THRESH
                and rsi < 65 and rsi > 25
                and self._position == 0):
            equity    = self.portfolio.total_portfolio_value
            stop_dist = self._ATR_MULT * atr
            if stop_dist > 0:
                shares = int(min((equity * self._RISK_PCT) / stop_dist,
                                  (equity * 0.30) / price))
                if shares > 0:
                    self.market_order(self._sym, shares)
                    self._stop_price = price - stop_dist
                    self._position   = 1
                    self.log(f"Sentiment BUY {shares} @ {price:.2f}  "
                             f"sentiment={combined_sentiment:.3f}  RSI={rsi:.1f}")

    def on_order_event(self, order_event: OrderEvent) -> None:
        self.log(str(order_event))

    def on_end_of_algorithm(self) -> None:
        self.log(f"Final value: {self.portfolio.total_portfolio_value:.2f}")
