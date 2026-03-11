#!/usr/bin/env python3
"""
Dependency Injection - Configurable dependencies for testing

Enables:
- Easy mocking
- Testing without side effects
- Configuration flexibility
- Loose coupling between components
"""

import logging
from typing import Type, Any, Dict, Optional, Callable
from abc import ABC, abstractmethod

log = logging.getLogger("DependencyInjection")


# ============= SERVICE INTERFACES =============

class DatabaseInterface(ABC):
    @abstractmethod
    async def add_fact(self, key: str, value: Any):
        pass
    
    @abstractmethod
    async def get_fact(self, key: str) -> Optional[Any]:
        pass


class BrainInterface(ABC):
    @abstractmethod
    async def think(self, text: str) -> str:
        pass
    
    @abstractmethod
    async def handle_command(self, text: str) -> str:
        pass


class InternetInterface(ABC):
    @abstractmethod
    async def search(self, query: str) -> list:
        pass


class RouterInterface(ABC):
    @abstractmethod
    async def process(self, text: str) -> str:
        pass


# ============= MOCK IMPLEMENTATIONS =============

class MockDatabase(DatabaseInterface):
    def __init__(self):
        self.data = {}
        log.debug("MockDatabase initialized")
    
    async def add_fact(self, key: str, value: Any):
        self.data[key] = value
        log.debug(f"MockDatabase: Added {key}")
    
    async def get_fact(self, key: str) -> Optional[Any]:
        return self.data.get(key)


class MockBrain(BrainInterface):
    async def think(self, text: str) -> str:
        log.debug(f"MockBrain: Thinking about '{text}'")
        return f"[MockBrain] Response to: {text}"
    
    async def handle_command(self, text: str) -> str:
        log.debug(f"MockBrain: Handling command '{text}'")
        return f"[MockBrain] Command result: {text}"


class MockInternet(InternetInterface):
    async def search(self, query: str) -> list:
        log.debug(f"MockInternet: Searching for '{query}'")
        return [f"Mock result for {query}"]


class MockRouter(RouterInterface):
    async def process(self, text: str) -> str:
        log.debug(f"MockRouter: Processing '{text}'")
        return f"[MockRouter] Routed: {text}"


# ============= DEPENDENCY CONTAINER =============

class Container:
    """
    Dependency Injection Container.
    
    Manages service registration and resolution.
    """
    
    def __init__(self):
        self._services: Dict[str, Any] = {}
        self._factories: Dict[str, Callable] = {}
        log.debug("Container initialized")
    
    def register_singleton(self, name: str, instance: Any):
        """Register a singleton service."""
        self._services[name] = instance
        log.info(f"Registered singleton: {name}")
    
    def register_factory(self, name: str, factory: Callable):
        """Register a factory for creating instances."""
        self._factories[name] = factory
        log.info(f"Registered factory: {name}")
    
    def resolve(self, name: str) -> Any:
        """Resolve a service."""
        if name in self._services:
            return self._services[name]
        
        if name in self._factories:
            return self._factories[name]()
        
        raise KeyError(f"Service '{name}' not registered")
    
    def has(self, name: str) -> bool:
        """Check if service is registered."""
        return name in self._services or name in self._factories


# ============= SERVICE LOCATOR (Alternative Pattern) =============

class ServiceLocator:
    """
    Service Locator pattern.
    
    Alternative to DI - useful for legacy code integration.
    """
    
    _instance = None
    _services: Dict[str, Any] = {}
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance
    
    @classmethod
    def register(cls, name: str, service: Any):
        cls._services[name] = service
        log.info(f"ServiceLocator: Registered {name}")
    
    @classmethod
    def get(cls, name: str) -> Any:
        if name not in cls._services:
            raise KeyError(f"Service '{name}' not registered")
        return cls._services[name]


# ============= EXAMPLE USAGE =============

class NiblitCoreWithDI:
    """Example of how to use DI in NiblitCore."""
    
    def __init__(
        self,
        db: DatabaseInterface,
        brain: BrainInterface,
        internet: InternetInterface,
        router: RouterInterface,
    ):
        self.db = db
        self.brain = brain
        self.internet = internet
        self.router = router
        log.debug("NiblitCoreWithDI initialized with injected dependencies")
    
    async def handle(self, text: str) -> str:
        """Handle command using injected services."""
        # Can use any implementation (real or mock)
        return await self.brain.think(text)


if __name__ == "__main__":
    import asyncio
    
    # Production setup
    prod_container = Container()
    # prod_container.register_singleton("db", RealDatabase())
    # prod_container.register_singleton("brain", RealBrain())
    
    # Test setup
    test_container = Container()
    test_container.register_singleton("db", MockDatabase())
    test_container.register_singleton("brain", MockBrain())
    test_container.register_singleton("internet", MockInternet())
    test_container.register_singleton("router", MockRouter())
    
    async def test():
        # Get services from test container
        db = test_container.resolve("db")
        brain = test_container.resolve("brain")
        internet = test_container.resolve("internet")
        router = test_container.resolve("router")
        
        # Create core with test services
        core = NiblitCoreWithDI(db, brain, internet, router)
        
        # Use it
        result = await core.handle("help")
        print(f"Result: {result}")
    
    asyncio.run(test())
