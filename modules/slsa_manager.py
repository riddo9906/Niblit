#!/usr/bin/env python3
"""
SLSA MANAGER MODULE
Manages SLSA (Secure Software Learning Artifacts) generation
Singleton pattern - controls the SLSA engine dynamically
"""

import logging
import threading
import time
from typing import Dict, List, Any, Optional, Tuple

log = logging.getLogger("SLSAManager")


class SLSAManager:
    """Singleton manager to control SLSA engine dynamically."""
    
    _instance = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(SLSAManager, cls).__new__(cls)
        return cls._instance
    
    def __init__(self):
        if getattr(self, "_initialized", False):
            return
        self._initialized = True
        
        self.engine = None
        self.thread = None
        self.running = False
        self.topics = []
        self.lock = threading.RLock()
        
        log.info("✅ SLSAManager initialized")
    
    def start(self, topics: Optional[List[str]] = None) -> str:
        """
        Start SLSA engine with optional topics.
        
        Args:
            topics: List of research topics for SLSA
        
        Returns:
            Status message
        """
        with self.lock:
            if self.running and self.engine:
                log.warning("SLSA engine already running")
                return "SLSA engine already running."
            
            try:
                # Import here to avoid circular imports
                try:
                    try:
                        from slsa_generator_full import start_slsa
                    except ImportError:
                        from modules.slsa_generator_full import start_slsa
                    self.engine, self.thread = start_slsa(topics=topics)
                except ImportError:
                    log.warning("slsa_generator_full not available, using stub")
                    # Stub implementation if full generator not available
                    self.engine = type('SLSAGenerator', (), {
                        'stop_event': threading.Event(),
                        'topics': topics or [],
                        'stop': lambda: None
                    })()
                    self.thread = threading.Thread(target=lambda: None, daemon=True)
                
                self.running = True
                self.topics = topics or []
                log.info(f"🚀 SLSA engine started with topics: {self.topics}")
                return "SLSA engine started."
            
            except Exception as e:
                log.error(f"Failed to start SLSA: {e}")
                return f"Failed to start SLSA: {e}"
    
    def stop(self) -> str:
        """
        Stop SLSA engine.
        
        Returns:
            Status message
        """
        with self.lock:
            if not self.running or not self.engine:
                log.warning("SLSA engine not running")
                return "SLSA engine is not running."
            
            try:
                # Stop the engine
                if hasattr(self.engine, 'stop_event'):
                    self.engine.stop_event.set()
                elif hasattr(self.engine, 'stop'):
                    self.engine.stop()
                
                # Wait for thread
                if self.thread and self.thread.is_alive():
                    self.thread.join(timeout=5)
                
                self.engine = None
                self.thread = None
                self.running = False
                self.topics = []
                
                log.info("⏹️ SLSA engine stopped")
                return "SLSA engine stopped."
            
            except Exception as e:
                log.error(f"Failed to stop SLSA: {e}")
                return f"Failed to stop SLSA: {e}"
    
    def restart(self, topics: Optional[List[str]] = None) -> str:
        """
        Restart SLSA engine with optional new topics.
        
        Args:
            topics: New topics (optional)
        
        Returns:
            Status message
        """
        self.stop()
        time.sleep(0.5)
        return self.start(topics=topics)
    
    def status(self) -> str:
        """
        Get SLSA status.
        
        Returns:
            Status string
        """
        with self.lock:
            if self.running and self.engine:
                topics_str = ", ".join(self.topics) if self.topics else "No topics"
                return f"🚀 SLSA engine running on topics: {topics_str}"
            else:
                return "⏹️ SLSA engine is not active."
    
    def is_running(self) -> bool:
        """Check if SLSA is running."""
        with self.lock:
            return self.running and self.engine is not None
    
    def get_topics(self) -> List[str]:
        """Get current topics."""
        with self.lock:
            return list(self.topics)

    def add_topics(self, new_topics: List[str]) -> str:
        """
        Add new topics to the SLSA engine.

        If the engine is running, topics are appended to the active list and
        propagated to the engine object (no restart needed).  If the engine is
        not running it is started with the supplied topics.

        Args:
            new_topics: Topics to add (duplicates are ignored).

        Returns:
            Status message.
        """
        if not new_topics:
            return "No topics provided."

        with self.lock:
            added = []
            for t in new_topics:
                if t and t not in self.topics:
                    self.topics.append(t)
                    added.append(t)

            if not added:
                return "All topics already present."

            # Propagate to the live engine object if it exposes a 'topics' attribute
            if self.engine and hasattr(self.engine, "topics"):
                try:
                    # Always replace with a full copy to avoid aliasing issues
                    self.engine.topics = list(self.topics)
                except Exception:
                    pass

            log.info(f"📌 SLSA topics added: {added}")
            if self.running:
                return f"Topics added to running SLSA: {added}"
            # Not running — start with all accumulated topics
            return self.start(topics=list(self.topics))


# Global singleton instance
slsa_manager = SLSAManager()

# Export
__all__ = ["SLSAManager", "slsa_manager"]


if __name__ == "__main__":
    print('Running slsa_manager.py - Singleton SLSA Manager')
