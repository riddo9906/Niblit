import math
from types import SimpleNamespace
from unittest.mock import Mock
import pytest
from modules.freqtrade_research import FreqtradeResearch


def test_freqtrade_uses_shared_rules_and_never_posts_orders(tmp_path):
    desk=Mock();desk.path=tmp_path/'orders.sqlite3'
    desk.configuration.return_value={'strategy':'SampleStrategy','dry_run':True,'exchange':'test','state':'running'}
    desk.api.return_value={'whitelist':['BTC/USDT']}
    rows=[dict(timestamp=(i+1)*300,open=100+math.sin(i)*.01,close=100+math.sin(i)*.01,high=101,low=99) for i in range(160)]
    desk.market.return_value={'fresh':True,'candles':rows}
    lab=FreqtradeResearch(desk)
    result=lab.snapshot('BTC/USDT')
    assert len(result['manager']['candidates'])==6
    assert result['research']['execution_eligible'] is False
    assert result['native_engine_strategy']=='SampleStrategy'
    assert result['execution_active'] is False
    assert all(call.args==('whitelist',) for call in desk.api.call_args_list)
    rows.append(dict(timestamp=48300,open=100,close=100.01,high=101,low=99))
    result=lab.snapshot('BTC/USDT')
    assert len(result['forecast_outcomes'])==1
    assert result['forecast_outcomes'][0]['target_bar']==48300
    assert len(lab.snapshot('BTC/USDT')['forecast_outcomes'])==1
    with pytest.raises(ValueError): lab.snapshot('OTHER/PAIR')
