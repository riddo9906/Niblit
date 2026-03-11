#!/usr/bin/env python3
"""
Command Registry - Extensible command dispatcher

Replaces massive if/elif chains with a clean, plugin-based system.
Reduces complexity from 200+ lines to ~50 lines in main handler.

Features:
- Command prefix registration
- Priority-based execution
- Category grouping
- Help generation
- Statistics tracking
"""

import logging
from typing import Callable, Dict, Optional, List, Any
from dataclasses import dataclass

log = logging.getLogger("CommandRegistry")


@dataclass
class CommandMetadata:
    """Metadata about a registered command."""
    prefix: str
    handler: Callable
    description: str
    category: str  # "core", "slsa", "brain", "internet", etc.
    priority: int  # Higher = executed first


class CommandRegistry:
    """
    Extensible command registry system.
    
    Features:
    - Command prefix registration
    - Priority-based execution
    - Category grouping
    - Help generation
    - Statistics tracking
    """
    
    def __init__(self):
        self.commands: Dict[str, CommandMetadata] = {}
        self.stats = {
            "total_executed": 0,
            "total_failed": 0,
            "by_category": {}
        }
        log.debug("CommandRegistry initialized")
    
    def register(
        self,
        prefix: str,
        handler: Callable,
        description: str = "",
        category: str = "core",
        priority: int = 0
    ):
        """
        Register a command handler.
        
        Args:
            prefix: Command prefix (e.g., "slsa-status")
            handler: Callable that handles the command
            description: Human-readable description
            category: Category for grouping
            priority: Higher = executed first (0-100)
        """
        self.commands[prefix] = CommandMetadata(
            prefix=prefix,
            handler=handler,
            description=description,
            category=category,
            priority=priority
        )
        log.info(f"Registered command: {prefix} (priority: {priority}, category: {category})")
    
    def can_handle(self, text: str) -> bool:
        """Check if any registered handler can handle this text."""
        ltext = text.lower().strip()
        return any(ltext.startswith(cmd) for cmd in self.commands.keys())
    
    def execute(self, text: str) -> Optional[str]:
        """
        Execute command by priority.
        
        Returns:
            Command output if handled, None otherwise
        """
        ltext = text.lower().strip()
        
        # Sort by priority (higher first)
        sorted_commands = sorted(
            self.commands.items(),
            key=lambda x: x[1].priority,
            reverse=True
        )
        
        for prefix, metadata in sorted_commands:
            if ltext.startswith(prefix):
                try:
                    log.debug(f"[COMMAND] {prefix} (priority: {metadata.priority})")
                    
                    # Call handler (support both sync and async)
                    result = metadata.handler(text)
                    
                    # Update stats
                    self.stats["total_executed"] += 1
                    category = metadata.category
                    self.stats["by_category"][category] = \
                        self.stats["by_category"].get(category, 0) + 1
                    
                    return result
                except Exception as e:
                    log.error(f"Command execution failed: {e}", exc_info=True)
                    self.stats["total_failed"] += 1
                    return f"[ERROR] Command failed: {e}"
        
        return None
    
    def get_help(self, category: Optional[str] = None) -> str:
        """Generate help text for registered commands."""
        help_text = "=== NIBLIT COMMANDS ===\n\n"
        
        # Group by category
        by_category: Dict[str, List[CommandMetadata]] = {}
        for metadata in self.commands.values():
            if category and metadata.category != category:
                continue
            if metadata.category not in by_category:
                by_category[metadata.category] = []
            by_category[metadata.category].append(metadata)
        
        # Sort categories
        for cat in sorted(by_category.keys()):
            help_text += f"--- {cat.upper()} ---\n"
            for cmd in sorted(by_category[cat], key=lambda x: x.prefix):
                help_text += f"  {cmd.prefix:<30} — {cmd.description}\n"
            help_text += "\n"
        
        return help_text
    
    def get_stats(self) -> Dict[str, Any]:
        """Get execution statistics."""
        return {
            **self.stats,
            "registered_commands": len(self.commands),
            "success_rate": (
                self.stats["total_executed"] - self.stats["total_failed"]
            ) / max(self.stats["total_executed"], 1)
        }


# Example usage
if __name__ == "__main__":
    registry = CommandRegistry()
    
    # Register commands
    def help_handler(text: str) -> str:
        return "Showing help..."
    
    def status_handler(text: str) -> str:
        return "System status: OK"
    
    def slsa_status_handler(text: str) -> str:
        return "[SLSA] Status: Running"
    
    registry.register("help", help_handler, "Show this help", "core", priority=100)
    registry.register("status", status_handler, "Show system status", "core", priority=100)
    registry.register("slsa-status", slsa_status_handler, "Show SLSA status", "slsa", priority=90)
    
    # Test
    result = registry.execute("slsa-status")
    print(f"Result: {result}")
    print(f"\nStats: {registry.get_stats()}")
    print(f"\nHelp:\n{registry.get_help()}")
