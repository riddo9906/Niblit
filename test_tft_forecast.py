"""
test_tft_forecast.py — Unit tests for modules/tft_forecast.py

Covers:
  - TFTForecastAdapter: push_price, predict_signal, status
  - EWMA fallback signal logic
  - Singleton via get_tft_adapter()
  - Thread-safety basics

Run with::

    pytest test_tft_forecast.py -v
"""

import pytest


# ---------------------------------------------------------------------------
# Import guard
# ---------------------------------------------------------------------------

try:
    from modules.tft_forecast import (
        TFTForecastAdapter,
        get_tft_adapter,
        _ewma_signal,
        _MIN_HISTORY,
    )
    _AVAILABLE = True
except ImportError:
    _AVAILABLE = False

pytestmark = pytest.mark.skipif(not _AVAILABLE, reason="tft_forecast module not available")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _fresh_adapter(**kwargs) -> "TFTForecastAdapter":
    """Return a new TFTForecastAdapter (not the singleton)."""
    return TFTForecastAdapter(**kwargs)


def _rising_prices(n: int = 20, start: float = 100.0, step: float = 1.0):
    """Generate a list of steadily rising prices."""
    return [start + i * step for i in range(n)]


def _falling_prices(n: int = 20, start: float = 120.0, step: float = 1.0):
    """Generate a list of steadily falling prices."""
    return [start - i * step for i in range(n)]


def _flat_prices(n: int = 20, price: float = 100.0):
    """Generate a list of constant prices."""
    return [price] * n


# ---------------------------------------------------------------------------
# TFTForecastAdapter — basic behaviour
# ---------------------------------------------------------------------------

class TestTFTForecastAdapterBasic:
    def test_initial_signal_is_hold(self):
        """With an empty buffer predict_signal must return HOLD."""
        adapter = _fresh_adapter()
        assert adapter.predict_signal() == "HOLD"

    def test_insufficient_history_returns_hold(self):
        """If fewer than _MIN_HISTORY observations exist return HOLD."""
        adapter = _fresh_adapter()
        for p in _rising_prices(n=_MIN_HISTORY - 1):
            adapter.push_price(p)
        assert adapter.predict_signal() == "HOLD"

    def test_sufficient_history_returns_valid_signal(self):
        """Once enough prices are pushed the signal should be BUY/SELL/HOLD."""
        adapter = _fresh_adapter()
        for p in _rising_prices(n=_MIN_HISTORY + 5):
            adapter.push_price(p)
        signal = adapter.predict_signal()
        assert signal in ("BUY", "SELL", "HOLD")

    def test_signal_is_string(self):
        adapter = _fresh_adapter()
        for p in _rising_prices(n=20):
            adapter.push_price(p)
        assert isinstance(adapter.predict_signal(), str)

    def test_push_price_updates_buffer(self):
        adapter = _fresh_adapter(history_len=10)
        for p in range(15):
            adapter.push_price(float(p))
        # maxlen=10: only the last 10 prices are kept
        assert adapter.status()["history_len"] == 10

    def test_status_keys_present(self):
        adapter = _fresh_adapter()
        s = adapter.status()
        expected = {"enabled", "backend", "history_len", "history_capacity",
                    "forecast_horizon", "last_signal", "signal_count"}
        assert expected.issubset(set(s.keys()))

    def test_signal_count_increments(self):
        adapter = _fresh_adapter()
        for p in _rising_prices(n=20):
            adapter.push_price(p)
        adapter.predict_signal()
        adapter.predict_signal()
        assert adapter.status()["signal_count"] == 2

    def test_history_capacity_matches_init(self):
        adapter = _fresh_adapter(history_len=32)
        assert adapter.status()["history_capacity"] == 32


# ---------------------------------------------------------------------------
# EWMA fallback signal logic
# ---------------------------------------------------------------------------

class TestEwmaSignal:
    def test_returns_hold_on_short_history(self):
        assert _ewma_signal([100.0, 101.0, 102.0], horizon=3) == "HOLD"

    def test_rising_trend_gives_buy(self):
        """A clear upward trend should typically yield BUY."""
        prices = _rising_prices(n=30, step=2.0)
        signal = _ewma_signal(prices, horizon=3)
        assert signal == "BUY"

    def test_falling_trend_gives_sell(self):
        """A clear downward trend should typically yield SELL."""
        prices = _falling_prices(n=30, step=2.0)
        signal = _ewma_signal(prices, horizon=3)
        assert signal == "SELL"

    def test_flat_prices_give_hold(self):
        """Flat prices have zero MACD → HOLD."""
        prices = _flat_prices(n=20)
        signal = _ewma_signal(prices, horizon=3)
        assert signal == "HOLD"

    def test_returns_valid_string(self):
        prices = _rising_prices(n=16)
        signal = _ewma_signal(prices, horizon=3)
        assert signal in ("BUY", "SELL", "HOLD")

    def test_zero_price_returns_hold(self):
        """If the last price is 0 the function should return HOLD safely."""
        prices = [0.0] * 10
        signal = _ewma_signal(prices, horizon=3)
        assert signal == "HOLD"


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

class TestGetTftAdapter:
    def test_singleton_returns_same_instance(self):
        a1 = get_tft_adapter()
        a2 = get_tft_adapter()
        assert a1 is a2

    def test_singleton_is_tft_adapter(self):
        assert isinstance(get_tft_adapter(), TFTForecastAdapter)


# ---------------------------------------------------------------------------
# Thread safety (basic smoke test)
# ---------------------------------------------------------------------------

class TestTFTThreadSafety:
    def test_concurrent_push_does_not_raise(self):
        import threading
        adapter = _fresh_adapter()
        errors = []

        def _push():
            try:
                for p in _rising_prices(n=20):
                    adapter.push_price(p)
            except Exception as exc:
                errors.append(exc)

        threads = [threading.Thread(target=_push) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert errors == [], f"Thread errors: {errors}"


if __name__ == "__main__":
    print('Running test_tft_forecast.py')
