import pytest
from modules.market_events import MarketEvents

def feed(link='https://www.federalreserve.gov/newsevents/pressreleases/example.htm', date='Thu, 01 Jan 2026 00:00:00 GMT'):
    return f'<rss><channel><item><title>Policy statement</title><link>{link}</link><pubDate>{date}</pubDate></item></channel></rss>'.encode()

def test_published_and_available_are_distinct_no_hindsight(tmp_path):
    e=MarketEvents(tmp_path/'events.sqlite3')
    import email.utils
    published=email.utils.parsedate_to_datetime('Thu, 01 Jan 2026 00:00:00 GMT').timestamp()
    seen=published+600
    assert e.ingest(feed(),seen)==1
    assert e.ingest(feed(),seen+10)==0
    assert not e.context(published+300)
    assert e.context(seen)[0]['available_at']==seen
    assert not e.context(seen+86400)

def test_foreign_links_future_dates_and_entities_rejected(tmp_path):
    e=MarketEvents(tmp_path/'events.sqlite3')
    assert e.ingest(feed(link='http://127.0.0.1/admin'))==0
    assert e.ingest(feed(date='Thu, 01 Jan 2099 00:00:00 GMT'))==0
    with pytest.raises(ValueError): e.ingest(b'<!DOCTYPE rss><rss/>')

def test_refresh_failure_is_visible_and_throttled(tmp_path,monkeypatch):
    e=MarketEvents(tmp_path/'events.sqlite3')
    from unittest.mock import Mock
    client=Mock(side_effect=OSError('offline'))
    monkeypatch.setattr('modules.market_events.httpx.Client',client)
    assert e.refresh()['health']['state']=='unavailable'
    e.refresh()
    client.assert_called_once()
