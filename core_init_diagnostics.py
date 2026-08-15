#!/usr/bin/env python3
"""
NIBLIT CORE INITIALIZATION DIAGNOSTICS
Instrumented version of NiblitCore.__init__ to identify exact hang point.
"""

import time
import sys
import os
import datetime
import logging
import threading

# Set up a dedicated logger for diagnostics
DIAG_LOG = logging.getLogger("NiblitInitDiag")
DIAG_LOG.setLevel(logging.DEBUG)
_handler = logging.StreamHandler(sys.stderr)
_handler.setFormatter(logging.Formatter("[%(asctime)s][%(levelname)s] %(message)s"))
DIAG_LOG.addHandler(_handler)

# Checkpoint counter
_checkpoint_count = 0

def _checkpoint(msg: str):
    """Log a numbered checkpoint."""
    global _checkpoint_count
    _checkpoint_count += 1
    DIAG_LOG.info(f"[INIT {_checkpoint_count:03d}] {msg}")


def _instrumented_core_init():
    """Instrumented NiblitCore.__init__ sequence."""
    
    _checkpoint("entering __init__")
    
    # Import the NiblitConfig class
    _checkpoint("importing NiblitConfig")
    try:
        from niblit_core import NiblitConfig
        _checkpoint("NiblitConfig imported successfully")
    except Exception as e:
        _checkpoint(f"NiblitConfig import failed: {e}")
        raise

    # Import required modules
    _checkpoint("importing required modules")
    try:
        from pathlib import Path
        _checkpoint("Path imported")
    except Exception as e:
        _checkpoint(f"Path import failed: {e}")
        raise

    _checkpoint("creating config instance")
    config = NiblitConfig()
    _checkpoint("config created")

    _checkpoint("initializing circuit_breakers dict")
    circuit_breakers = {}
    _checkpoint("circuit_breakers dict initialized")

    _checkpoint("initializing db as None placeholder")
    db = None
    _checkpoint("db placeholder set")

    # Start of try block around core init
    _checkpoint("entering core initialization try block")

    _checkpoint("calling _init_improvements")
    try:
        # Import CommandRegistry etc.
        _checkpoint("importing CommandRegistry and related classes")
        try:
            from modules.command_registry import CommandRegistry
            _checkpoint("CommandRegistry imported")
        except Exception as e:
            _checkpoint(f"CommandRegistry import failed: {e}")

        try:
            from modules.async_task_coordinator import AsyncTaskCoordinator
            _checkpoint("AsyncTaskCoordinator imported")
        except Exception as e:
            _checkpoint(f"AsyncTaskCoordinator import failed: {e}")

        try:
            from modules.event_sourced_logger import EventStore
            _checkpoint("EventStore imported")
        except Exception as e:
            _checkpoint(f"EventStore import failed: {e}")

        try:
            from modules.rate_limiting import RateLimiter
            _checkpoint("RateLimiter imported")
        except Exception as e:
            _checkpoint(f"RateLimiter import failed: {e}")

        try:
            from modules.metrics_observability import TelemetryCollector
            _checkpoint("TelemetryCollector imported")
        except Exception as e:
            _checkpoint(f"TelemetryCollector import failed: {e}")

        try:
            from modules.circuit_breaker import CircuitBreaker
            _checkpoint("CircuitBreaker imported")
        except Exception as e:
            _checkpoint(f"CircuitBreaker import failed: {e}")

        try:
            from modules.connection_pool import ConnectionPool
            _checkpoint("ConnectionPool imported")
        except Exception as e:
            _checkpoint(f"ConnectionPool import failed: {e}")

        try:
            from modules.multi_level_caching import CacheStrategy
            _checkpoint("CacheStrategy imported")
        except Exception as e:
            _checkpoint(f"CacheStrategy import failed: {e}")

        try:
            from modules.learning_batcher import LearningBatcher
            _checkpoint("LearningBatcher imported")
        except Exception as e:
            _checkpoint(f"LearningBatcher import failed: {e}")

        try:
            from modules.plugin_architecture import PluginManager
            _checkpoint("PluginManager imported")
        except Exception as e:
            _checkpoint(f"PluginManager import failed: {e}")

        try:
            from modules.monitoring_alerting import AlertManager
            _checkpoint("AlertManager imported")
        except Exception as e:
            _checkpoint(f"AlertManager import failed: {e}")

        _checkpoint("finished importing improvement modules")

        _checkpoint("initializing CommandRegistry")
        command_registry = CommandRegistry(
            event_emitter=lambda *a, **k: None,
            context_provider=lambda: {},
        )
        _checkpoint("CommandRegistry initialized")

    except Exception as e:
        _checkpoint(f"_init_improvements partially failed: {e}")

    _checkpoint("returning from core init sequence")
    return True


if __name__ == "__main__":
    try:
        _instrumented_core_init()
        print("Core init sequence completed")
    except Exception as e:
        _checkpoint(f"Core init FAILED with exception: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)