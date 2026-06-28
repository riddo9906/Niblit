#!/usr/bin/env python3
"""
run_realtime.py — Launch Niblit's real-time Binance WebSocket intelligence stream.

BEFORE (polling):
    Every 60 s → fetch REST API → process → decide

AFTER (realtime):
    Live WebSocket ticks → build candles → compute indicators →
    embed into fused memory (SQLite + Qdrant) → decide instantly

Usage
-----
    python run_realtime.py [--symbol BTCUSDT] [--interval 1m] [--intra]

Options
-------
    --symbol   <SYM>    Binance trading pair  (default: btcusdt)
    --interval <INT>    Kline interval        (default: 1m)
    --intra             Enable intra-candle (tick-level) processing

Requirements
------------
    pip install python-binance pandas websockets

Environment variables (optional — loaded from .env)
    BINANCE_API_KEY
    BINANCE_API_SECRET
"""

import argparse
import asyncio
import logging
import os
import sys

from modules.runtime_bootstrap import bootstrap_runtime_environment

# ── ensure repo root is on sys.path (for running from any working directory) ──
_ROOT = str(bootstrap_runtime_environment(__file__))

# ── load .env if python-dotenv is available ──────────────────────────────────
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s][%(name)s][%(levelname)s] %(message)s",
)
log = logging.getLogger("run_realtime")


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Niblit real-time Binance WebSocket intelligence stream",
    )
    p.add_argument("--symbol",   default="btcusdt",   help="Binance symbol (default: btcusdt)")
    p.add_argument("--interval", default="1m",        help="Kline interval (default: 1m)")
    p.add_argument("--intra",    action="store_true",  help="Enable tick-level (intra-candle) processing")
    return p.parse_args()


async def _run(symbol: str, interval: str, intra: bool) -> None:
    from modules.realtime_stream import RealtimeStream
    stream = RealtimeStream(symbol=symbol, interval=interval, intra_candle=intra)

    log.info(
        "Starting RealtimeStream  symbol=%s  interval=%s  intra=%s",
        symbol, interval, intra,
    )
    try:
        await stream.start()
    except KeyboardInterrupt:
        log.info("Interrupted — stopping stream")
        stream.stop()


def main() -> None:
    args = _parse_args()
    try:
        asyncio.run(_run(args.symbol, args.interval, args.intra))
    except KeyboardInterrupt:
        log.info("Bye.")


if __name__ == "__main__":
    main()
