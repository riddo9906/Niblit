"""Exact model routing for the desktop UI without disturbing default 3B."""
import asyncio
from modules import local_large_inference as bridge


def test_large_coder_uses_isolated_cloud_and_other_models_keep_existing(monkeypatch):
    class FakeBrain:
        def __init__(self,base_url=None,timeout=None):
            self.base_url=base_url;self.timeout=timeout
    sentinel=object()
    monkeypatch.setattr(bridge,'NiblitCloudBrain',FakeBrain)
    monkeypatch.setattr(bridge,'get_niblit_cloud_brain',lambda:sentinel)
    assert bridge.selected_cloud_brain('qwen2.5-coder-3b') is sentinel
    assert bridge.selected_cloud_brain('llama3.2-1b') is sentinel
    p=bridge.selected_cloud_brain(bridge.LARGE_MODEL_ID)
    assert p.base_url=='http://127.0.0.1:8212'
    assert p.timeout==240


def test_desktop_14b_advertised_only_if_real_cloud_lists_exact_model(monkeypatch):
    class FakeBrain:
        def __init__(self,base_url=None,timeout=None):
            assert base_url=='http://127.0.0.1:8212' and timeout==3
        async def list_models(self):
            return {'data':[{'id':'qwen2.5-coder-3b'},{'id':'qwen2.5-coder-14b'}]}
    monkeypatch.setattr(bridge,'NiblitCloudBrain',FakeBrain)
    assert asyncio.run(bridge.additional_local_models())==[{'id':'qwen2.5-coder-14b','object':'model'}]


def test_unavailable_cloud_does_not_invent_14b(monkeypatch):
    class FakeBrain:
        def __init__(self,*args,**kwargs):pass
        async def list_models(self):
            raise RuntimeError('unavailable')
    monkeypatch.setattr(bridge,'NiblitCloudBrain',FakeBrain)
    assert asyncio.run(bridge.additional_local_models())==[]
