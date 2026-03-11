#!/usr/bin/env python3
"""
Layered Architecture - Separation of concerns

CommandLayer -> RouterLayer -> LLMLayer

Each layer has clear responsibilities and can fail independently.
"""

import logging
from typing import Optional, Any
from abc import ABC, abstractmethod
import asyncio

log = logging.getLogger("LayeredArchitecture")


class Layer(ABC):
    """Base class for all processing layers."""
    
    @abstractmethod
    async def can_handle(self, text: str) -> bool:
        """Check if this layer can handle the text."""
        pass
    
    @abstractmethod
    async def process(self, text: str) -> Optional[str]:
        """Process text and return result."""
        pass


class CommandLayer(Layer):
    """
    Command execution layer.
    
    Handles:
    - System commands (help, status, metrics)
    - SLSA commands
    - Memory/learning commands
    - Internet commands
    
    No LLM involvement - direct execution only.
    """
    
    def __init__(self, command_registry: Any):
        self.registry = command_registry
        log.debug("CommandLayer initialized")
    
    async def can_handle(self, text: str) -> bool:
        return self.registry.can_handle(text)
    
    async def process(self, text: str) -> Optional[str]:
        log.debug(f"[COMMAND_LAYER] Processing: {text[:50]}")
        try:
            result = self.registry.execute(text)
            if result:
                log.info(f"[COMMAND_LAYER] Command executed successfully")
            return result
        except Exception as e:
            log.error(f"[COMMAND_LAYER] Error: {e}", exc_info=True)
            return None


class RouterLayer(Layer):
    """
    Routing/coordination layer.
    
    Handles:
    - Multi-agent coordination
    - Research routing
    - Reflection/thinking
    - Complex command sequences
    
    Can use router to coordinate between brain and modules.
    """
    
    def __init__(self, router: Any):
        self.router = router
        log.debug("RouterLayer initialized")
    
    async def can_handle(self, text: str) -> bool:
        # Handle complex routing scenarios
        ltext = text.lower().strip()
        return any(ltext.startswith(p) for p in [
            "self-research", "self-idea", "reflect", 
            "auto-reflect", "self-implement", "self-heal"
        ])
    
    async def process(self, text: str) -> Optional[str]:
        log.debug(f"[ROUTER_LAYER] Processing: {text[:50]}")
        try:
            if self.router:
                result = self.router.process(text)
                if result:
                    log.info(f"[ROUTER_LAYER] Router handled successfully")
                return result
            return None
        except Exception as e:
            log.error(f"[ROUTER_LAYER] Error: {e}", exc_info=True)
            return None


class LLMLayer(Layer):
    """
    LLM/conversation layer.
    
    Handles:
    - General chat
    - Thinking/reflection
    - Creative ideation
    
    Only reached after command and routing layers.
    Can be disabled without breaking commands.
    """
    
    def __init__(self, brain: Any, llm_enabled: bool = True):
        self.brain = brain
        self.llm_enabled = llm_enabled
        log.debug("LLMLayer initialized")
    
    async def can_handle(self, text: str) -> bool:
        # Always can handle general text
        return self.llm_enabled and self.brain is not None
    
    async def process(self, text: str) -> Optional[str]:
        log.debug(f"[LLM_LAYER] Processing: {text[:50]}")
        
        if not self.llm_enabled:
            log.warning("[LLM_LAYER] LLM is disabled")
            return None
        
        if not self.brain:
            log.warning("[LLM_LAYER] Brain not available")
            return None
        
        try:
            # Call brain.think() for general conversation
            result = self.brain.think(text)
            log.info(f"[LLM_LAYER] Brain processed successfully")
            return result
        except Exception as e:
            log.error(f"[LLM_LAYER] Error: {e}", exc_info=True)
            return None


class StackedArchitecture:
    """
    Stacked layer processor.
    
    Processes through layers in order:
    1. CommandLayer
    2. RouterLayer
    3. LLMLayer
    """
    
    def __init__(self):
        self.layers: list[Layer] = []
        log.debug("StackedArchitecture initialized")
    
    def add_layer(self, layer: Layer, position: int = None):
        """Add a layer to the stack."""
        if position is None:
            self.layers.append(layer)
        else:
            self.layers.insert(position, layer)
        log.info(f"Added layer: {layer.__class__.__name__}")
    
    async def process(self, text: str) -> str:
        """
        Process text through layers.
        
        Returns result from first layer that can handle it,
        or default message if no layer handles it.
        """
        log.debug(f"[STACKED_ARCH] Processing through {len(self.layers)} layers")
        
        for layer in self.layers:
            try:
                if await layer.can_handle(text):
                    log.debug(f"[STACKED_ARCH] Layer can handle: {layer.__class__.__name__}")
                    result = await layer.process(text)
                    if result:
                        return result
            except Exception as e:
                log.error(f"[STACKED_ARCH] Layer error: {e}", exc_info=True)
                continue
        
        # Fallback
        log.warning("[STACKED_ARCH] No layer handled the text")
        return f"I hear you: {text}"


# Example usage
if __name__ == "__main__":
    async def test():
        from modules.command_registry import CommandRegistry
        
        registry = CommandRegistry()
        registry.register("help", lambda t: "Help text", "Show help")
        registry.register("status", lambda t: "Status OK", "Show status")
        
        arch = StackedArchitecture()
        arch.add_layer(CommandLayer(registry))
        arch.add_layer(LLMLayer(None))  # No brain for testing
        
        result = await arch.process("help")
        print(f"Result: {result}")
    
    asyncio.run(test())
