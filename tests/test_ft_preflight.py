"""Tests for src/extract/ft_preflight.py - fetch is mocked, no network, no DB."""
from src.extract import ft_preflight
from src.extract.rss_client import FeedResult

FAKE_CFG = {"meta": {"user_agent": "TestAgent/1.0"},
            "feeds": {"core": [{"name": "home", "url": "https://ft.com/rss/home"},
                               {"name": "markets", "url": "https://ft.com/markets?format=rss"}]}}


def test_all_reachable_returns_zero(monkeypatch):
    monkeypatch.setattr(ft_preflight, "load_feeds", lambda _p: FAKE_CFG)
    monkeypatch.setattr(ft_preflight, "fetch_feed",
                        lambda name, url, user_agent=None: FeedResult(name, items=[{"item_id": "x"}],
                                                                      status="ok", http_status=200))
    assert ft_preflight.main() == 0


def test_any_unreachable_returns_one(monkeypatch):
    monkeypatch.setattr(ft_preflight, "load_feeds", lambda _p: FAKE_CFG)
    def fetch(name, url, user_agent=None):
        if name == "markets":
            return FeedResult(name, status="error", http_status=404, error="not found")
        return FeedResult(name, items=[{"item_id": "x"}], status="ok", http_status=200)
    monkeypatch.setattr(ft_preflight, "fetch_feed", fetch)
    assert ft_preflight.main() == 1


def test_not_modified_counts_as_reachable(monkeypatch):
    monkeypatch.setattr(ft_preflight, "load_feeds", lambda _p: FAKE_CFG)
    monkeypatch.setattr(ft_preflight, "fetch_feed",
                        lambda name, url, user_agent=None: FeedResult(name, status="not_modified",
                                                                      http_status=304))
    assert ft_preflight.main() == 0
