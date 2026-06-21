from __future__ import annotations

import json
from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass, field
from typing import Any, Dict


class StandardEventType:
    """Versioned event names shared across the Niblit architecture layers."""

    MARKET_DATA_RECEIVED = "market_data.received"
    INDICATOR_UPDATED = "indicator.updated"
    SIGNAL_GENERATED = "signal.generated"
    AI_INFERENCE_REQUESTED = "ai.inference.requested"
    AI_INFERENCE_COMPLETED = "ai.inference.completed"
    CONTEXT_UPDATED = "context.updated"
    LEARNING_EVENT = "learning.event"
    MEMORY_STORED = "memory.stored"
    DECISION_REQUESTED = "decision.requested"
    DECISION_APPROVED = "decision.approved"
    DECISION_REJECTED = "decision.rejected"
    RISK_EVALUATION_COMPLETED = "risk.evaluation.completed"
    TRADE_PROPOSED = "trade.proposed"
    TRADE_APPROVED = "trade.approved"
    TRADE_EXECUTED = "trade.executed"
    TRADE_REJECTED = "trade.rejected"
    ORDER_FILLED = "order.filled"
    POSITION_CHANGED = "position.changed"
    PERFORMANCE_UPDATED = "performance.updated"
    FEEDBACK_RECEIVED = "feedback.received"
    STRATEGY_UPDATED = "strategy.updated"
    ERROR_OCCURRED = "error.occurred"
    HEARTBEAT = "heartbeat"


@dataclass
class Message:
    """Lightweight message contract for inter-module communication."""

    message_type: str
    source: str
    target: str
    payload: Dict[str, Any] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)
    message_id: str | None = None
    schema_version: str = "1.0"
    correlation_id: str | None = None
    timestamp: float | None = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Message":
        return cls(**data)


@dataclass
class MarketSnapshot:
    """Normalized market observation for the cognitive decision pipeline."""

    symbol: str
    price: float
    volume: float | None = None
    bid: float | None = None
    ask: float | None = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class AIRequest:
    """Request payload sent to the AI inference layer."""

    model_id: str
    prompt: str
    market_snapshot: MarketSnapshot | None = None
    context: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        payload = asdict(self)
        if self.market_snapshot is not None:
            payload["market_snapshot"] = self.market_snapshot.to_dict()
        return payload


@dataclass
class RiskAssessment:
    """Structured risk evaluation emitted by governance logic."""

    level: str
    confidence: float
    rationale: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class MessageSerializer(ABC):
    """Serializer abstraction for message transport."""

    @abstractmethod
    def serialize(self, message: Message) -> str:
        raise NotImplementedError

    @abstractmethod
    def deserialize(self, payload: str) -> Message:
        raise NotImplementedError


class JsonMessageSerializer(MessageSerializer):
    """Simple JSON-based message serializer used for testing and routing."""

    def serialize(self, message: Message) -> str:
        return json.dumps(message.to_dict(), sort_keys=True)

    def deserialize(self, payload: str) -> Message:
        data = json.loads(payload)
        return Message.from_dict(data)
