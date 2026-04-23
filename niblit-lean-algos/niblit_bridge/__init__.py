"""
niblit_bridge — Niblit ↔ LEAN / Freqtrade signal bridge package.

Provides two integration modes:

1. **File-based** (``NiblitBridge``) — reads signals from a shared JSON
   sidecar file written by Niblit's ``modules/lean_algo_manager.py``.
   Works inside QuantConnect Cloud where no network calls are possible.

2. **HTTP-based** (``NiblitHTTPAdapter``) — calls Niblit's
   ``POST /trade/signal`` endpoint over localhost.  Used by Freqtrade
   strategies running in a local venv (``niblit-py311``).

Quick start (Freqtrade)::

    from niblit_bridge.freqtrade_adapter import NiblitHTTPAdapter

    adapter = NiblitHTTPAdapter()   # reads NIBLIT_API_URL env var
    signal = adapter.get_signal("BTC/USDT", dataframe)
    # signal is "buy" | "sell" | "hold"
"""

from .connector import NiblitBridge
from .freqtrade_adapter import NiblitHTTPAdapter

__all__ = ["NiblitBridge", "NiblitHTTPAdapter"]

if __name__ == "__main__":
    print("Running __init__.py")
