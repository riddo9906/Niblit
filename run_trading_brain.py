#!/usr/bin/env python3
"""
run_trading_brain.py — Continuous runner for Niblit's Trading Brain.

Pulls live Binance market data every 60 seconds, computes technical
indicators, embeds the market state into Niblit's fused memory, and
prints the resulting trade signal (BUY / SELL / HOLD).

Usage::

    # With Binance credentials (enables live order-book access)
    BINANCE_API_KEY=xxx BINANCE_API_SECRET=yyy python run_trading_brain.py

    # Keyless — read-only public market data only
    python run_trading_brain.py

    # Override symbol and interval
    TRADING_SYMBOL=ETHUSDT TRADING_INTERVAL=5m python run_trading_brain.py

Environment variables::

    BINANCE_API_KEY     — Binance API key (optional)
    BINANCE_API_SECRET  — Binance API secret (optional)
    TRADING_SYMBOL      — Trading pair, default BTCUSDT
    TRADING_INTERVAL    — Kline interval, default 1m
    TRADING_KLINE_LIMIT — Number of candles per cycle, default 200
    TRADING_CYCLE_SECS  — Seconds between cycles, default 60

Stop with Ctrl-C.
"""

import logging
import os
import time

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
log = logging.getLogger("run_trading_brain")

from modules.trading_brain import TradingBrain  # noqa: E402 — after logging setup

_CYCLE_SECS = int(os.getenv("TRADING_CYCLE_SECS", "60"))


def main() -> None:
    """Entry point — instantiate TradingBrain and loop forever."""
    log.info("Starting Niblit Trading Brain (cycle=%ds)…", _CYCLE_SECS)

    brain = TradingBrain()

    try:
        while True:
            decision = brain.cycle()
            log.info("Decision → %s", decision)
            time.sleep(_CYCLE_SECS)
    except KeyboardInterrupt:
        log.info("Trading Brain stopped by user.")


if __name__ == "__main__":
    main()
