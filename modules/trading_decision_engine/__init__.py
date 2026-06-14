"""modules/trading_decision_engine — Niblit Decision Engine for trading.

Converts Qdrant + MemoryGraph state into structured trading decisions that
are compatible with Freqtrade execution logic.

Pipeline::

    query → memory (Qdrant) → graph (MemoryGraph) → scoring → decision → trade signal

Public API
----------
``NiblitDecisionEngine``   — core reasoning engine
``FreqtradeAdapter``       — converts decisions to Freqtrade-compatible signals
``TradingDecision``        — structured decision dataclass
"""

from modules.trading_decision_engine.freqtrade_adapter import FreqtradeAdapter
from modules.trading_decision_engine.niblit_decision_engine import (
    NiblitDecisionEngine,
    TradingDecision,
)

__all__ = ["NiblitDecisionEngine", "TradingDecision", "FreqtradeAdapter"]
