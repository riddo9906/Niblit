import json
import time
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient
from modules.trading_desk import Desk, Intent, create_app


@pytest.fixture
def desk(tmp_path):
    config = dict(dry_run=True,state='running',exchange='test',strategy='Test',timeframe='5m',
                  force_entry_enable=True,max_open_trades=3)
    def api(path,payload):
        if path=='show_config': return dict(config)
        if path=='whitelist': return {'whitelist':['BTC/USDT']}
        if path=='status': return []
        if path.startswith('pair_candles?'):
            return {'timeframe_ms':300000,'columns':['__date_ts','close','enter_long'],
                    'data':[[(time.time()-310)*1000,100,1],[(time.time()-10)*1000,110,1]]}
        if path=='forceenter': return {'trade_id':12,'pair':payload['pair']}
        return {}
    d=Desk(tmp_path,Mock(side_effect=api))
    d.minimum_stake=Mock(return_value=5)
    d.test_config=config
    return d


def test_completed_candles_only(desk):
    market=desk.market('BTC/USDT')
    assert len(market['candles'])==1
    assert market['last']['close']==100 and market['fresh']


def test_live_mode_is_read_only(desk):
    desk.test_config['dry_run']=False
    with pytest.raises(ValueError,match='Funded'):
        desk.preview(Intent(action='enter_long',pair='BTC/USDT'))
    assert not any(call.args[0]=='forceenter' for call in desk.transport.call_args_list)


def test_repeated_confirmation_does_not_repeat_order(desk):
    ticket=desk.preview(Intent(action='enter_long',pair='BTC/USDT'))['ticket']
    assert desk.confirm(ticket)['state']=='submitted'
    assert desk.confirm(ticket)['state']=='submitted'
    assert sum(c.args[0]=='forceenter' for c in desk.transport.call_args_list)==1


def test_unresolved_delivery_blocks_new_ticket(desk):
    ticket=desk.preview(Intent(action='enter_long',pair='BTC/USDT'))['ticket']
    second=desk.preview(Intent(action='enter_long',pair='BTC/USDT'))['ticket']
    with desk.db() as db: db.execute("UPDATE tickets SET state='unknown' WHERE id=?",(ticket,))
    with pytest.raises(ValueError,match='unresolved'):
        desk.preview(Intent(action='enter_long',pair='BTC/USDT'))
    with pytest.raises(ValueError,match='unresolved'):
        desk.confirm(second)


def test_reconciliation_requires_matching_engine_evidence(desk):
    key=desk.preview(Intent(action='enter_long',pair='BTC/USDT'))['ticket']
    with desk.db() as db: db.execute("UPDATE tickets SET state='unknown' WHERE id=?",(key,))
    previous=desk.transport.side_effect
    def api(path,payload):
        if path=='trades?limit=100': return {'trades':[{'trade_id':9,'pair':'BTC/USDT','enter_tag':'niblit_'+key[:12],'is_open':True}]}
        return previous(path,payload)
    desk.transport.side_effect=api
    assert desk.reconcile()['resolved']==1
    assert desk.confirm(key)['state']=='reconciled'
    assert not any(c.args[0]=='forceenter' for c in desk.transport.call_args_list)


def test_uncertain_delivery_never_retries(desk):
    ticket=desk.preview(Intent(action='enter_long',pair='BTC/USDT'))['ticket']
    previous=desk.transport.side_effect
    def ambiguous(path,payload):
        if path=='forceenter': raise TimeoutError()
        return previous(path,payload)
    desk.transport.side_effect=ambiguous
    assert desk.confirm(ticket)['state']=='unknown'
    assert desk.confirm(ticket)['state']=='unknown'
    assert sum(c.args[0]=='forceenter' for c in desk.transport.call_args_list)==1


def test_mode_change_between_review_and_send_blocks(desk):
    ticket=desk.preview(Intent(action='enter_long',pair='BTC/USDT'))['ticket']
    desk.test_config['dry_run']=False
    with pytest.raises(ValueError,match='changed'): desk.confirm(ticket)


def test_stale_data_and_mismatched_exit_block(desk):
    desk.market=Mock(return_value={'fresh':False})
    with pytest.raises(ValueError,match='stale'): desk.preview(Intent(action='enter_long',pair='BTC/USDT'))
    with pytest.raises(ValueError,match='identity'): desk.preview(Intent(action='exit',pair='BTC/USDT',trade_id=4))


def test_below_exchange_minimum_does_not_send(desk):
    desk.minimum_stake.return_value=85
    with pytest.raises(ValueError,match='minimum'):
        desk.preview(Intent(action='enter_long',pair='BTC/USDT',stake=20))
    assert not any(c.args[0]=='forceenter' for c in desk.transport.call_args_list)


def test_definite_engine_rejection_is_not_unknown(desk):
    from modules.trading_desk import FreqtradeRejection
    key=desk.preview(Intent(action='enter_long',pair='BTC/USDT'))['ticket']
    previous=desk.transport.side_effect
    def reject(path,payload):
        if path=='forceenter': raise FreqtradeRejection('Entry rejected by engine')
        return previous(path,payload)
    desk.transport.side_effect=reject
    assert desk.confirm(key)['state']=='rejected'
    assert desk.confirm(key)['state']=='rejected'
    assert sum(c.args[0]=='forceenter' for c in desk.transport.call_args_list)==1


def test_binance_minimum_uses_quantity_cost_and_reserve(tmp_path):
    import time
    from modules.trading_desk import Desk
    d=Desk(tmp_path)
    d.market_rules=(time.monotonic(),{'BTCUSDT':{'filters':[
        {'filterType':'LOT_SIZE','minQty':'0.001'},
        {'filterType':'MIN_NOTIONAL','notional':'5'}]}})
    assert d.minimum_stake('BTC/USDT:USDT',{'exchange':'binance','trading_mode':'futures'},81000)==85.05


def test_expired_and_inflight_ticket_are_not_sent(desk):
    key=desk.preview(Intent(action='enter_long',pair='BTC/USDT'))['ticket']
    with desk.db() as db: db.execute('UPDATE tickets SET created=0 WHERE id=?',(key,))
    with pytest.raises(ValueError,match='expired'): desk.confirm(key)
    with desk.db() as db: db.execute("UPDATE tickets SET state='sending' WHERE id=?",(key,))
    assert desk.confirm(key)['state']=='sending'
    assert not any(c.args[0]=='forceenter' for c in desk.transport.call_args_list)


def test_origin_host_and_token_required(desk):
    client=TestClient(create_app(desk))
    body={'action':'enter_long','pair':'BTC/USDT'}
    assert client.post('/api/preview',json=body).status_code==403
    assert client.get('/',headers={'host':'evil.test'}).status_code==400
    html=client.get('/').text
    token=html.split('name="desk-token" content="')[1].split('"')[0]
    assert client.post('/api/preview',json=body,headers={'origin':'http://127.0.0.1:8767','x-desk-token':token}).status_code==200
