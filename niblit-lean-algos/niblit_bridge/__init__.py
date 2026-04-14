"""
niblit_bridge — Niblit ↔ LEAN signal bridge package.

Provides the NiblitBridge class used by every algorithm in this repo
to optionally read trading signals from Niblit's TradingBrain without
importing any Niblit Python modules (which are not available on
QuantConnect Cloud).

Integration is purely file-based:

    Niblit writes → /tmp/niblit_lean_signal.json
    LEAN reads   ← NiblitBridge.get_signal()
"""

from .connector import NiblitBridge

__all__ = ["NiblitBridge"]
