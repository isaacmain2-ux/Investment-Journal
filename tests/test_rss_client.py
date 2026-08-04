"""Tests for src/extract/rss_client.py - the network call is mocked, so these
run entirely offline and never touch ft.com."""
import pathlib
from datetime import datetime, timezone

import pytest
import requests

from src.extract import rss_client
from src.extract.rss_client import fetch_feed, _parse_datetime, _item_id, _parse_feed

FIX = pathlib.Path(__file__).parent / "fixtures" / "sample_feed.xml"

ATOM = b"""<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <title>Atom sample</title>
  <entry>
    <title>An Atom entry</title>
    <link rel="alternate" href="https://example.com/atom/one"/>
    <id>atom-0001</id>
    <summary>A short summary.</summary>
    <published>2026-01-07T09:58:19Z</published>
  </entry>
</feed>"""


class _Resp:
    """A minimal stand-in for requests.Response."""
    def __init__(self, status_code, content=b"", headers=None):
        self.status_code = status_code
        self.content = content if isinstance(content, bytes) else content.encode("utf-8")
        self.headers = headers or {}


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch):
    """Make throttle/backoff instant so the suite stays fast."""
    monkeypatch.setattr(rss_client.time, "sleep", lambda *_: None)
    rss_client._last_call[0] = 0.0


def _mock_get(monkeypatch, resp=None, exc=None, capture=None):
    def fake(url, etag=None, last_modified=None, user_agent=rss_client.DEFAULT_UA):
        if capture is not None:
            capture.update(url=url, etag=etag, last_modified=last_modified, user_agent=user_agent)
        if exc is not None:
            raise exc
        return resp
    monkeypatch.setattr(rss_client, "_http_get", fake)


# ---------------------------------------------------------------- parsing
def test_parse_rss_fixture(monkeypatch):
    body = FIX.read_bytes()
    _mock_get(monkeypatch, _Resp(200, body, {"ETag": "abc123"}))
    r = fetch_feed("sample", "https://example.com/rss")
    assert r.status == "ok"
    assert r.n_items == 3
    assert r.etag == "abc123"

    first = r.items[0]
    assert first["title"] == "Markets rally as rates hold steady"
    assert first["item_id"] == "story-0001"          # guid used directly
    assert first["link"] == "https://example.com/story/markets-rally"
    assert first["published_at"] == datetime(2026, 1, 7, 8, 30, tzinfo=timezone.utc)


def test_html_entities_decoded(monkeypatch):
    _mock_get(monkeypatch, _Resp(200, FIX.read_bytes()))
    r = fetch_feed("sample", "url")
    second = r.items[1]
    assert second["title"] == 'Bonds & the dollar: a "wait and see" mood'   # &amp; &quot; decoded
    assert "&" in second["summary"] and "&amp;" not in second["summary"]


def test_guid_fallback_and_missing_date(monkeypatch):
    _mock_get(monkeypatch, _Resp(200, FIX.read_bytes()))
    r = fetch_feed("sample", "url")
    third = r.items[2]
    assert third["published_at"] is None             # no pubDate -> None, not a crash
    assert third["guid"] is None
    assert third["item_id"].startswith("link:")       # falls back to a hash of the link


def test_atom_parse(monkeypatch):
    _mock_get(monkeypatch, _Resp(200, ATOM))
    r = fetch_feed("atom", "url")
    assert r.status == "ok" and r.n_items == 1
    it = r.items[0]
    assert it["item_id"] == "atom-0001"
    assert it["link"] == "https://example.com/atom/one"
    assert it["published_at"] == datetime(2026, 1, 7, 9, 58, 19, tzinfo=timezone.utc)


# ---------------------------------------------------------------- HTTP behaviour
def test_not_modified(monkeypatch):
    _mock_get(monkeypatch, _Resp(304))
    r = fetch_feed("sample", "url", etag="abc123", last_modified="Wed, 07 Jan 2026 00:00:00 GMT")
    assert r.status == "not_modified"
    assert r.n_items == 0
    assert r.etag == "abc123"                         # cache preserved for next time


def test_conditional_headers_sent(monkeypatch):
    cap = {}
    _mock_get(monkeypatch, _Resp(304), capture=cap)
    fetch_feed("sample", "https://example.com/rss", etag="E1", last_modified="LM1")
    assert cap["etag"] == "E1" and cap["last_modified"] == "LM1"


def test_empty_feed(monkeypatch):
    empty = b'<?xml version="1.0"?><rss version="2.0"><channel><title>x</title></channel></rss>'
    _mock_get(monkeypatch, _Resp(200, empty))
    r = fetch_feed("sample", "url")
    assert r.status == "empty" and r.n_items == 0


def test_malformed_xml_is_error_not_raise(monkeypatch):
    _mock_get(monkeypatch, _Resp(200, b"this is not xml <<<"))
    r = fetch_feed("sample", "url")
    assert r.status == "error" and "parse" in (r.error or "").lower()


def test_http_500_retries_then_errors(monkeypatch):
    _mock_get(monkeypatch, _Resp(500))
    r = fetch_feed("sample", "url", retries=3)
    assert r.status == "error" and r.http_status == 500


def test_network_exception_is_caught(monkeypatch):
    _mock_get(monkeypatch, exc=requests.RequestException("boom"))
    r = fetch_feed("sample", "url", retries=2)
    assert r.status == "error" and "network" in r.error


# ---------------------------------------------------------------- helpers
def test_parse_datetime_formats():
    assert _parse_datetime("Wed, 07 Jan 2026 09:58:19 GMT") == datetime(2026, 1, 7, 9, 58, 19, tzinfo=timezone.utc)
    assert _parse_datetime("2026-01-07T09:58:19Z") == datetime(2026, 1, 7, 9, 58, 19, tzinfo=timezone.utc)
    assert _parse_datetime(None) is None
    assert _parse_datetime("not a date") is None


def test_item_id_prefers_guid():
    assert _item_id("guid-1", "https://x/y") == "guid-1"
    assert _item_id(None, "https://x/y").startswith("link:")
    assert _item_id(None, "https://x/y") == _item_id(None, "https://x/y")   # stable
    assert _item_id(None, None) is None
