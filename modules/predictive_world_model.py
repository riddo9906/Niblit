#!/usr/bin/env python3
"""
modules/predictive_world_model.py — Phase Ω Predictive World Model

Expands ``forecast_arbitrator`` into a full **multi-horizon predictive
intelligence layer**.

Capabilities
------------
    multi_horizon_forecast    — short / medium / long term predictions
    confidence_propagation    — uncertainty grows with horizon
    scenario_simulation       — generate named alternative futures
    counterfactual_futures    — "what if X had not happened"
    market_regime_classifier  — bull / bear / sideways / volatile
    uncertainty_cones         — confidence bands per horizon
    strategic_anticipation    — attach action recommendations to forecasts
    consequence_estimation    — estimate impact of proposed actions

Architecture::

    Signal inputs (price, RSI, volume, external)
         │
         ▼
    MarketRegimeClassifier
         │
         ▼
    HorizonForecaster (short / medium / long)
         │
         ├── UncertaintyConeBuilder
         ├── ScenarioSimulator
         └── CounterfactualEngine
                   │
                   ▼
             WorldModelOutput
                   │
              StrategicAnticipator → action_recommendations

Configuration (env vars)
------------------------
    NIBLIT_PWM_ENABLED      — "0" to disable (default 1)
    NIBLIT_PWM_HORIZONS     — comma-separated horizon labels (default short,medium,long)

Usage::

    from modules.predictive_world_model import get_predictive_world_model

    pwm = get_predictive_world_model()
    pwm.ingest_signal(price=50000.0, rsi=58.0, volume_delta=0.03)
    output = pwm.forecast()
    print(output.regime)           # "bull"
    print(output.horizons["short"].direction)  # "bullish"
    print(output.scenarios)
"""

from __future__ import annotations

import logging
import os
import threading
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

log = logging.getLogger(__name__)

_ENABLED: bool = os.getenv("NIBLIT_PWM_ENABLED", "1").strip() not in ("0", "false")
_HORIZON_LABELS: List[str] = [
    h.strip() for h in os.getenv("NIBLIT_PWM_HORIZONS", "short,medium,long").split(",")
]


# ── Data structures ───────────────────────────────────────────────────────────

@dataclass
class HorizonForecast:
    """Forecast for a single time horizon."""
    label: str               # short | medium | long
    direction: str           # bullish | bearish | neutral
    confidence: float        # 0.0–1.0
    uncertainty: float       # grows with horizon
    lower_bound: float       # price / value lower cone
    upper_bound: float       # price / value upper cone

    def to_dict(self) -> Dict:
        return {
            "label": self.label,
            "direction": self.direction,
            "confidence": round(self.confidence, 4),
            "uncertainty": round(self.uncertainty, 4),
            "lower_bound": round(self.lower_bound, 2),
            "upper_bound": round(self.upper_bound, 2),
        }


@dataclass
class ScenarioForecast:
    """An alternative future scenario."""
    name: str         # e.g. "bull_breakout", "bear_continuation", "sideways"
    probability: float
    description: str
    action_recommendation: str

    def to_dict(self) -> Dict:
        return {
            "name": self.name,
            "probability": round(self.probability, 4),
            "description": self.description,
            "action_recommendation": self.action_recommendation,
        }


@dataclass
class WorldModelOutput:
    """Full predictive world model output."""
    regime: str                          # bull | bear | sideways | volatile
    regime_confidence: float
    horizons: Dict[str, HorizonForecast]
    scenarios: List[ScenarioForecast]
    counterfactuals: List[str]
    action_recommendations: List[str]
    overall_uncertainty: float
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> Dict:
        return {
            "regime": self.regime,
            "regime_confidence": round(self.regime_confidence, 4),
            "horizons": {k: v.to_dict() for k, v in self.horizons.items()},
            "scenarios": [s.to_dict() for s in self.scenarios],
            "counterfactuals": list(self.counterfactuals),
            "action_recommendations": list(self.action_recommendations),
            "overall_uncertainty": round(self.overall_uncertainty, 4),
        }


# ── PredictiveWorldModel ──────────────────────────────────────────────────────

class PredictiveWorldModel:
    """Multi-horizon predictive intelligence layer.

    Thread-safe singleton.
    """

    _REGIME_THRESHOLDS = {
        "rsi_overbought": 70.0,
        "rsi_oversold":   30.0,
        "vol_high":        0.04,
        "vol_low":         0.01,
    }

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._signals: List[Dict] = []         # time-series of ingested signals
        self._forecast_count: int = 0
        self._last_output: Optional[WorldModelOutput] = None
        log.debug("[PredictiveWorldModel] initialised")

    # ── Signal ingestion ──────────────────────────────────────────────────────

    def ingest_signal(
        self,
        price: float = 0.0,
        rsi: float = 50.0,
        volume_delta: float = 0.0,
        macd: float = 0.0,
        external_score: float = 0.5,
        timestamp: Optional[float] = None,
    ) -> None:
        """Record a market / world signal for use in forecasting.

        Args:
            price:          Current asset price (or 0 to skip).
            rsi:            RSI value 0–100.
            volume_delta:   Volume change fraction (positive = increasing).
            macd:           MACD histogram value.
            external_score: External sentiment 0.0–1.0 (0=bearish, 1=bullish).
        """
        with self._lock:
            self._signals.append({
                "ts": timestamp or time.time(),
                "price": price,
                "rsi": rsi,
                "volume_delta": volume_delta,
                "macd": macd,
                "external_score": external_score,
            })
            # Keep a rolling window
            if len(self._signals) > 500:
                self._signals = self._signals[-500:]

    # ── Forecasting ───────────────────────────────────────────────────────────

    def forecast(self) -> WorldModelOutput:
        """Generate a full :class:`WorldModelOutput` from accumulated signals.

        Returns:
            :class:`WorldModelOutput`.
        """
        if not _ENABLED:
            return _empty_output()

        with self._lock:
            signals = list(self._signals[-20:])  # last 20 signals
            self._forecast_count += 1

        if not signals:
            signals = [{"rsi": 50.0, "volume_delta": 0.0, "macd": 0.0,
                        "external_score": 0.5, "price": 0.0, "ts": time.time()}]

        last = signals[-1]
        regime, regime_conf = self._classify_regime(signals)
        direction = self._regime_to_direction(regime)
        base_confidence = regime_conf
        base_price = last.get("price", 0.0)

        horizons: Dict[str, HorizonForecast] = {}
        uncertainty_growth = 0.12
        for idx, label in enumerate(_HORIZON_LABELS):
            unc = min(0.9, uncertainty_growth * (idx + 1))
            conf = max(0.1, base_confidence - unc * 0.5)
            spread = base_price * unc * 0.5 if base_price > 0 else unc
            horizons[label] = HorizonForecast(
                label=label,
                direction=direction,
                confidence=conf,
                uncertainty=unc,
                lower_bound=max(0.0, base_price - spread),
                upper_bound=base_price + spread,
            )

        scenarios = self._build_scenarios(regime, regime_conf, base_price)
        counterfactuals = self._build_counterfactuals(signals)
        recommendations = self._build_recommendations(regime, regime_conf)
        overall_unc = min(0.9, sum(h.uncertainty for h in horizons.values()) / max(1, len(horizons)))

        output = WorldModelOutput(
            regime=regime,
            regime_confidence=round(regime_conf, 4),
            horizons=horizons,
            scenarios=scenarios,
            counterfactuals=counterfactuals,
            action_recommendations=recommendations,
            overall_uncertainty=round(overall_unc, 4),
        )
        with self._lock:
            self._last_output = output

        self._emit_event(output)
        return output

    def last_output(self) -> Optional[WorldModelOutput]:
        with self._lock:
            return self._last_output

    # ── Status ────────────────────────────────────────────────────────────────

    def status(self) -> Dict:
        with self._lock:
            return {
                "enabled": _ENABLED,
                "signal_count": len(self._signals),
                "forecast_count": self._forecast_count,
                "last_regime": self._last_output.regime if self._last_output else None,
            }

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _classify_regime(self, signals: List[Dict]) -> Tuple[str, float]:
        if not signals:
            return "neutral", 0.5
        avg_rsi = sum(s.get("rsi", 50.0) for s in signals) / len(signals)
        avg_vol = sum(abs(s.get("volume_delta", 0.0)) for s in signals) / len(signals)
        avg_ext = sum(s.get("external_score", 0.5) for s in signals) / len(signals)
        avg_macd = sum(s.get("macd", 0.0) for s in signals) / len(signals)

        bull_score = 0.0
        bear_score = 0.0
        bull_score += max(0.0, (avg_rsi - 50) / 50) * 0.4
        bear_score += max(0.0, (50 - avg_rsi) / 50) * 0.4
        bull_score += max(0.0, avg_ext - 0.5) * 0.4
        bear_score += max(0.0, 0.5 - avg_ext) * 0.4
        if avg_macd > 0:
            bull_score += min(0.2, avg_macd * 2)
        else:
            bear_score += min(0.2, abs(avg_macd) * 2)

        if avg_vol > self._REGIME_THRESHOLDS["vol_high"]:
            return "volatile", min(0.9, 0.5 + avg_vol * 3)

        if bull_score > bear_score + 0.1:
            return "bull", min(0.9, 0.5 + bull_score)
        if bear_score > bull_score + 0.1:
            return "bear", min(0.9, 0.5 + bear_score)
        return "sideways", 0.55

    def _regime_to_direction(self, regime: str) -> str:
        return {"bull": "bullish", "bear": "bearish",
                "sideways": "neutral", "volatile": "uncertain",
                "neutral": "neutral"}.get(regime, "neutral")

    def _build_scenarios(self, regime: str, conf: float, price: float) -> List[ScenarioForecast]:
        scenarios = []
        if regime == "bull":
            scenarios.append(ScenarioForecast("bull_continuation", conf,
                "Momentum continues upward", "consider long position with tight stop"))
            scenarios.append(ScenarioForecast("bull_exhaustion", 1 - conf,
                "Overbought; reversal possible", "tighten stops or reduce exposure"))
        elif regime == "bear":
            scenarios.append(ScenarioForecast("bear_continuation", conf,
                "Downtrend deepens", "reduce risk, consider defensive positioning"))
            scenarios.append(ScenarioForecast("bear_reversal", 1 - conf,
                "Oversold bounce may emerge", "watch for volume confirmation before entry"))
        else:
            scenarios.append(ScenarioForecast("range_bound", 0.6,
                "Sideways price action", "wait for breakout confirmation"))
            scenarios.append(ScenarioForecast("volatility_spike", 0.4,
                "External catalyst triggers move", "reduce position size"))
        return scenarios

    def _build_counterfactuals(self, signals: List[Dict]) -> List[str]:
        cf = []
        if len(signals) < 2:
            return cf
        last = signals[-1]
        if last.get("rsi", 50) > 70:
            cf.append("If RSI had stayed below 70, bull continuation likelihood was higher.")
        if last.get("volume_delta", 0) < 0:
            cf.append("If volume had increased, trend confidence would be stronger.")
        return cf

    def _build_recommendations(self, regime: str, conf: float) -> List[str]:
        if conf < 0.4:
            return ["low_confidence: defer major decisions", "await more signal clarity"]
        if regime == "bull":
            return ["monitor for continuation signals", "set trailing stops"]
        if regime == "bear":
            return ["reduce exposure", "prioritise capital preservation"]
        if regime == "volatile":
            return ["reduce position size", "disable heavy forecasts if resource-constrained"]
        return ["maintain current strategy", "watch for regime shift"]

    def _emit_event(self, output: WorldModelOutput) -> None:
        try:
            from modules.event_bus import get_event_bus, NiblitEvent, EVENT_WORLD_MODEL_UPDATED
            get_event_bus().publish(NiblitEvent(
                type=EVENT_WORLD_MODEL_UPDATED,
                source="predictive_world_model",
                payload={"regime": output.regime, "uncertainty": output.overall_uncertainty},
            ))
        except Exception:
            pass


# ── Empty default ─────────────────────────────────────────────────────────────

def _empty_output() -> WorldModelOutput:
    return WorldModelOutput(
        regime="neutral", regime_confidence=0.5, horizons={},
        scenarios=[], counterfactuals=[], action_recommendations=[],
        overall_uncertainty=0.5,
    )


# ── Singleton ─────────────────────────────────────────────────────────────────
_pwm: Optional[PredictiveWorldModel] = None
_pwm_lock = threading.Lock()


def get_predictive_world_model() -> PredictiveWorldModel:
    """Return the module-level :class:`PredictiveWorldModel` singleton."""
    global _pwm
    with _pwm_lock:
        if _pwm is None:
            _pwm = PredictiveWorldModel()
    return _pwm
