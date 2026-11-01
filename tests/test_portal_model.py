from unittest.mock import Mock
import pytest
from modules.portal_model import settings,readiness,reply
from modules.portal_model import runtime_facts,factual_reply
from datetime import datetime,timezone


def test_identity_and_clock_are_runtime_facts_not_model_guesses():
    facts=runtime_facts('local_gguf',datetime(2026,10,30,18,0,0,tzinfo=timezone.utc))
    assert '20:00:00 SAST' in facts['clock']
    assert 'Qwen 2.5 Coder 3B' in factual_reply('which ai language model are you\n',facts)
    assert 'not OpenAI GPT-4' in factual_reply('who are you?',facts)
    assert '20:00:00 SAST' in factual_reply('what is the time\n',facts)
    assert factual_reply('Write a Python function that returns the current time',facts) is None


def test_paid_urls_and_unknown_backends_never_fall_back(monkeypatch):
    monkeypatch.setenv('NIBLIT_PORTAL_MODEL_BACKEND','local_gguf')
    monkeypatch.setenv('NIBLIT_PORTAL_GGUF_URL','https://api.openai.com/v1')
    with pytest.raises(ValueError): settings()
    assert readiness()['ready'] is False
    monkeypatch.setenv('NIBLIT_PORTAL_MODEL_BACKEND','paid')
    with pytest.raises(ValueError): settings()


def test_gguf_auth_context_and_generation_limit(monkeypatch,tmp_path):
    key=tmp_path/'local-key';key.write_text('local-test-key-value-not-a-real-secret-12345')
    monkeypatch.setenv('NIBLIT_PORTAL_MODEL_BACKEND','local_gguf')
    monkeypatch.setenv('NIBLIT_PORTAL_GGUF_KEY_FILE',str(key))
    client=Mock();client.post.return_value.json.return_value={'choices':[{'message':{'content':'4'}}]}
    factory=Mock();factory.return_value.__enter__=Mock(return_value=client);factory.return_value.__exit__=Mock(return_value=False)
    monkeypatch.setattr('modules.portal_model.httpx.Client',factory)
    history=[{'role':'user','content':'x'*8000} for _ in range(12)]
    assert reply(history,'2+2')=='4'
    call=client.post.call_args
    assert call.args[0]=='http://127.0.0.1:8766/v1/chat/completions'
    assert call.kwargs['headers']['Authorization'].startswith('Bearer ')
    assert call.kwargs['json']['max_tokens']==256
    assert sum(len(m['content']) for m in call.kwargs['json']['messages'])<10000
