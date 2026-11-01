from types import SimpleNamespace
from unittest.mock import Mock
from unittest.mock import AsyncMock

from fastapi.testclient import TestClient


def test_configured_astra_is_advertised_exactly_without_claiming_connectivity(monkeypatch):
    import server
    import niblit_brain
    monkeypatch.setenv('OPENAI_API_KEY', 'test-key')
    monkeypatch.setenv('OPENAI_MODEL', 'gpt-6-astra')
    cloud = SimpleNamespace(list_models=AsyncMock(return_value={'data':[{'id':'local-test'}]}))
    monkeypatch.setattr(niblit_brain, 'get_niblit_cloud_brain', lambda: cloud)
    result = TestClient(server.app).get('/v1/inference/models').json()
    assert result['data'][0]['id'] == 'local-test'
    remote = next(model for model in result['data'] if model['id'] == 'openai/gpt-6-astra')
    assert remote['availability'] == 'configured_not_verified'
    assert 'test-key' not in str(result)


def test_greeting_uses_selected_model_but_core_commands_stay_local(monkeypatch):
    import server
    import niblit_brain
    from modules import llm_chat_memory

    core = SimpleNamespace(command_registry=SimpleNamespace(commands={}))
    runtime = Mock()
    runtime.dispatch_command.return_value = "actual Core status"
    cloud = Mock()
    cloud._request_json.return_value = {"model": "selected-local", "choices": [{"message": {"content": "Hello, how can I help?"}}]}
    memory = Mock()
    memory.load_messages.return_value = []
    monkeypatch.setattr(server, "get_core", lambda: core)
    monkeypatch.setattr(server, "_get_unified_runtime", lambda: runtime)
    monkeypatch.setattr(niblit_brain, "get_niblit_cloud_brain", lambda: cloud)
    monkeypatch.setattr(llm_chat_memory, "get_llm_chat_memory", lambda: memory)
    client = TestClient(server.app)
    result = client.post('/chat', json={"text": "hi", "model": "selected-local", "use_model": True})
    assert result.status_code == 200
    assert result.json()["source"] == "cloud"
    assert cloud._request_json.call_args.args[1]["model"] == "selected-local"
    runtime.dispatch_command.assert_not_called()
    memory.add_exchange.assert_called_once_with("hi", "Hello, how can I help?")
    result = client.post('/chat', json={"text": "status", "model": "selected-local", "use_model": True})
    assert result.json()["reply"] == "actual Core status"
    runtime.dispatch_command.assert_called_once()
    assert cloud._request_json.call_count == 1


def test_model_failure_is_explicit_and_never_looks_like_a_knowledge_reply(monkeypatch):
    import server
    import niblit_brain
    from modules import llm_chat_memory

    memory = Mock()
    memory.load_messages.return_value = []
    cloud = Mock()
    cloud._request_json.side_effect = RuntimeError("private upstream detail")
    monkeypatch.setattr(server, "get_core", lambda: SimpleNamespace(command_registry=None))
    monkeypatch.setattr(niblit_brain, "get_niblit_cloud_brain", lambda: cloud)
    monkeypatch.setattr(llm_chat_memory, "get_llm_chat_memory", lambda: memory)
    result = TestClient(server.app).post('/chat', json={"text": "hi", "model": "local", "use_model": True})
    assert result.status_code == 502
    assert "private upstream detail" not in result.text
    memory.add_exchange.assert_not_called()
