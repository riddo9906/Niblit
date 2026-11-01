from unittest.mock import Mock
import pytest
from modules.local_brain import LocalBrainGateway
from modules.runtime_router_v2 import NiblitUnifiedRuntimeRouterV2


def test_native_router_delegates_to_existing_gguf_transport(monkeypatch):
    monkeypatch.setenv('NIBLIT_NATIVE_LOCAL_TRANSPORT','local_gguf')
    monkeypatch.setattr('modules.portal_model.settings',lambda:('local_gguf','private',{}))
    reply=Mock(return_value='source-grounded answer')
    monkeypatch.setattr('modules.portal_model.reply',reply)
    router=NiblitUnifiedRuntimeRouterV2(LocalBrainGateway())
    assert router.generate('question',context='reference')=='source-grounded answer'
    assert router.last_route()['backend']=='http'
    assert reply.call_args.args[0][0]['content'].startswith('Untrusted reference context')


def test_unknown_transport_or_paid_model_cannot_fall_back(monkeypatch):
    gateway=LocalBrainGateway()
    monkeypatch.setenv('NIBLIT_NATIVE_LOCAL_TRANSPORT','paid')
    with pytest.raises(ValueError):gateway.route_inference('question')
    monkeypatch.setenv('NIBLIT_NATIVE_LOCAL_TRANSPORT','cloud')
    monkeypatch.setenv('NIBLIT_NATIVE_LOCAL_MODEL','openai/gpt-6-astra')
    with pytest.raises(ValueError):gateway.route_inference('question')


def test_missing_cloud_is_an_error_not_a_fake_answer(monkeypatch):
    brain=Mock();brain.route_inference.return_value={'backend':'none','text':'','error':'CloudRuntime discovery unavailable; generation was not started'}
    with pytest.raises(RuntimeError,match='generation was not started'):
        NiblitUnifiedRuntimeRouterV2(brain).generate('question')
