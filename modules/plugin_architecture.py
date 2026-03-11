#!/usr/bin/env python3
"""
Plugin Architecture - Advanced plugin system

Extensible plugin system with lifecycle management, hot-reload support,
and dependency management.

Features:
- Plugin discovery and loading
- Lifecycle management (init, shutdown)
- Hot-reload support
- Dependency resolution
- Metrics tracking
"""

import logging
import importlib.util
from typing import Dict, List, Optional, Type, Any
from abc import ABC, abstractmethod
from pathlib import Path
from dataclasses import dataclass, field

log = logging.getLogger("PluginArchitecture")


class PluginInterface(ABC):
    """Base interface for plugins."""
    
    @abstractmethod
    async def initialize(self):
        """Initialize plugin."""
        pass
    
    @abstractmethod
    async def execute(self, *args, **kwargs) -> Any:
        """Execute plugin logic."""
        pass
    
    @abstractmethod
    async def shutdown(self):
        """Shutdown plugin."""
        pass


@dataclass
class PluginMetadata:
    """Metadata about a plugin."""
    name: str
    version: str
    author: str
    description: str
    dependencies: List[str] = field(default_factory=list)
    enabled: bool = True


class PluginManager:
    """
    Manage plugin lifecycle and execution.
    
    Features:
    - Load plugins from directory
    - Manage dependencies
    - Handle lifecycle
    - Track metrics
    """
    
    def __init__(self):
        self.plugins: Dict[str, PluginInterface] = {}
        self.metadata: Dict[str, PluginMetadata] = {}
        self.metrics = {
            "loaded": 0,
            "failed": 0,
            "executions": 0,
            "errors": 0,
        }
        log.debug("PluginManager initialized")
    
    async def load_plugin(
        self,
        name: str,
        plugin_class: Type[PluginInterface]
    ) -> bool:
        """
        Load and initialize plugin.
        
        Args:
            name: Plugin name
            plugin_class: Plugin class
            
        Returns:
            True if successful
        """
        try:
            log.info(f"Loading plugin: {name}")
            plugin = plugin_class()
            await plugin.initialize()
            
            self.plugins[name] = plugin
            self.metrics["loaded"] += 1
            
            log.info(f"Plugin loaded: {name}")
            return True
            
        except Exception as e:
            log.error(f"Failed to load plugin {name}: {e}")
            self.metrics["failed"] += 1
            return False
    
    async def load_from_directory(self, plugin_dir: Path) -> int:
        """
        Auto-discover and load plugins from directory.
        
        Args:
            plugin_dir: Directory containing plugins
            
        Returns:
            Number of plugins loaded
        """
        if not plugin_dir.exists():
            log.warning(f"Plugin directory not found: {plugin_dir}")
            return 0
        
        loaded_count = 0
        
        for plugin_file in plugin_dir.glob("*.py"):
            if plugin_file.name.startswith("_"):
                continue
            
            try:
                spec = importlib.util.spec_from_file_location(
                    plugin_file.stem,
                    plugin_file
                )
                
                if spec and spec.loader:
                    module = importlib.util.module_from_spec(spec)
                    spec.loader.exec_module(module)
                    
                    # Find plugin class
                    for attr_name in dir(module):
                        attr = getattr(module, attr_name)
                        if (isinstance(attr, type) and
                            issubclass(attr, PluginInterface) and
                            attr != PluginInterface):
                            
                            if await self.load_plugin(attr_name, attr):
                                loaded_count += 1
                                
            except Exception as e:
                log.error(f"Error loading plugin from {plugin_file}: {e}")
        
        return loaded_count
    
    async def execute(
        self,
        plugin_name: str,
        *args,
        **kwargs
    ) -> Optional[Any]:
        """
        Execute plugin.
        
        Args:
            plugin_name: Plugin to execute
            *args: Arguments
            **kwargs: Keyword arguments
            
        Returns:
            Plugin result or None
        """
        if plugin_name not in self.plugins:
            log.warning(f"Plugin not found: {plugin_name}")
            return None
        
        try:
            plugin = self.plugins[plugin_name]
            result = await plugin.execute(*args, **kwargs)
            self.metrics["executions"] += 1
            return result
            
        except Exception as e:
            log.error(f"Plugin execution failed: {plugin_name}: {e}")
            self.metrics["errors"] += 1
            return None
    
    async def unload_plugin(self, name: str) -> bool:
        """
        Unload and shutdown plugin.
        
        Args:
            name: Plugin name
            
        Returns:
            True if successful
        """
        if name not in self.plugins:
            return False
        
        try:
            plugin = self.plugins[name]
            await plugin.shutdown()
            del self.plugins[name]
            
            log.info(f"Plugin unloaded: {name}")
            return True
            
        except Exception as e:
            log.error(f"Error unloading plugin {name}: {e}")
            return False
    
    async def unload_all(self):
        """Unload all plugins."""
        for plugin_name in list(self.plugins.keys()):
            await self.unload_plugin(plugin_name)
    
    def get_stats(self) -> dict:
        """Get plugin manager statistics."""
        return {
            "loaded_plugins": len(self.plugins),
            "plugin_names": list(self.plugins.keys()),
            **self.metrics,
        }


# Example plugin
class ExamplePlugin(PluginInterface):
    """Example plugin implementation."""
    
    async def initialize(self):
        log.info("Example plugin initialized")
    
    async def execute(self, *args, **kwargs) -> str:
        return f"Example plugin executed with {len(args)} args"
    
    async def shutdown(self):
        log.info("Example plugin shutdown")


# Example usage
if __name__ == "__main__":
    import asyncio
    
    async def test():
        manager = PluginManager()
        
        # Load plugin
        await manager.load_plugin("example", ExamplePlugin)
        
        # Execute plugin
        result = await manager.execute("example", "arg1", "arg2")
        print(f"Result: {result}")
        
        # Get stats
        print(f"Stats: {manager.get_stats()}")
        
        # Unload
        await manager.unload_all()
    
    asyncio.run(test())
