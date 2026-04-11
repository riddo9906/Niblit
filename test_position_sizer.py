"""test_position_sizer.py — unit tests for modules.position_sizer.PositionSizer.

All tests are offline-safe and require no external dependencies beyond the
standard library.

Run with::

    pytest test_position_sizer.py -v
"""

import unittest


class TestPositionSizerImport(unittest.TestCase):
    def test_module_importable(self):
        from modules import position_sizer  # noqa: F401
        self.assertTrue(True)

    def test_class_accessible(self):
        from modules.position_sizer import PositionSizer
        self.assertTrue(callable(PositionSizer))

    def test_get_singleton(self):
        # Reset module-level singleton so this test is isolated
        import modules.position_sizer as ps
        ps._sizer = None
        sizer = ps.get_position_sizer()
        self.assertIsNotNone(sizer)
        # Second call returns the same object
        sizer2 = ps.get_position_sizer()
        self.assertIs(sizer, sizer2)
        ps._sizer = None  # clean up


class TestKellyCriterion(unittest.TestCase):
    """Tests for the raw Kelly fraction calculation."""

    def _make_sizer(self, **kw):
        from modules.position_sizer import PositionSizer
        return PositionSizer(**kw)

    def test_zero_win_rate_returns_zero(self):
        sizer = self._make_sizer()
        self.assertEqual(sizer.compute_kelly(0.0, 0.02, 0.01), 0.0)

    def test_full_win_rate_returns_zero(self):
        # win_rate=1.0 is not valid (must be strictly between 0 and 1)
        sizer = self._make_sizer()
        self.assertEqual(sizer.compute_kelly(1.0, 0.02, 0.01), 0.0)

    def test_zero_avg_loss_returns_zero(self):
        sizer = self._make_sizer()
        self.assertEqual(sizer.compute_kelly(0.55, 0.02, 0.0), 0.0)

    def test_zero_avg_win_returns_zero(self):
        sizer = self._make_sizer()
        self.assertEqual(sizer.compute_kelly(0.55, 0.0, 0.01), 0.0)

    def test_positive_edge_case(self):
        # 55% win rate, 2:1 payoff → Kelly = (0.55*2 - 0.45) / 2 = 0.325
        sizer = self._make_sizer()
        k = sizer.compute_kelly(0.55, 0.02, 0.01)
        self.assertAlmostEqual(k, 0.325, places=3)

    def test_negative_edge_clamped_to_zero(self):
        # Losing strategy: 10% win rate with equal payoff → should be 0.0
        sizer = self._make_sizer()
        k = sizer.compute_kelly(0.1, 0.01, 0.01)
        self.assertEqual(k, 0.0)

    def test_result_clamped_to_1(self):
        # Extreme edge: very high win rate and payoff should not exceed 1
        sizer = self._make_sizer()
        k = sizer.compute_kelly(0.99, 0.5, 0.001)
        self.assertLessEqual(k, 1.0)


class TestPositionFraction(unittest.TestCase):
    """Tests for position_fraction() including fractional-Kelly and max cap."""

    def _make_sizer(self, kelly_fraction=1.0, max_fraction=0.25):
        from modules.position_sizer import PositionSizer
        return PositionSizer(kelly_fraction=kelly_fraction, max_fraction=max_fraction)

    def test_full_kelly(self):
        sizer = self._make_sizer(kelly_fraction=1.0, max_fraction=1.0)
        f = sizer.position_fraction(0.55, 0.02, 0.01)
        self.assertAlmostEqual(f, 0.325, places=3)

    def test_half_kelly(self):
        sizer = self._make_sizer(kelly_fraction=0.5, max_fraction=1.0)
        f = sizer.position_fraction(0.55, 0.02, 0.01)
        self.assertAlmostEqual(f, 0.1625, places=3)

    def test_max_fraction_caps_result(self):
        sizer = self._make_sizer(kelly_fraction=1.0, max_fraction=0.10)
        f = sizer.position_fraction(0.55, 0.02, 0.01)
        self.assertLessEqual(f, 0.10)

    def test_returns_zero_for_bad_inputs(self):
        sizer = self._make_sizer()
        self.assertEqual(sizer.position_fraction(0.0, 0.02, 0.01), 0.0)
        self.assertEqual(sizer.position_fraction(0.55, 0.0, 0.01), 0.0)

    def test_circuit_breaker_blocks_fraction(self):
        from modules.position_sizer import PositionSizer
        sizer = PositionSizer(max_drawdown_pct=0.10, initial_equity=1000.0)
        sizer.update_equity(800.0)   # 20% drawdown → trips 10% threshold
        self.assertTrue(sizer.circuit_breaker_open)
        self.assertEqual(sizer.position_fraction(0.55, 0.02, 0.01), 0.0)


class TestCircuitBreaker(unittest.TestCase):
    """Tests for the max-drawdown circuit breaker."""

    def _make_sizer(self, max_drawdown_pct=0.20, initial_equity=10_000.0):
        from modules.position_sizer import PositionSizer
        return PositionSizer(
            max_drawdown_pct=max_drawdown_pct,
            initial_equity=initial_equity,
        )

    def test_no_trip_within_threshold(self):
        sizer = self._make_sizer(max_drawdown_pct=0.20, initial_equity=1000.0)
        tripped = sizer.update_equity(850.0)  # 15% drawdown < 20%
        self.assertFalse(tripped)
        self.assertFalse(sizer.circuit_breaker_open)

    def test_trip_at_exact_threshold(self):
        sizer = self._make_sizer(max_drawdown_pct=0.20, initial_equity=1000.0)
        tripped = sizer.update_equity(800.0)  # exactly 20%
        self.assertTrue(tripped)
        self.assertTrue(sizer.circuit_breaker_open)

    def test_trip_above_threshold(self):
        sizer = self._make_sizer(max_drawdown_pct=0.15, initial_equity=1000.0)
        tripped = sizer.update_equity(700.0)  # 30% > 15%
        self.assertTrue(tripped)
        self.assertTrue(sizer.circuit_breaker_open)

    def test_peak_equity_updated_on_new_high(self):
        sizer = self._make_sizer(max_drawdown_pct=0.20, initial_equity=1000.0)
        sizer.update_equity(1200.0)
        self.assertEqual(sizer._peak_equity, 1200.0)

    def test_reset_clears_circuit_breaker(self):
        sizer = self._make_sizer(max_drawdown_pct=0.10, initial_equity=1000.0)
        sizer.update_equity(800.0)   # trip it
        self.assertTrue(sizer.circuit_breaker_open)
        sizer.reset_circuit_breaker()
        self.assertFalse(sizer.circuit_breaker_open)

    def test_current_drawdown_property(self):
        sizer = self._make_sizer(max_drawdown_pct=0.20, initial_equity=1000.0)
        sizer.update_equity(900.0)
        self.assertAlmostEqual(sizer.current_drawdown, 0.10, places=4)

    def test_zero_initial_equity_no_crash(self):
        sizer = self._make_sizer(max_drawdown_pct=0.20, initial_equity=0.0)
        # Should not raise even with no peak
        tripped = sizer.update_equity(0.0)
        self.assertFalse(tripped)

    def test_status_dict_keys(self):
        sizer = self._make_sizer()
        s = sizer.status()
        for key in ("kelly_fraction", "max_fraction", "max_drawdown_pct",
                    "peak_equity", "current_equity", "circuit_breaker_open",
                    "current_drawdown_pct"):
            self.assertIn(key, s)


class TestTradingBrainPositionSizerIntegration(unittest.TestCase):
    """Light integration tests: TradingBrain should accept a position_sizer param."""

    def test_trading_brain_accepts_position_sizer(self):
        from modules.trading_brain import TradingBrain
        from modules.position_sizer import PositionSizer
        from unittest.mock import MagicMock

        mem = MagicMock()
        mem.save_record = MagicMock()
        mem.query_vector = MagicMock(return_value=[])

        ps = PositionSizer(max_drawdown_pct=0.20, initial_equity=10_000.0)
        brain = TradingBrain(memory=mem, position_sizer=ps)
        self.assertIs(brain.position_sizer, ps)

    def test_trading_brain_position_sizer_none_disables(self):
        from modules.trading_brain import TradingBrain
        from unittest.mock import MagicMock

        mem = MagicMock()
        mem.save_record = MagicMock()
        mem.query_vector = MagicMock(return_value=[])

        brain = TradingBrain(memory=mem, position_sizer=False)
        self.assertIsNone(brain.position_sizer)

    def test_status_includes_position_sizer(self):
        from modules.trading_brain import TradingBrain
        from modules.position_sizer import PositionSizer
        from unittest.mock import MagicMock

        mem = MagicMock()
        mem.save_record = MagicMock()
        mem.query_vector = MagicMock(return_value=[])

        ps = PositionSizer(max_drawdown_pct=0.20, initial_equity=10_000.0)
        brain = TradingBrain(memory=mem, position_sizer=ps)
        status = brain.status()
        self.assertIn("position_sizer", status)
        self.assertIn("circuit_breaker_open", status["position_sizer"])


if __name__ == "__main__":
    unittest.main()
