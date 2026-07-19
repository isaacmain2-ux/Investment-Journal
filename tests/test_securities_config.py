"""Tests for the securities manifest loader in src/common/config.py."""
import yaml
import pytest

from src.common.config import load_securities, iter_securities


def test_real_securities_config_loads():
    cfg = load_securities("config/securities.yaml")
    secs = iter_securities(cfg)
    assert len(secs) == 64                          # full universe
    tickers = [s["ticker"] for s in secs]
    assert len(tickers) == len(set(tickers))        # no duplicates
    assert cfg["meta"]["base_currency"] == "GBP"
    # every security carries the fields the pipeline relies on
    for s in secs:
        assert {"ticker", "name", "type", "region", "currency", "group"} <= set(s)
    # the watchlist has ~30 names and includes the pence-quoted UK stocks
    watch = [s for s in secs if s["group"] == "watchlist"]
    assert len(watch) == 30
    assert any(s["currency"] == "GBp" for s in watch)   # UK shares in pence


def _write(tmp_path, obj):
    p = tmp_path / "sec.yaml"
    p.write_text(yaml.safe_dump(obj))
    return str(p)


def test_bad_type_rejected(tmp_path):
    bad = {"meta": {"base_currency": "GBP"},
           "securities": {"x": [{"ticker": "A", "name": "a", "type": "bond",
                                 "region": "US", "currency": "USD"}]}}
    with pytest.raises(ValueError):
        load_securities(_write(tmp_path, bad))


def test_duplicate_ticker_rejected(tmp_path):
    bad = {"meta": {"base_currency": "GBP"},
           "securities": {"a": [{"ticker": "DUP", "name": "a", "type": "etf",
                                 "region": "US", "currency": "USD"}],
                          "b": [{"ticker": "DUP", "name": "b", "type": "stock",
                                 "region": "US", "currency": "USD"}]}}
    with pytest.raises(ValueError):
        load_securities(_write(tmp_path, bad))


def test_missing_field_rejected(tmp_path):
    bad = {"meta": {"base_currency": "GBP"},
           "securities": {"a": [{"ticker": "A", "name": "a", "type": "etf", "region": "US"}]}}
    with pytest.raises(ValueError):
        load_securities(_write(tmp_path, bad))
