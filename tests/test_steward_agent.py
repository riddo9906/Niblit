import pytest

from modules.steward_agent import StewardBridge, configuration
from modules.environment_navigator import NAME


def test_agent_schema_is_distinct_from_responses_and_no_nested_credentials(monkeypatch):
    monkeypatch.delenv('OPENAI_AGENT_MODEL', raising=False)
    config = configuration()
    assert config['model'] == 'gpt-6-astra'
    assert config['tools'][0]['name'] == NAME
    assert 'strict' not in config['tools'][0]
    assert config['multi_agent']['enabled'] is False


def test_pending_batch_is_validated_before_any_tool_executes(monkeypatch):
    bridge = StewardBridge()
    monkeypatch.setattr(bridge, 'request', lambda *args: {'required_actions': [
        {'type': 'function_call', 'name': 'arbitrary_shell', 'arguments': {'cmd': 'anything'}}]})
    with pytest.raises(ValueError, match='Unsupported pending action'):
        bridge.handle_pending('session_123')


def test_bridge_dispatches_known_tool_and_returns_matching_ids(monkeypatch):
    import modules.steward_agent as steward
    bridge = StewardBridge()
    calls = []
    arguments = {'environment_type': 'workspace', 'action': 'describe', 'environment_details':
        {'name': 'test', 'url': '.', 'additional_context': '', 'object_id': ''}}
    def request(method, path, payload=None):
        calls.append((method, path, payload))
        return {'required_actions': [{'type': 'function_call', 'name': NAME, 'turn_id': 'turn_1',
            'call_id': 'call_1', 'arguments': arguments}]} if method == 'GET' else {}
    monkeypatch.setattr(bridge, 'request', request)
    monkeypatch.setattr(steward, 'navigate_and_describe_environment', lambda **args: {
        'id': 'local_run', 'status': 'completed', 'started_at': 'now', 'events': [],
        'result': {'mode': 'workspace_inspection', 'evidence': {'private': 'contents remain local'}}})
    assert bridge.handle_pending('session_1')['handled'] == 1
    event = calls[1][2]['events'][0]
    assert event['call_id'] == 'call_1' and event['turn_id'] == 'turn_1'
    assert 'contents remain local' not in event['output']


def test_agent_review_api_failure_is_visible(monkeypatch, tmp_path):
    from fastapi.testclient import TestClient
    import server
    from modules.environment_navigator import tool_runs
    from modules.openai_adapter import OpenAIAdapter
    monkeypatch.setenv('NIBLIT_WORKSPACE_ROOT', str(tmp_path))
    args = {'environment_type': 'workspace', 'action': 'explore', 'environment_details':
        {'name': 'test', 'url': '.', 'additional_context': '', 'object_id': ''}}
    run = tool_runs.start(args, background=False)
    def fail(self, *args, **kwargs):
        self.last_error = {'message': 'Provider rate limited'}
        return None
    monkeypatch.setattr(OpenAIAdapter, 'complete', fail)
    response = TestClient(server.app).post('/api/tools/runs/' + run['id'] + '/review', json={})
    assert response.status_code == 502
    assert response.json()['error'] == 'Provider rate limited'
