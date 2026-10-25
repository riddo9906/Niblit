"""Read-only Core bridge to the separately packaged Lean trading runtime."""
from __future__ import annotations

import asyncio
import json
import os
import time
import sys
from pathlib import Path
from types import SimpleNamespace
from urllib.request import urlopen


class TradingRuntimeClient:
    """Expose runtime identity/health without importing Lean's flat packages.

    Process ownership stays with the multi-repository supervisor. An existing
    healthy service is attached to and is never stopped by this client.
    Trading execution remains in Lean's API; this bridge places no orders.
    """

    owns_api = True

    def __init__(self):
        root = Path(sys.executable).resolve().parent
        if getattr(sys, 'frozen', False) and (root / 'freqtrade/niblit-freqtrade-worker.exe').is_file():
            # Direct executable launches get the same integrated paper feed as
            # the testing launcher; explicit operator configuration wins.
            if os.getenv('NIBLIT_TRADING_BACKEND', 'paper') == 'paper':
                data = Path(os.getenv('LOCALAPPDATA', str(Path.home()))) / 'Niblit/paper'
                data.mkdir(parents=True, exist_ok=True)
                for key, value in {
                    'NIBLIT_MARKET_DATA_PROVIDER': 'replay',
                    'NIBLIT_MARKET_DATA_TIMEFRAME': '1h',
                    'NIBLIT_PAPER_STATE_FILE': str(data / 'account.json'),
                    'NIBLIT_EXECUTION_DB': str(data / 'executions.sqlite'),
                    'NIBLIT_TRADING_CONTROL_FILE': str(data / 'control.json'),
                    'NIBLIT_REPLAY_STATE_FILE': str(data / 'replay.json'),
                    'NIBLIT_REPLAY_DATA_DIR': str(root / 'freqtrade/data'),
                }.items():
                    os.environ.setdefault(key, value)
        port = int(os.getenv("NIBLIT_TRADING_API_PORT", "8100"))
        self.url = f"http://127.0.0.1:{port}"
        self._health = {"backend": "unknown", "state": "starting", "mode": "observe", "healthy": False}
        self._owns_service = False
        self._orchestrator = None
        self._checked_at = 0.0

    def _refresh(self, force=False):
        if not force and time.monotonic() - self._checked_at < 1.0:
            return bool(self._health.get("healthy"))
        self._checked_at = time.monotonic()
        try:
            with urlopen(self.url + "/health", timeout=1) as response:
                payload = json.load(response)
            self._health = payload
            return payload.get("healthy") is True and payload.get("state") == "ready"
        except Exception as exc:
            self._health = {**self._health, "healthy": False, "state": "degraded", "error": str(exc)}
            return False

    async def start(self):
        if await asyncio.to_thread(self._refresh, True):
            return
        from modules.multi_repo_orchestrator import get_multi_repo_orchestrator

        self._orchestrator = get_multi_repo_orchestrator()
        if self._orchestrator.get_repo_manifest("niblit-lean-algos") is None:
            await asyncio.to_thread(self._orchestrator.boot)
        result = await asyncio.to_thread(self._orchestrator.start_managed_repositories, ["niblit-lean-algos"])
        state = result.get("niblit-lean-algos", {})
        self._owns_service = bool(state.get("pid"))
        deadline = time.monotonic() + 25
        while time.monotonic() < deadline:
            if await asyncio.to_thread(self._refresh, True):
                return
            await asyncio.sleep(0.25)
        raise RuntimeError(f"Lean service did not become ready at {self.url}: {self._health.get('error', state)}")

    async def stop(self):
        if self._owns_service and self._orchestrator is not None:
            await asyncio.to_thread(self._orchestrator.stop_managed_repositories, ["niblit-lean-algos"])
            self._owns_service = False

    @property
    def backend(self):
        self._refresh()
        return self._health.get("backend", "unknown")

    @property
    def state(self):
        self._refresh()
        return self._health.get("state", "degraded")

    @property
    def execution_mode(self):
        return self._health.get("mode", "observe")

    @property
    def trading_mode(self):
        return self.execution_mode

    @property
    def execution_enabled(self):
        return bool(self._health.get("execution_enabled", False))

    async def health(self):
        await asyncio.to_thread(self._refresh, True)
        return SimpleNamespace(**{**self._health, "error": self._health.get("error"), "market_data": self._health.get("market_data")})

    def status(self):
        self._refresh()
        return dict(self._health)

    get_status = status
