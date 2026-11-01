from concurrent.futures import ThreadPoolExecutor
from unittest.mock import Mock

import pytest
import requests

from modules.openai_budget import OpenAIBudget, BudgetError


def test_reservations_are_atomic_and_reported_usage_releases_unused_budget(tmp_path, monkeypatch):
    monkeypatch.setenv('OPENAI_LOCAL_BUDGET_USD', '.10')
    budget = OpenAIBudget(tmp_path / 'usage.sqlite')
    def reserve(_):
        try: return budget.reserve('gpt-6-astra', [{'content':'hello'}], 512)[0]
        except BudgetError: return None
    with ThreadPoolExecutor(max_workers=6) as pool:
        reservations = [item for item in pool.map(reserve, range(12)) if item]
    assert len(reservations) == 1
    assert budget.status()['reserved_usd'] <= .10
    budget.settle(reservations[0], {'input_tokens':100, 'output_tokens':100})
    assert budget.status()['charged_or_estimated_usd'] == pytest.approx(.006)
    assert budget.reserve('gpt-6-astra', [{'content':'hello'}], 512)


def test_unknown_outcomes_stay_reserved_as_estimated_spend(tmp_path):
    budget = OpenAIBudget(tmp_path / 'usage.sqlite')
    reservation, preview = budget.reserve('gpt-6-astra', [{'content':'hello'}], 800)
    budget.settle(reservation, uncertain=True)
    assert budget.status()['charged_or_estimated_usd'] == preview['maximum_estimated_usd']


def test_oversized_unknown_model_and_invalid_limits_block_before_network(tmp_path, monkeypatch):
    from modules.openai_adapter import OpenAIAdapter
    monkeypatch.setenv('NIBLIT_OPENAI_USAGE_DB', str(tmp_path / 'usage.sqlite'))
    monkeypatch.setenv('OPENAI_BUDGET_ENFORCE', '1')
    post = Mock(side_effect=AssertionError('A blocked request reached the provider'))
    monkeypatch.setattr(requests, 'post', post)
    for model, content in [('unpriced-model','hello'), ('gpt-6-astra', 'x'*17000)]:
        adapter = OpenAIAdapter(api_key='fake', model=model)
        assert adapter.complete([{'role':'user','content':content}]) is None
        assert adapter.last_error['code'] == 'budget_blocked'
    monkeypatch.setenv('OPENAI_LOCAL_BUDGET_USD', 'nan')
    with pytest.raises(BudgetError): OpenAIBudget(tmp_path / 'usage.sqlite').status()
    post.assert_not_called()


def test_incomplete_paid_response_still_records_usage_and_caps_output(tmp_path, monkeypatch):
    from modules.openai_adapter import OpenAIAdapter
    path = tmp_path / 'usage.sqlite'
    monkeypatch.setenv('NIBLIT_OPENAI_USAGE_DB', str(path))
    monkeypatch.setenv('OPENAI_BUDGET_ENFORCE', '1')
    response = Mock(status_code=200, headers={})
    response.json.return_value = {'status':'incomplete','usage':{'input_tokens':100,'output_tokens':800},'output':[]}
    post = Mock(return_value=response)
    monkeypatch.setattr(requests, 'post', post)
    adapter = OpenAIAdapter(api_key='fake', model='gpt-6-astra')
    assert adapter.complete([{'role':'user','content':'hello'}], max_tokens=2000) is None
    assert post.call_args.kwargs['json']['max_output_tokens'] == 800
    assert OpenAIBudget(path).status()['charged_or_estimated_usd'] == pytest.approx(.041)
