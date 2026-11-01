"""Resume EURUSD research only; never start an order-submitting session."""
from html.parser import HTMLParser
import json
import httpx


class DeskToken(HTMLParser):
    token = None

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == 'meta' and attrs.get('name') == 'desk-token':
            self.token = attrs.get('content')


if __name__ == '__main__':
    base = 'http://127.0.0.1:8767'
    with httpx.Client(trust_env=False, timeout=25) as client:
        current = client.get(base + '/api/demo/status')
        current.raise_for_status()
        if current.json().get('running'):
            print('Existing market session preserved; no new session started.')
        else:
            page = client.get(base + '/')
            page.raise_for_status()
            parser = DeskToken()
            parser.feed(page.text)
            if not parser.token:
                raise SystemExit('Desk authentication unavailable; no action taken.')
            response = client.post(base + '/api/demo/observe',
                headers={'Origin': base, 'x-desk-token': parser.token},
                json={'symbol': 'EURUSD', 'strategy': 'auto',
                      'acknowledgement': 'START_BOUNDED_MT5_DEMO'})
            response.raise_for_status()
            print(json.dumps({'observation_requested': True,
                              'order_session_started': False}))
