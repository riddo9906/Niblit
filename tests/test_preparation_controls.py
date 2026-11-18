import json
from unittest.mock import patch,Mock
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from modules.freqtrade_core_claim import core_receipt
from modules.trading_session_api import register_trading_routes
from modules.cognitive_chat import admission

@pytest.mark.parametrize('url',[
    'https://example.com/api/trading/native-entry-receipt',
    'http://127.0.0.1.evil:5000/api/trading/native-entry-receipt',
    'http://user@localhost:5000/api/trading/native-entry-receipt',
    'http://localhost:5000/api/trading/native-entry-receipt?x=1',
    'http://localhost:5000/api/trading/sessions/activate',
    'http://localhost/api/trading/native-entry-receipt'])
def test_callback_rejects_nonlocal_or_wrong_route(url):
    with patch('modules.freqtrade_core_claim.build_opener') as opener:
        with pytest.raises(ValueError):core_receipt({}, {'niblit_core_callback_url':url})
        opener.assert_not_called()

def test_redirects_are_not_followed():
    with patch('modules.freqtrade_core_claim.build_opener') as opener:
        opener.return_value.open.side_effect=PermissionError('redirect denied')
        with pytest.raises(PermissionError):core_receipt({})
        handler=opener.call_args.args[1]
        with pytest.raises(PermissionError):handler.redirect_request(None,None,302,'',{},'http://evil')

def test_exact_preparation_intent():
    assert admission('Review demo execution preparation.')==('execution_rehearsal',[('recall_environment_preparation',{})])

def test_persistent_preparation_provider_cannot_reach_broker_control():
    control=Mock();app=FastAPI()
    register_trading_routes(app,lambda:control)
    app.state.niblit_native_callback=('host.docker.internal:5800','a'*48,'b'*64)
    app.state.niblit_native_provider=lambda:None
    body={'ticket':'c'*32,'symbol':'BTC/USDT:USDT','side':'long','amount':1,'rate':100,
          'stoploss':-.01,'minimal_roi':{'0':.02},'fee':.0002,'account_binding':'b'*64}
    response=TestClient(app).post('/api/trading/native-entry-receipt',
        headers={'host':'host.docker.internal:5800','x-niblit-native-token':'a'*48},json=body)
    assert response.status_code==503
    control.native_entry_receipt.assert_not_called()

@pytest.mark.parametrize('failure',['token','binding','host','origin'])
def test_native_scope_does_not_grant_operator_access(failure):
    control=Mock();app=FastAPI();token='a'*48;binding='b'*64
    register_trading_routes(app,lambda:control,native_callback=('host.docker.internal:5801',token,binding))
    client=TestClient(app)
    headers={'host':'host.docker.internal:5801','x-niblit-native-token':token}
    body={'ticket':'c'*32,'symbol':'BTC/USDT:USDT','side':'long','amount':1,'rate':100,
          'stoploss':-.01,'minimal_roi':{'0':.02},'fee':.0002,'account_binding':binding}
    if failure=='token':headers['x-niblit-native-token']='wrong'
    if failure=='binding':body['account_binding']='0'*64
    if failure=='host':headers['host']='evil:5801'
    if failure=='origin':headers['origin']='http://127.0.0.1:5183'
    assert client.post('/api/trading/native-entry-receipt',headers=headers,json=body).status_code==403
    control.native_entry_receipt.assert_not_called()
    assert client.post('/api/trading/sessions/activate',headers=headers,json={'id':'a'*32,'spec_hash':'b'*64,'acknowledgement':'ACTIVATE_BOUNDED_DEMO_SESSION'}).status_code==403
