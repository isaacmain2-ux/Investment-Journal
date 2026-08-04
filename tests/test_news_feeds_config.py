"""Tests for the news_feeds manifest loader/validator in src/common/config.py."""
import pytest
import yaml

from src.common.config import load_feeds, iter_feeds, _validate_feeds


def test_loads_real_manifest():
    cfg = load_feeds("config/news_feeds.yaml")
    feeds = iter_feeds(cfg)
    assert len(feeds) >= 4
    names = {f["name"] for f in feeds}
    assert {"home", "markets"} <= names
    # every flattened feed is tagged with its group and defaulted region
    assert all("group" in f and "region" in f for f in feeds)


def test_iter_tags_group():
    cfg = {"meta": {}, "feeds": {
        "core": [{"name": "a", "url": "https://x/a"}],
        "themed": [{"name": "b", "url": "https://x/b", "region": "uk"}],
    }}
    rows = {f["name"]: f for f in iter_feeds(cfg)}
    assert rows["a"]["group"] == "core" and rows["a"]["region"] is None
    assert rows["b"]["group"] == "themed" and rows["b"]["region"] == "uk"


def test_rejects_missing_top_level_keys():
    with pytest.raises(ValueError):
        _validate_feeds({"feeds": {}})              # no meta
    with pytest.raises(ValueError):
        _validate_feeds({"meta": {}})               # no feeds


def test_rejects_empty():
    with pytest.raises(ValueError):
        _validate_feeds({"meta": {}, "feeds": {"core": []}})


def test_rejects_missing_url():
    with pytest.raises(ValueError):
        _validate_feeds({"meta": {}, "feeds": {"core": [{"name": "a"}]}})


def test_rejects_bad_url():
    with pytest.raises(ValueError):
        _validate_feeds({"meta": {}, "feeds": {"core": [{"name": "a", "url": "ftp://x/a"}]}})


def test_rejects_duplicate_name():
    cfg = {"meta": {}, "feeds": {
        "core": [{"name": "dup", "url": "https://x/1"}],
        "themed": [{"name": "dup", "url": "https://x/2"}],
    }}
    with pytest.raises(ValueError):
        _validate_feeds(cfg)
