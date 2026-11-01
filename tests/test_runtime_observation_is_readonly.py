import threading
from types import SimpleNamespace
from unittest.mock import Mock


def test_live_observation_does_not_feed_learning_or_persistence(monkeypatch):
    from modules.unified_runtime import NiblitUnifiedRuntime, RuntimeState
    import modules.local_brain as local
    monkeypatch.setattr(local, 'get_local_brain', lambda: SimpleNamespace(status=lambda: {}))
    runtime = NiblitUnifiedRuntime.__new__(NiblitUnifiedRuntime)
    runtime._lock = threading.RLock()
    runtime._state = RuntimeState()
    runtime._state_file = 'unused.json'
    runtime.provider_runtime = SimpleNamespace(status=lambda: {})
    runtime.deployment_runtime = SimpleNamespace(detect=lambda: {})
    runtime.cognitive_runtime = SimpleNamespace(status=lambda: {})
    runtime.legacy_cognition_recovery = SimpleNamespace(build_report=lambda **kwargs: {})
    runtime.market_cognition = Mock()
    runtime.market_cognition.status.return_value = {}
    runtime.adaptive_retrieval = SimpleNamespace(status=lambda: {})
    runtime.hypothesis_engine = Mock()
    runtime.hypothesis_engine.status.return_value = {}
    runtime.telemetry_runtime = SimpleNamespace(snapshot=lambda **kwargs: {})
    runtime._event_bus = Mock()
    runtime._event_bus.stats.return_value = {}
    runtime._event_bus.events.return_value = []
    runtime._foundation_architecture = Mock()
    runtime._foundation_architecture.status.return_value = {}
    runtime._architecture_model = None
    runtime.model_manager_status = lambda: {}
    runtime._save_state = Mock()
    for _ in range(3):
        assert runtime.stream_frame(core=None)['stream_format'] == 'niblit.runtime.stream.v1'
        runtime.state(core=None)
    runtime.hypothesis_engine.ingest_snapshot_sources.assert_not_called()
    runtime._foundation_architecture.record_model_selection.assert_not_called()
    runtime._event_bus.emit.assert_not_called()
    runtime._save_state.assert_not_called()
    assert all(call.kwargs['core'] is None for call in runtime.market_cognition.status.call_args_list)
    assert runtime._state.telemetry_snapshots == []
