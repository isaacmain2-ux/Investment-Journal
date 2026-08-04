"""Tests for src/extract/ft_ingest.py - the network fetch is mocked and the
warehouse is in-memory, so these run offline. Skips if duckdb is absent."""
from datetime import datetime, timezone

import pytest

duckdb = pytest.importorskip("duckdb")

from src.extract import ft_ingest
from src.load import load_headlines
from src.extract.rss_client import FeedResult

FAKE_CFG = {
    "meta": {"user_agent": "TestAgent/1.0"},
    "feeds": {
        "core": [
            {"name": "home", "url": "https://ft.com/rss/home", "region": "global"},
            {"name": "markets", "url": "https://ft.com/markets?format=rss", "region": "global"},
        ],
        "themed": [
            {"name": "opinion", "url": "https://ft.com/opinion?format=rss", "region": "global"},
        ],
    },
}


class _NoClose:
    """Proxy that forwards to a real connection but makes close() a no-op, so a
    test can inspect the warehouse after run() has finished with it."""
    def __init__(self, con): self._c = con
    def __getattr__(self, k): return getattr(self._c, k)
    def close(self): pass


def _item(i):
    return {"item_id": f"s-{i}", "title": f"H{i}", "summary": f"sum{i}",
            "link": f"https://ft.com/{i}",
            "published_at": datetime(2026, 1, 7, 8, 0, tzinfo=timezone.utc)}


def _wire(monkeypatch, fetch_impl, captured):
    con = _NoClose(duckdb.connect(":memory:"))
    monkeypatch.setattr(ft_ingest, "get_connection", lambda: con)
    monkeypatch.setattr(ft_ingest, "load_feeds", lambda _p: FAKE_CFG)
    monkeypatch.setattr(ft_ingest, "fetch_feed", fetch_impl)
    monkeypatch.setattr(ft_ingest, "write_report",
                        lambda md, path: captured.update(md=md, path=path) or path)
    raw_calls = []
    orig_raw = load_headlines.save_raw_xml
    monkeypatch.setattr(load_headlines, "save_raw_xml",
                        lambda feed, content, stamp, **k: raw_calls.append((feed, content)))
    captured["raw_calls"] = raw_calls
    return con


def test_happy_path_loads_and_reports(monkeypatch):
    def fetch(name, url, etag=None, last_modified=None, user_agent=None):
        return FeedResult(name, items=[_item(1), _item(2)], status="ok",
                          http_status=200, etag=f"etag-{name}", raw=b"<rss/>")
    cap = {}
    con = _wire(monkeypatch, fetch, cap)
    rc = ft_ingest.run(only=["home", "markets"])
    assert rc == 0
    # 2 stories per feed, but same item_ids across feeds -> 2 unique stories, 4 bridges
    assert con.execute("SELECT count(*) FROM stg_headlines").fetchone()[0] == 2
    assert con.execute("SELECT count(*) FROM stg_headline_feeds").fetchone()[0] == 4
    # status rows recorded for both feeds
    assert con.execute("SELECT count(*) FROM ft_feed_status").fetchone()[0] == 2
    # cache stored for both feeds
    assert load_headlines.get_feed_cache(con, "home")["etag"] == "etag-home"
    # raw landed for both ok feeds
    assert {c[0] for c in cap["raw_calls"]} == {"home", "markets"}
    # report captured with a PASS banner
    assert "PASS" in cap["md"] and cap["path"].endswith(".md")


def test_only_filter_restricts_feeds(monkeypatch):
    seen = []
    def fetch(name, url, etag=None, last_modified=None, user_agent=None):
        seen.append(name)
        return FeedResult(name, items=[_item(1)], status="ok", http_status=200, raw=b"<rss/>")
    _wire(monkeypatch, fetch, {})
    ft_ingest.run(only=["markets"])
    assert seen == ["markets"]


def test_not_modified_skips_load_and_raw(monkeypatch):
    def fetch(name, url, etag=None, last_modified=None, user_agent=None):
        return FeedResult(name, status="not_modified", http_status=304)
    cap = {}
    con = _wire(monkeypatch, fetch, cap)
    ft_ingest.run(only=["home"])
    assert con.execute("SELECT count(*) FROM stg_headlines").fetchone()[0] == 0
    assert cap["raw_calls"] == []                                    # nothing landed
    assert con.execute("SELECT status FROM ft_feed_status WHERE feed='home'").fetchone()[0] == "not_modified"


def test_error_feed_is_recorded_not_fatal(monkeypatch):
    def fetch(name, url, etag=None, last_modified=None, user_agent=None):
        if name == "home":
            return FeedResult(name, status="error", http_status=500, error="boom")
        return FeedResult(name, items=[_item(1)], status="ok", http_status=200, raw=b"<rss/>")
    cap = {}
    con = _wire(monkeypatch, fetch, cap)
    rc = ft_ingest.run(only=["home", "markets"])
    assert rc == 0                                                   # one bad feed doesn't sink the run
    assert con.execute("SELECT status FROM ft_feed_status WHERE feed='home'").fetchone()[0] == "error"
    assert con.execute("SELECT count(*) FROM stg_headlines").fetchone()[0] == 1   # markets still loaded
    assert "ISSUES" in cap["md"]                                     # banner downgraded


def test_conditional_get_sends_stored_validators(monkeypatch):
    calls = {}
    def fetch(name, url, etag=None, last_modified=None, user_agent=None):
        calls[name] = {"etag": etag, "last_modified": last_modified, "ua": user_agent}
        return FeedResult(name, items=[_item(1)], status="ok", http_status=200,
                          etag="new", raw=b"<rss/>")
    con = _wire(monkeypatch, fetch, {})
    load_headlines.ensure_cache_schema(con)                             # simulate a prior run
    load_headlines.set_feed_cache(con, "home", "prev-etag", "prev-lm")   # pre-seed
    ft_ingest.run(only=["home"])
    assert calls["home"]["etag"] == "prev-etag"
    assert calls["home"]["last_modified"] == "prev-lm"
    assert calls["home"]["ua"] == "TestAgent/1.0"                    # UA from manifest meta


def test_unknown_only_returns_error(monkeypatch):
    _wire(monkeypatch, lambda *a, **k: None, {})
    assert ft_ingest.run(only=["does-not-exist"]) == 1
