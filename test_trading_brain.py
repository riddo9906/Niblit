"""test_trading_brain.py — unit tests for modules.trading_brain.TradingBrain.

All tests are offline-safe: no real Binance connection or Qdrant instance
is required.  Network calls are patched and an in-memory NiblitMemory
(FusedMemoryPrimary with ``:memory:`` SQLite) is used where applicable.

Run with::

    pytest test_trading_brain.py -v
"""

import random
import unittest
from unittest.mock import MagicMock, patch

import pytest


# ── helpers ───────────────────────────────────────────────────────────────────

def _random_kline_row():
    """Return a dict mimicking one pandas-row of processed OHLCV + indicators."""
    close = random.uniform(20_000, 70_000)
    return {
        "close": close,
        "volume": random.uniform(100, 5000),
        "rsi": random.uniform(20, 80),
        "macd": random.uniform(-500, 500),
        "ema": close * random.uniform(0.99, 1.01),
        "volatility": random.uniform(50, 800),
        "high": close + random.uniform(0, 400),
        "low": close - random.uniform(0, 400),
    }


def _make_mock_memory(scores=None):
    """Return a MagicMock that mimics the NiblitMemory interface."""
    mem = MagicMock()
    mem.save_record = MagicMock()
    # query_vector returns list of dicts with "score" key
    if scores is not None:
        mem.query_vector = MagicMock(return_value=[{"score": s} for s in scores])
    else:
        mem.query_vector = MagicMock(return_value=[])
    return mem


# ── import guard ──────────────────────────────────────────────────────────────

class TestTradingBrainImport(unittest.TestCase):
    """Verify the module imports cleanly even without optional dependencies."""

    def test_module_importable(self):
        from modules import trading_brain  # noqa: F401
        self.assertTrue(True)

    def test_class_accessible(self):
        from modules.trading_brain import TradingBrain
        self.assertTrue(callable(TradingBrain))


# ── instantiation ─────────────────────────────────────────────────────────────

class TestTradingBrainInit(unittest.TestCase):

    @patch("modules.trading_brain._BINANCE_AVAILABLE", False)
    def test_init_no_binance(self):
        """TradingBrain should initialise without crashing when python-binance
        is absent."""
        from modules.trading_brain import TradingBrain
        brain = TradingBrain(memory=_make_mock_memory())
        self.assertIsNone(brain._client)
        self.assertIsNotNone(brain.memory)

    @patch("modules.trading_brain._BINANCE_AVAILABLE", True)
    @patch("modules.trading_brain._BinanceClient")
    def test_init_with_binance(self, mock_client_cls):
        """When python-binance is available the Binance client is created."""
        from modules.trading_brain import TradingBrain
        brain = TradingBrain(api_key="k", api_secret="s", memory=_make_mock_memory())
        mock_client_cls.assert_called_once_with("k", "s")
        self.assertIsNotNone(brain._client)

    def test_symbol_and_interval_defaults(self):
        from modules.trading_brain import TradingBrain, _DEFAULT_SYMBOL, _DEFAULT_INTERVAL
        brain = TradingBrain(memory=_make_mock_memory())
        self.assertEqual(brain.symbol, _DEFAULT_SYMBOL)
        self.assertEqual(brain.interval, _DEFAULT_INTERVAL)

    def test_custom_symbol(self):
        from modules.trading_brain import TradingBrain
        brain = TradingBrain(symbol="ETHUSDT", memory=_make_mock_memory())
        self.assertEqual(brain.symbol, "ETHUSDT")


# ── build_state_vector ────────────────────────────────────────────────────────

class TestBuildStateVector(unittest.TestCase):

    @pytest.mark.skipif(
        not __import__("importlib").util.find_spec("numpy"),
        reason="numpy not installed",
    )
    def test_returns_list_of_floats(self):
        from modules.trading_brain import TradingBrain
        brain = TradingBrain(memory=_make_mock_memory())
        row = _random_kline_row()
        vector = brain.build_state_vector(row)
        self.assertIsInstance(vector, list)
        self.assertEqual(len(vector), 6)
        for v in vector:
            self.assertIsInstance(v, float)

    @pytest.mark.skipif(
        not __import__("importlib").util.find_spec("numpy"),
        reason="numpy not installed",
    )
    def test_vector_is_normalised(self):
        """After z-score normalisation the absolute values should be moderate."""
        import numpy as np
        from modules.trading_brain import TradingBrain
        brain = TradingBrain(memory=_make_mock_memory())
        row = _random_kline_row()
        vector = brain.build_state_vector(row)
        arr = np.array(vector)
        # normalised values should have mean ~0 and std ~1
        self.assertAlmostEqual(float(np.mean(arr)), 0.0, places=6)

    @patch("modules.trading_brain._NP_AVAILABLE", False)
    def test_raises_without_numpy(self):
        from modules.trading_brain import TradingBrain
        brain = TradingBrain(memory=_make_mock_memory())
        with self.assertRaises(RuntimeError):
            brain.build_state_vector(_random_kline_row())


# ── store_market_state ────────────────────────────────────────────────────────

class TestStoreMarketState(unittest.TestCase):

    def test_calls_memory_save_record(self):
        from modules.trading_brain import TradingBrain
        mem = _make_mock_memory()
        brain = TradingBrain(memory=mem)
        vector = [0.1, 0.2, 0.3, 0.4, 0.5, 0.6]
        meta = {"timestamp": "2024-01-01T00:00:00+00:00", "price": 50000.0}
        brain.store_market_state(vector, meta)
        mem.save_record.assert_called_once()
        call_args = mem.save_record.call_args
        self.assertIn("market_2024-01-01T00:00:00", call_args[0][0])

    def test_no_crash_when_memory_is_none(self):
        from modules.trading_brain import TradingBrain
        brain = TradingBrain(memory=None)
        brain._client = None
        # Should not raise
        brain.store_market_state([0.1], {"timestamp": "t"})


# ── retrieve_similar_states ───────────────────────────────────────────────────

class TestRetrieveSimilarStates(unittest.TestCase):

    def test_delegates_to_memory_query_vector(self):
        from modules.trading_brain import TradingBrain
        mem = _make_mock_memory(scores=[0.9, 0.8, 0.7])
        brain = TradingBrain(memory=mem)
        results = brain.retrieve_similar_states([0.1] * 6, top_k=3)
        mem.query_vector.assert_called_once_with([0.1] * 6, top_k=3)
        self.assertEqual(len(results), 3)

    @patch("modules.trading_brain._MEMORY_AVAILABLE", False)
    def test_returns_empty_when_memory_none(self):
        from modules.trading_brain import TradingBrain
        brain = TradingBrain(memory=None)
        brain._client = None
        self.assertEqual(brain.retrieve_similar_states([0.1] * 6), [])


# ── decide_action ─────────────────────────────────────────────────────────────

class TestDecideAction(unittest.TestCase):

    def test_hold_when_no_history(self):
        from modules.trading_brain import TradingBrain
        brain = TradingBrain(memory=_make_mock_memory(scores=[]))
        self.assertEqual(brain.decide_action([0.0] * 6), "HOLD")

    def test_hold_when_insufficient_history(self):
        from modules.trading_brain import TradingBrain
        # Fewer than 5 similar states → HOLD
        brain = TradingBrain(memory=_make_mock_memory(scores=[0.9, 0.9]))
        self.assertEqual(brain.decide_action([0.0] * 6), "HOLD")

    def test_buy_on_high_similarity(self):
        from modules.trading_brain import TradingBrain, _BUY_THRESHOLD
        high_scores = [_BUY_THRESHOLD + 0.05] * 10
        brain = TradingBrain(memory=_make_mock_memory(scores=high_scores))
        self.assertEqual(brain.decide_action([0.0] * 6), "BUY")

    def test_sell_on_low_similarity(self):
        from modules.trading_brain import TradingBrain, _SELL_THRESHOLD
        low_scores = [_SELL_THRESHOLD - 0.05] * 10
        brain = TradingBrain(memory=_make_mock_memory(scores=low_scores))
        self.assertEqual(brain.decide_action([0.0] * 6), "SELL")

    def test_hold_on_mid_similarity(self):
        from modules.trading_brain import TradingBrain, _BUY_THRESHOLD, _SELL_THRESHOLD
        mid_score = (_BUY_THRESHOLD + _SELL_THRESHOLD) / 2
        brain = TradingBrain(memory=_make_mock_memory(scores=[mid_score] * 10))
        self.assertEqual(brain.decide_action([0.0] * 6), "HOLD")


# ── cycle() ───────────────────────────────────────────────────────────────────

class TestCycle(unittest.TestCase):

    def _brain_with_mocked_steps(self, decision="HOLD"):
        """Return a TradingBrain whose internal steps are fully mocked."""
        from modules.trading_brain import TradingBrain
        brain = TradingBrain(memory=_make_mock_memory())
        brain._client = None  # no real Binance

        # Patch each step to return safe stub data
        row = _random_kline_row()

        import pandas as pd
        df_raw = pd.DataFrame([row])
        df_with_indicators = pd.DataFrame([{**row, "rsi": 50.0, "macd": 10.0,
                                             "ema": row["close"], "volatility": 200.0}])

        brain.fetch_market_data = MagicMock(return_value=df_raw)
        brain.compute_indicators = MagicMock(return_value=df_with_indicators)
        brain.build_state_vector = MagicMock(return_value=[0.1] * 6)
        brain.store_market_state = MagicMock()
        brain.decide_action = MagicMock(return_value=decision)
        return brain

    @pytest.mark.skipif(
        not __import__("importlib").util.find_spec("pandas"),
        reason="pandas not installed",
    )
    def test_cycle_returns_decision(self):
        brain = self._brain_with_mocked_steps("BUY")
        self.assertEqual(brain.cycle(), "BUY")

    @pytest.mark.skipif(
        not __import__("importlib").util.find_spec("pandas"),
        reason="pandas not installed",
    )
    def test_cycle_calls_all_steps(self):
        brain = self._brain_with_mocked_steps()
        brain.cycle()
        brain.fetch_market_data.assert_called_once()
        brain.compute_indicators.assert_called_once()
        brain.build_state_vector.assert_called_once()
        brain.store_market_state.assert_called_once()
        brain.decide_action.assert_called_once()

    @pytest.mark.skipif(
        not __import__("importlib").util.find_spec("pandas"),
        reason="pandas not installed",
    )
    def test_cycle_returns_hold_on_empty_dataframe(self):
        from modules.trading_brain import TradingBrain
        import pandas as pd
        brain = TradingBrain(memory=_make_mock_memory())
        brain.fetch_market_data = MagicMock(return_value=pd.DataFrame())
        self.assertEqual(brain.cycle(), "HOLD")

    def test_cycle_returns_hold_on_unexpected_exception(self):
        from modules.trading_brain import TradingBrain
        brain = TradingBrain(memory=_make_mock_memory())
        brain.fetch_market_data = MagicMock(side_effect=RuntimeError("boom"))
        self.assertEqual(brain.cycle(), "HOLD")


class TestAutonomousCycle(unittest.TestCase):
    """Tests for start/stop/status/running methods."""

    def _brain(self, **kwargs):
        from modules.trading_brain import TradingBrain
        brain = TradingBrain(memory=_make_mock_memory(), **kwargs)
        brain._client = None
        return brain

    def test_initial_state_not_running(self):
        brain = self._brain()
        self.assertFalse(brain.running)
        self.assertEqual(brain._cycle_count, 0)
        self.assertEqual(brain._last_decision, "HOLD")
        self.assertIsNone(brain._last_cycle_ts)

    def test_start_returns_true_first_call(self):
        brain = self._brain()
        brain.cycle = MagicMock(return_value="HOLD")
        result = brain.start()
        self.assertTrue(result)
        self.assertTrue(brain._running)
        brain.stop()

    def test_start_returns_false_when_already_running(self):
        brain = self._brain()
        brain.cycle = MagicMock(return_value="HOLD")
        brain.start()
        result = brain.start()
        self.assertFalse(result)
        brain.stop()

    def test_stop_returns_true_when_running(self):
        brain = self._brain()
        brain.cycle = MagicMock(return_value="HOLD")
        brain.start()
        result = brain.stop()
        self.assertTrue(result)

    def test_stop_returns_false_when_not_running(self):
        brain = self._brain()
        result = brain.stop()
        self.assertFalse(result)

    def test_status_dict_keys(self):
        brain = self._brain()
        st = brain.status()
        for key in ("running", "symbol", "interval", "cycle_secs",
                    "cycle_count", "last_decision", "last_cycle_ts",
                    "binance_available", "memory_available"):
            self.assertIn(key, st)
        self.assertIsInstance(st["running"], bool)
        self.assertIsInstance(st["symbol"], str)
        self.assertIsInstance(st["interval"], str)
        self.assertIsInstance(st["cycle_secs"], int)
        self.assertIsInstance(st["cycle_count"], int)
        self.assertIsInstance(st["last_decision"], str)
        self.assertIsInstance(st["binance_available"], bool)
        self.assertIsInstance(st["memory_available"], bool)

    def test_status_reflects_state(self):
        brain = self._brain(symbol="ETHUSDT", cycle_secs=30)
        st = brain.status()
        self.assertFalse(st["running"])
        self.assertEqual(st["symbol"], "ETHUSDT")
        self.assertEqual(st["cycle_secs"], 30)
        self.assertEqual(st["cycle_count"], 0)


if __name__ == "__main__":
    unittest.main()
