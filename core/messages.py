from __future__ import annotations

import json
from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass, field
from typing import Any, Dict


@dataclass
class Message:
    """Lightweight message contract for inter-module communication."""

    message_type: str
    source: str
    target: str
    payload: Dict[str, Any] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)
    message_id: str | None = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Message":
        return cls(**data)


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
