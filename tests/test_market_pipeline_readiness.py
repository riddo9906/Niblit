
"""Acceptance CLI contracts: real rules, fixtures for unavailable external services."""
import importlib.util
import time
from pathlib import Path
from unittest.mock import Mock

import pytest

script=Path(__file__).resolve().parents[1]/'scripts/check-market-pipeline.py'
spec=importlib.util.spec_from_file_location('market_readiness_check',script)
check=importlib.util.module_from_spec(spec)
spec.loader.exec_module(check)


def fixture_desk(tmp_path):
    desk=Mock();desk.root=tmp_path
    desk.configuration.return_value={'exchange':'fixture','dry_run':True,'strategy':'Fixture',
        'timeframe':'5m','state':'stopped'}
    desk.api.return_value={'whitelist':['BTC/USDT']}
    end=int(time.time()//300)*300
    desk.market.return_value={'fresh':True,'candles':[
        dict(timestamp=end-(60-i)*300,open=100+i,high=101+i,low=99+i,close=100+i)
        for i in range(60)]}
    return desk


def analyzed(observation):
    return {'state':'analyzed_by_core','analysis':check.assess_observation(observation),
        'authorization':{'allowed':True},'memory':{'queued':True,'state':'queued_to_core'}}


def test_real_rules_and_core_readiness_never_arm_execution(tmp_path):
    desk=fixture_desk(tmp_path)
    report=check.check_market_pipeline(desk=desk,analyze=analyzed)
    assert report['ready_for_analysis'] is True
    assert report['rules']['invoked']==6
    assert report['execution_ready'] is False
    assert report['orders_sent']==0
    assert desk.api.call_args_list[0].args==('whitelist',)
    desk.preview.assert_not_called();desk.confirm.assert_not_called()


@pytest.mark.parametrize('mode',[False,None,'true'])
def test_unknown_or_live_mode_stops_before_market_or_core(tmp_path,mode):
    desk=fixture_desk(tmp_path);desk.configuration.return_value['dry_run']=mode
    core=Mock()
    report=check.check_market_pipeline(desk=desk,analyze=core)
    assert report['blocked']=='non_live_identity_unverified'
    core.assert_not_called();desk.market.assert_not_called()


@pytest.mark.parametrize('failure',['stale','partial','core_denied','memory_denied','core_offline'])
def test_partial_acceptance_is_explicit(tmp_path,failure):
    desk=fixture_desk(tmp_path)
    if failure=='stale':desk.market.return_value['fresh']=False
    if failure=='partial':desk.market.return_value['candles']=[]
    def core(observation):
        result=analyzed(observation)
        if failure=='core_denied':result['authorization']={'allowed':False}
        if failure=='memory_denied':result['memory']={'queued':False,'state':'pending'}
        if failure=='core_offline':return {'state':'pending','error_type':'ConnectError'}
        return result
    result=check.check_market_pipeline(desk=desk,analyze=core)
    assert result['ready_for_analysis'] is False
    assert result['execution_ready'] is False


def test_feed_unavailable_is_classified_without_credentials(tmp_path):
    desk=fixture_desk(tmp_path);desk.configuration.side_effect=ConnectionError('private fixture text')
    result=check.check_market_pipeline(desk=desk)
    assert result['error_type']=='ConnectionError'
    assert 'private fixture text' not in str(result)
