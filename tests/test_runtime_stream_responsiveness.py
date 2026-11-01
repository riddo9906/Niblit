"""A busy desktop telemetry snapshot must not freeze the backend event loop."""
import asyncio
import threading
from types import SimpleNamespace

import pytest
from fastapi import WebSocketDisconnect


def test_telemetry_capability_reads_have_no_persistence_events():
    from modules.command_registry import CanonicalRuntimeCapabilityRegistry
    events = []
    registry = CanonicalRuntimeCapabilityRegistry(event_emitter=lambda kind, payload: events.append(kind))
    registry.register("sample", lambda text: text, "test capability", "test",
                      dynamic_availability=lambda ctx: (ctx.get("ready", False), "not ready"))
    events.clear()
    for ready in [False, True, False]:
        snapshot = registry.capability_snapshot(context={"ready": ready}, surface="runtime", emit_events=False)
        assert snapshot[0]["available"] is ready
    assert events == []
    # Operator discovery still emits the normal lifecycle/audit transition.
    registry.capability_snapshot(context={"ready": True}, surface="runtime")
    assert events == ["capability.available"]


@pytest.mark.parametrize("module_name", ["server", "app"])
def test_websocket_snapshot_runs_off_the_request_loop(monkeypatch, module_name):
    import importlib
    module = importlib.import_module(module_name)
    loop_thread = threading.get_ident()
    worker_threads = []
    started, release = threading.Event(), threading.Event()

    def stream_frame(**kwargs):
        worker_threads.append(threading.get_ident())
        started.set()
        # Represents a slow runtime lock, disk operation or service probe.
        # A timer ensures the old implementation fails without hanging pytest.
        release.wait(2)
        return {"events": [], "stream_format": "niblit.runtime.stream.v1"}

    runtime = SimpleNamespace(stream_frame=stream_frame)
    monkeypatch.setattr(module, "_get_unified_runtime", lambda: runtime)
    monkeypatch.setattr(module, "get_core", lambda: object())

    class Socket:
        async def accept(self):
            pass

        async def send_json(self, frame):
            raise WebSocketDisconnect()

    async def run():
        task = asyncio.create_task(module.ws_runtime(Socket()))
        try:
            for _ in range(100):
                if started.is_set():
                    break
                await asyncio.sleep(0.005)
            assert started.is_set()
            # This is the same loop that must keep scheduling HTTP handlers.
            assert worker_threads == [worker_threads[0]]
            assert worker_threads[0] != loop_thread
        finally:
            release.set()
            await asyncio.wait_for(task, 3)

    asyncio.run(run())
