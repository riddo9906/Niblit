"""Source-stamped research context, never executable instructions or sentiment.

Only an allowlisted public central-bank feed is fetched. Titles and source links
are retained; no arbitrary URL fetch, article scraping or paid inference occurs.
Publication time and local availability are separate to prevent hindsight use.
"""
from email.utils import parsedate_to_datetime
import hashlib
import json
import sqlite3
import threading
import time
from urllib.parse import urlparse
from xml.etree import ElementTree

import httpx

FED_FEED = 'https://www.federalreserve.gov/feeds/press_monetary.xml'

class MarketEvents:
    def __init__(self, path):
        self.path = str(path)
        self.lock = threading.Lock()
        self.last_attempt = 0
        self.health = {'state':'not_fetched'}
        with self.db() as db:
            db.execute('CREATE TABLE IF NOT EXISTS macro_events(id TEXT PRIMARY KEY, available REAL, published REAL, payload TEXT)')

    def db(self):
        return sqlite3.connect(self.path, timeout=10)

    def ingest(self, raw, now=None):
        now = time.time() if now is None else now
        if len(raw)>1_000_000 or b'<!DOCTYPE' in raw.upper() or b'<!ENTITY' in raw.upper():
            raise ValueError('Unsupported feed document')
        root = ElementTree.fromstring(raw)
        count=0
        with self.db() as db:
            for item in root.findall('./channel/item')[:30]:
                title=(item.findtext('title') or '').strip()[:300]
                url=(item.findtext('link') or '').strip()
                if urlparse(url).scheme!='https' or urlparse(url).hostname!='www.federalreserve.gov':
                    continue
                try:
                    date=parsedate_to_datetime(item.findtext('pubDate') or '')
                    if date.tzinfo is None: continue
                    published=date.timestamp()
                except (ValueError,TypeError,OverflowError): continue
                if not title or published>now: continue
                identity=hashlib.sha256((url+title+str(published)).encode()).hexdigest()
                body={'id':identity,'title':title,'url':url,'publisher':'Federal Reserve Board',
                      'published_at':published,'available_at':now,'category':'monetary_policy',
                      'interpretation':'Research context only; no direction inferred from headline.'}
                cursor=db.execute('INSERT OR IGNORE INTO macro_events VALUES(?,?,?,?)',
                                  (identity,now,published,json.dumps(body)))
                count+=cursor.rowcount
        return count

    def refresh(self):
        with self.lock:
            if time.time()-self.last_attempt<600:
                return self.snapshot()
            self.last_attempt=time.time()
            try:
                raw=bytearray()
                with httpx.Client(trust_env=False,timeout=8,follow_redirects=False) as client:
                    with client.stream('GET',FED_FEED) as response:
                        response.raise_for_status()
                        for chunk in response.iter_bytes():
                            raw.extend(chunk)
                            if len(raw)>1_000_000: raise ValueError('Feed too large')
                count=self.ingest(bytes(raw))
                self.health={'state':'fetched','checked_at':time.time(),'new_items':count,'source':FED_FEED}
            except Exception as exc:
                self.health={'state':'unavailable','checked_at':time.time(),'error':type(exc).__name__,'source':FED_FEED}
            return self.snapshot()

    def context(self, at=None):
        at=time.time() if at is None else at
        with self.db() as db:
            return [json.loads(r[0]) for r in db.execute(
                'SELECT payload FROM macro_events WHERE available<=? AND published<=? AND published>=? ORDER BY published DESC LIMIT 5',
                (at,at,at-86400))]

    def snapshot(self):
        with self.db() as db:
            events=[json.loads(r[0]) for r in db.execute('SELECT payload FROM macro_events ORDER BY published DESC LIMIT 15')]
        return {'health':self.health,'events':events,'scope':'US monetary policy only; politics/war coverage is not connected.'}
