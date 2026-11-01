import httpx
from modules.native_runtime_readiness import check_readiness


def profile(tmp_path):
    (tmp_path / 'key').write_text('private-test-key-' * 3)
    return {
        'NIBLIT_SHARED_ADMISSION': '1', 'NIBLIT_ALE_LOCAL_SAFE': '1',
        'NIBLIT_NATIVE_LOCAL_TRANSPORT': 'local_gguf',
        'NIBLIT_PORTAL_MODEL_BACKEND': 'local_gguf',
        'NIBLIT_ADMISSION_URL': 'http://127.0.0.1:8772',
        'NIBLIT_PORTAL_GGUF_URL': 'http://127.0.0.1:8766',
        'NIBLIT_PORTAL_GGUF_KEY_FILE': 'key',
    }


def test_readiness_never_generates_or_acquires(tmp_path):
    calls = []
    def handle(request):
        calls.append((request.method, request.url.path))
        payload = [{'is_processing': False}] if request.url.path == '/slots' else {'state': 'idle'}
        return httpx.Response(200, json=payload)
    report = check_readiness(profile(tmp_path), tmp_path, transport=httpx.MockTransport(handle))
    assert report['ready'] and not report['inference_started']
    assert calls == [('GET', '/slots'), ('POST', '/api/local-tutor/task/status')]
    assert 'private-test-key' not in str(report)


def test_invalid_profile_does_not_contact_services(tmp_path):
    values = profile(tmp_path)
    values['NIBLIT_ADMISSION_URL'] = 'https://remote.example'
    def handle(request):
        raise AssertionError('Unsafe profile must not contact any service')
    assert not check_readiness(values, tmp_path, transport=httpx.MockTransport(handle))['ready']


def test_busy_or_quarantined_is_not_ready(tmp_path):
    def handle(request):
        return httpx.Response(200, json=([{'is_processing': True}]
            if request.url.path == '/slots' else {'state': 'quarantined'}))
    assert not check_readiness(profile(tmp_path), tmp_path, transport=httpx.MockTransport(handle))['ready']


def test_auth_failure_hides_response_and_secrets(tmp_path):
    def handle(request):
        return httpx.Response(401, text='private-test-key- do not expose')
    report = check_readiness(profile(tmp_path), tmp_path, transport=httpx.MockTransport(handle))
    assert not report['ready'] and 'private-test-key' not in str(report)
