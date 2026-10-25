import json
import pytest
from modules.paper_trading import PaperTradingController, PaperTradingError
import httpx

@pytest.mark.parametrize('path,payload,expected', [('/health',None,2),('/v1/replay/step',{},2),('/v1/decisions/execute',{},1)])
def test_transport_retry_is_limited_to_safe_recoverable_requests(path,payload,expected):
    controller=PaperTradingController(); calls=[]
    def transport(request):
        calls.append(request)
        if len(calls)==1: raise httpx.ReadError('connection reset',request=request)
        return httpx.Response(200,json={'healthy':True})
    client=httpx.Client(base_url='http://127.0.0.1:8100',transport=httpx.MockTransport(transport))
    controller._clients['http://127.0.0.1:8100']=client
    try:
        if expected==1:
            with pytest.raises(PaperTradingError,match='connection reset'): controller._call('runtime',path,payload)
        else: assert controller._call('runtime',path,payload)=={'healthy':True}
        assert len(calls)==expected
    finally: client.close()

def test_external_backend_cannot_reach_operator_execution(monkeypatch):
    controller=PaperTradingController(); calls=[]
    def backend(service,path,payload=None,timeout=10):
        calls.append(path);return {'healthy':True,'backend':'freqtrade','mode':'paper'}
    monkeypatch.setattr(controller,'_call',backend)
    with pytest.raises(PaperTradingError) as error: controller.decision('enter_long',100)
    assert error.value.status==403 and calls==['/health']

def test_observe_blocks_before_fetching_strategy_or_executing(monkeypatch):
    controller=PaperTradingController(); calls=[]
    def backend(service,path,payload=None,timeout=10):
        calls.append(path);return {'healthy':True,'backend':'paper','mode':'observe'}
    monkeypatch.setattr(controller,'_call',backend)
    with pytest.raises(PaperTradingError) as error: controller.step()
    assert error.value.status==409 and calls==['/health']

def test_recovered_execution_is_acknowledged_without_resubmission(monkeypatch):
    controller=PaperTradingController(); calls=[]
    observation={'observation_id':'hash:strategy:200','source':'historical_replay','symbol':'BTC/USDT','enter_long':True,'exit_long':False,'cursor':200,'candles':[]}
    def backend(service,path,payload=None,timeout=10):
        calls.append(path)
        if path=='/health':return {'healthy':True,'backend':'paper','mode':'paper'}
        if path=='/v1/replay/step':return observation
        if path.startswith('/v1/executions/'):return {'action':'enter_long','status':'confirmed_open'}
        if path=='/v1/paper/account':return {'account':{'positions':[{'status':'open','symbol':'BTC/USDT','stake_amount':100}]}}
        if path=='/v1/replay/ack':return {'acknowledged':True}
        raise AssertionError(path)
    monkeypatch.setattr(controller,'_call',backend)
    result=controller.step()
    assert result['outcome']['recovered'] is True
    assert '/v1/decisions/execute' not in calls and '/v1/replay/ack' in calls

def test_string_approval_from_model_is_not_treated_as_permission(monkeypatch):
    import modules.paper_trading as gateway
    class Response:
        def __enter__(self):return self
        def __exit__(self,*args):pass
        def read(self):return json.dumps({'choices':[{'message':{'content':'{"approved":"true"}'}}]}).encode()
    monkeypatch.setattr(gateway,'urlopen',lambda *args,**kwargs:Response())
    with pytest.raises(PaperTradingError) as error:
        PaperTradingController().advice({'symbol':'BTC/USDT','as_of':'2026-01-01','candles':[]},'enter_long')
    assert error.value.status==503
