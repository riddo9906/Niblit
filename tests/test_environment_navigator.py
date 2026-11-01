import threading
import time

import pytest

from modules.environment_navigator import ToolRuns, validate


def arguments(kind='workspace', target='.'):
    return {'environment_type': kind, 'action': 'explore', 'environment_details':
        {'name': 'test', 'url': target, 'additional_context': 'Inspect, do not execute', 'object_id': ''}}


def test_workspace_scope_and_evidence(tmp_path, monkeypatch):
    monkeypatch.setenv('NIBLIT_WORKSPACE_ROOT', str(tmp_path))
    (tmp_path / 'sample.py').write_text('print(1)')
    ledger = ToolRuns()
    run = ledger.start(arguments(), background=False)
    assert run['status'] == 'completed'
    assert run['result']['mode'] == 'workspace_inspection'
    assert not run['result']['navigation_performed']
    assert [e['kind'] for e in run['events']] == ['purpose', 'action.started', 'action.result', 'finished']
    escaped = ledger.start(arguments(target='../outside'), background=False)
    assert escaped['status'] == 'failed'
    secret = arguments(target='.env')
    secret['environment_details']['object_id'] = 'file'
    assert ledger.start(secret, background=False)['status'] == 'failed'


@pytest.mark.parametrize('url', ['file:///C:/secret', 'http://user:pass@example.com', 'https://example.com?key=secret'])
def test_reject_sensitive_urls(url):
    with pytest.raises(ValueError):
        validate(arguments('website', url))


def test_strict_details_and_unsupported_control():
    args = arguments()
    args['environment_details']['shell'] = 'whoami'
    with pytest.raises(ValueError): validate(args)
    run = ToolRuns().start(arguments('application'), background=False)
    assert run['status'] == 'failed'
    assert run['result']['mode'] == 'unsupported'


def test_live_guidance_and_cooperative_stop(monkeypatch):
    import modules.governed_research as research
    entered, release = threading.Event(), threading.Event()
    def fetch(*args, **kwargs):
        entered.set()
        assert release.wait(3)
        return {'evidence': {'extracted_text': 'observed'}}
    monkeypatch.setattr(research, 'governed_fetch', fetch)
    ledger = ToolRuns()
    run = ledger.start(arguments('website', 'https://example.com'))
    assert entered.wait(2)
    ledger.control(run['id'], 'guidance', 'Check freshness')
    stopped = ledger.control(run['id'], 'stop')
    assert stopped['status'] == 'stopping'
    release.set()
    for _ in range(100):
        run = ledger.get(run['id'])
        if run['status'] == 'stopped': break
        time.sleep(.01)
    assert run['status'] == 'stopped'
    assert any(e['kind'] == 'operator.guidance' for e in run['events'])
    assert any(e['kind'] == 'action.result' for e in run['events'])


def test_redirects_revalidate_destination(monkeypatch):
    from modules.governed_research import _PublicRedirects
    import urllib.error
    import modules.governed_research as research
    monkeypatch.setattr(research, '_url_allowed', lambda url: (False, 'private'))
    with pytest.raises(urllib.error.URLError):
        _PublicRedirects().redirect_request(None, None, 302, '', {}, 'http://127.0.0.1/')
