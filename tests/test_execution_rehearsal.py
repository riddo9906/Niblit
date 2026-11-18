import time
import pytest
from modules.trading_session_selftest import fixture,freq_fixture,fixture_costs
from modules.cognitive_chat import admission


@pytest.mark.parametrize('platform,factory,symbol',[('mt5',fixture,'EURUSD'),('freqtrade',freq_fixture,'BTC/USDT:USDT')])
@pytest.mark.parametrize('fault',['missing','wrong_account','wrong_currency','expired','understated','over_budget'])
def test_entry_cost_admission_is_account_bound_and_fails_before_intercepted_send(tmp_path,platform,factory,symbol,fault):
    f=factory(tmp_path);adapter=f.service.adapters[platform]
    def model(snapshot,prepared):
        value=fixture_costs(snapshot,prepared)
        if fault=='wrong_account':value['binding']['account']='other'
        if fault=='wrong_currency':value['currency']='other'
        if fault=='expired':value['expires']=time.time()-1
        if fault=='understated':value['modeled_loss']=prepared['risk']/2
        if fault=='over_budget':value['modeled_loss']=1000
        return value
    adapter.cost_model=None if fault=='missing' else model
    p=f.service.propose(platform,symbol,60);f.service.activate(p['id'],p['spec_hash'],threaded=False)
    f.bot.step()
    assert not f.api.sent
    assert f.bot.error


def test_rehearsal_admission_does_not_accept_external_execution_suffix():
    assert admission('Run the governed execution rehearsal.')[1]==[('run_execution_rehearsal',{})]
    assert admission('Explain the latest execution rehearsal.')[1]==[('recall_execution_rehearsal',{})]
    assert admission('Run the governed execution rehearsal and send a demo order')[1]==[]
