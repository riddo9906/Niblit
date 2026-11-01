from unittest.mock import Mock

import pytest
import requests

from modules.openai_adapter import OpenAIAdapter


@pytest.fixture(autouse=True)
def mocked_provider_uses_separate_budget_policy(monkeypatch):
    # Provider protocol tests mock all network calls. Budget policy has its
    # own real SQLite/concurrency tests, with enforcement enabled.
    monkeypatch.setenv('OPENAI_BUDGET_ENFORCE', '0')


def response(data, status=200):
    r = Mock(status_code=status, headers={"x-request-id": "req_test"})
    r.json.return_value = data
    return r


def completed(text="READY"):
    return {"id": "resp_test", "status": "completed", "model": "configured-model", "usage": {"output_tokens": 2},
            "output": [{"type": "reasoning", "summary": []}, {"type": "message", "content": [{"type": "output_text", "text": text}]}]}


def test_astra_preserves_exact_model_and_uses_bounded_reasoning(monkeypatch):
    post = Mock(return_value=response(completed()))
    monkeypatch.setattr(requests, 'post', post)
    monkeypatch.delenv('OPENAI_REASONING_EFFORT', raising=False)
    adapter = OpenAIAdapter(api_key='test-key', model='gpt-6-astra')
    assert adapter.complete([{'role':'user', 'content':'hello'}], max_tokens=1000, temperature=.2)
    payload = post.call_args.kwargs['json']
    assert payload['model'] == 'gpt-6-astra'
    assert payload['reasoning'] == {'effort':'low'}
    assert payload['max_output_tokens'] == 1000 and 'temperature' not in payload


def test_responses_payload_and_multi_item_output_preserve_configured_model(monkeypatch):
    post = Mock(return_value=response(completed()))
    monkeypatch.setattr(requests, "post", post)
    adapter = OpenAIAdapter(api_key="test-key", model="configured-model")
    result = adapter.complete([{"role": "user", "content": "hello"}], max_tokens=64)
    assert result["text"] == "READY"
    assert result["request_id"] == "req_test"
    assert adapter.last_response["model"] == "configured-model"
    assert "text" not in adapter.last_response
    args = post.call_args
    assert args.args[0] == "https://api.openai.com/v1/responses"
    assert args.kwargs["json"] == {"model": "configured-model", "store": False, "input": [{"role": "user", "content": "hello"}], "max_output_tokens": 64}
    assert args.kwargs["allow_redirects"] is False


@pytest.mark.parametrize("status,code,expected", [(401,"invalid_api_key","authentication_failed"),(429,"insufficient_quota","quota_exhausted"),(404,"model_not_found","model_access_denied")])
def test_auth_and_quota_errors_are_safe_and_not_retried(monkeypatch, status, code, expected):
    post = Mock(return_value=response({"error": {"code": code, "message": "test-key private detail"}},status))
    monkeypatch.setattr(requests, "post", post)
    adapter = OpenAIAdapter(api_key="test-key")
    assert adapter.query([{"role":"user","content":"hi"}]) is None
    assert adapter.last_error["code"] == expected
    assert "test-key" not in str(adapter.last_error)
    assert post.call_count == 1


def test_transient_errors_have_a_bounded_retry(monkeypatch):
    post = Mock(side_effect=[response({"error":{}},503),response(completed())])
    monkeypatch.setattr(requests,"post",post)
    monkeypatch.setattr("modules.openai_adapter.time.sleep",lambda _:None)
    assert OpenAIAdapter(api_key="fake", max_retries=1).query([{"role":"user","content":"hi"}]) == "READY"
    assert post.call_count == 2


def test_timeout_is_not_replayed(monkeypatch):
    post=Mock(side_effect=requests.Timeout())
    monkeypatch.setattr(requests,"post",post)
    adapter=OpenAIAdapter(api_key="fake")
    assert adapter.query([{"role":"user","content":"hi"}]) is None
    assert adapter.last_error["code"] == "timeout"
    assert post.call_count == 1


def test_model_parameter_rejection_removes_temperature_once(monkeypatch):
    calls=[]
    def post(*args,**kwargs):
        calls.append(dict(kwargs["json"]))
        return response({"error":{"code":"unsupported_parameter","param":"temperature"}},400) if len(calls)==1 else response(completed())
    monkeypatch.setattr(requests,"post",post)
    assert OpenAIAdapter(api_key="fake").query([{"role":"user","content":"hi"}],temperature=.2)=="READY"
    assert calls[0]["temperature"]==.2
    assert "temperature" not in calls[1]


@pytest.mark.parametrize("data,code", [({"status":"incomplete","output":completed()["output"]},"response_not_completed"),({"status":"completed","output":[{"type":"function_call","name":"run_code"}]},"empty_response"),({"output":"bad"},"invalid_response")])
def test_incomplete_and_tool_only_outputs_do_not_look_successful(monkeypatch,data,code):
    monkeypatch.setattr(requests,"post",lambda *a,**k:response(data))
    adapter=OpenAIAdapter(api_key="fake")
    assert adapter.query([{"role":"user","content":"hi"}]) is None
    assert adapter.last_error["code"]==code


def test_refusal_and_explicit_legacy_mode(monkeypatch):
    monkeypatch.setattr(requests,"post",lambda *a,**k:response({"status":"completed","output":[{"type":"message","content":[{"type":"refusal","refusal":"I cannot assist with that."}]}]}))
    adapter=OpenAIAdapter(api_key="fake")
    assert adapter.query([{"role":"user","content":"hi"}])=="I cannot assist with that."
    assert adapter.last_response["refusal"] is True
    post=Mock(return_value=response({"choices":[{"message":{"content":"legacy"}}]}))
    monkeypatch.setattr(requests,"post",post)
    assert OpenAIAdapter(api_key="fake",api_mode="chat_completions").query([{"role":"user","content":"hi"}])=="legacy"
    assert post.call_args.args[0].endswith('/chat/completions')
    assert 'max_completion_tokens' in post.call_args.kwargs['json']


def test_invalid_input_never_sends_a_request(monkeypatch):
    post=Mock(side_effect=AssertionError("must not call"))
    monkeypatch.setattr(requests,"post",post)
    adapter=OpenAIAdapter(api_key="fake")
    assert adapter.query([],max_tokens=0) is None
    assert adapter.query([{"role":"tool","content":"untrusted"}]) is None
    post.assert_not_called()
