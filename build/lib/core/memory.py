from __future__ import annotations

from abc import ABC, abstractmethod
from collections import deque
from typing import Any, Deque, Dict, Generic, List, Optional, TypeVar

T = TypeVar("T")


class MemoryStore(ABC, Generic[T]):
    """Minimal memory interface for cognitive subsystems."""

    @abstractmethod
    def write(self, key: str, value: T) -> None:
        raise NotImplementedError

    @abstractmethod
    def read(self, key: str, default: Optional[T] = None) -> Optional[T]:
        raise NotImplementedError

    @abstractmethod
    def delete(self, key: str) -> None:
        raise NotImplementedError

    @abstractmethod
    def clear(self) -> None:
        raise NotImplementedError


class InMemoryShortTermMemory(MemoryStore[Any]):
    def __init__(self) -> None:
        self._store: Dict[str, Any] = {}

    def write(self, key: str, value: Any) -> None:
        self._store[key] = value

    def read(self, key: str, default: Optional[Any] = None) -> Optional[Any]:
        return self._store.get(key, default)

    def delete(self, key: str) -> None:
        self._store.pop(key, None)

    def clear(self) -> None:
        self._store.clear()


class InMemoryLongTermMemory(MemoryStore[Any]):
    def __init__(self) -> None:
        self._store: Dict[str, Any] = {}

    def write(self, key: str, value: Any) -> None:
        self._store[key] = value

    def read(self, key: str, default: Optional[Any] = None) -> Optional[Any]:
        return self._store.get(key, default)

    def delete(self, key: str) -> None:
        self._store.pop(key, None)

    def clear(self) -> None:
        self._store.clear()


class InMemoryWorkingMemory(MemoryStore[Any]):
    def __init__(self) -> None:
        self._store: Dict[str, Any] = {}

    def write(self, key: str, value: Any) -> None:
        self._store[key] = value

    def read(self, key: str, default: Optional[Any] = None) -> Optional[Any]:
        return self._store.get(key, default)

    def delete(self, key: str) -> None:
        self._store.pop(key, None)

    def clear(self) -> None:
        self._store.clear()


class InMemoryReplayMemory:
    def __init__(self, max_items: int = 100) -> None:
        self._max_items = max_items
        self._items: Deque[Any] = deque()

    def append(self, item: Any) -> None:
        self._items.append(item)
        if len(self._items) > self._max_items:
            self._items.popleft()

    def read(self) -> List[Any]:
        return list(self._items)

    def clear(self) -> None:
        self._items.clear()
