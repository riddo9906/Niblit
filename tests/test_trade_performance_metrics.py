import pytest
from modules.trade_performance_metrics import observed_excursion, summarise_closed


def test_short_excursion_tracks_favorable_and_adverse_quotes():
    p = observed_excursion(side="sell", entry=100, initial_stop=110, mark=95)
    assert p["current_r"] == pytest.approx(.5)
    assert p["mfe_r"] == pytest.approx(.5)
    assert p["mae_r"] == 0
    p = observed_excursion(side="sell", entry=100, initial_stop=110, mark=102, prior=p)
    assert p["current_r"] == pytest.approx(-.2)
    assert p["mfe_r"] == pytest.approx(.5)
    assert p["mae_r"] == pytest.approx(-.2)
    assert p["retracement_from_peak_r"] == pytest.approx(.7)
    assert p["realized_profit"] is None


def test_long_excursion_and_realized_net_r():
    p = observed_excursion(side="buy", entry=100, initial_stop=95, mark=103)
    assert p["current_r"] == pytest.approx(.6)
    q = observed_excursion(side="buy", entry=100, initial_stop=95, mark=98, prior=p)
    result = summarise_closed(entry_risk_cash=25, realized_net=12.5, prior=q)
    assert result["net_realized_r"] == .5
    assert result["observed_mfe_r"] == pytest.approx(.6)
    assert result["observed_mae_r"] == pytest.approx(-.4)
    assert q["gross_price_only"] is True


@pytest.mark.parametrize("args", [
    {"side": "sell", "entry": 100, "initial_stop": 99, "mark": 95},
    {"side": "buy", "entry": 100, "initial_stop": 101, "mark": 105},
    {"side": "wait", "entry": 100, "initial_stop": 110, "mark": 99},
    {"side": "sell", "entry": 100, "initial_stop": 110, "mark": float("nan")},
])
def test_nonphysical_exposure_or_quote_is_invalid(args):
    with pytest.raises(ValueError):
        observed_excursion(**args)


def test_replay_is_deterministic_and_non_mutating():
    prior = {"mfe_r": .8, "mae_r": -.3}
    a = observed_excursion(side="sell", entry=100, initial_stop=108, mark=98, prior=prior)
    b = observed_excursion(side="sell", entry=100, initial_stop=108, mark=98, prior=prior)
    assert a == b and prior == {"mfe_r": .8, "mae_r": -.3}


def test_negative_realized_profit_is_not_described_as_success():
    record = summarise_closed(entry_risk_cash=5, realized_net=-7)
    assert record["net_realized_r"] == -1.4
    assert record["net_cash"] == -7
