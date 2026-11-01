"""Read-only checks before starting the bounded native learning profile.

Keep checks separate from startup: readiness must never boot Core, load a model,
reserve a task, write memory, or submit an order.
"""
from pathlib import Path

import httpx


def check_readiness(values, root, *, transport=None):
    checks = []

    def record(name, passed, detail):
        checks.append({'name': name, 'passed': bool(passed), 'detail': detail})

    required = {
        'NIBLIT_SHARED_ADMISSION': '1',
        'NIBLIT_ALE_LOCAL_SAFE': '1',
        'NIBLIT_NATIVE_LOCAL_TRANSPORT': 'local_gguf',
        'NIBLIT_PORTAL_MODEL_BACKEND': 'local_gguf',
    }
    for name, expected in required.items():
        record(name, values.get(name) == expected, 'Required: ' + expected)
    # Only contact the fixed desktop services; never follow configured remote URLs.
    record('private_endpoints',
           values.get('NIBLIT_ADMISSION_URL') == 'http://127.0.0.1:8772'
           and values.get('NIBLIT_PORTAL_GGUF_URL') == 'http://127.0.0.1:8766',
           'Desktop gateway 8772 and local model 8766 required')
    if not all(item['passed'] for item in checks):
        return {'ready': False, 'checks': checks, 'inference_started': False}

    key_path = Path(values.get('NIBLIT_PORTAL_GGUF_KEY_FILE') or
                    'runtime/client-portal/gguf-api-key')
    if not key_path.is_absolute():
        key_path = Path(root) / key_path
    try:
        key = key_path.read_text().strip()
        if len(key) < 32:
            raise ValueError('Invalid local key')
    except (OSError, ValueError):
        record('local_authentication', False, 'Private local key unavailable')
        return {'ready': False, 'checks': checks, 'inference_started': False}

    with httpx.Client(timeout=5, trust_env=False, follow_redirects=False,
                      transport=transport) as client:
        headers = {'Authorization': 'Bearer ' + key}
        try:
            response = client.get('http://127.0.0.1:8766/slots', headers=headers)
            response.raise_for_status()
            slots = response.json()
            idle = (isinstance(slots, list) and len(slots) == 1
                    and isinstance(slots[0], dict)
                    and slots[0].get('is_processing') is False)
            record('single_model_slot_idle', idle, 'One idle local model slot required')
        except (httpx.HTTPError, ValueError):
            record('single_model_slot_idle', False, 'Local model status unavailable')
        try:
            response = client.post('http://127.0.0.1:8772/api/local-tutor/task/status',
                                   headers=headers, json={})
            response.raise_for_status()
            status = response.json()
            record('shared_authority_idle', isinstance(status, dict)
                   and status.get('state') == 'idle',
                   'Existing memory gateway must report an idle task authority')
        except (httpx.HTTPError, ValueError):
            record('shared_authority_idle', False, 'Memory gateway status unavailable')
    return {'ready': all(item['passed'] for item in checks), 'checks': checks,
            'inference_started': False,
            'scope': 'Point-in-time dependencies only; full Core boot is not verified'}
