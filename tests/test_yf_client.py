"""Tests for src/extract/yf_client.py - the download is mocked, so these run
offline and never touch Yahoo."""
import pandas as pd

from src.extract import yf_client
from src.extract.yf_client import fetch_prices


def _batched_frame(tickers):
    """A yfinance-style batched download: MultiIndex columns [ticker, field]."""
    idx = pd.to_datetime(["2024-01-02", "2024-01-03"])
    fields = ["Open", "High", "Low", "Close", "Adj Close", "Volume"]
    cols = pd.MultiIndex.from_product([tickers, fields])
    df = pd.DataFrame(index=idx, columns=cols, dtype="float64")
    for i, t in enumerate(tickers):
        base = 100 + 10 * i
        df[(t, "Open")] = [base, base + 1]
        df[(t, "High")] = [base + 2, base + 3]
        df[(t, "Low")] = [base - 1, base]
        df[(t, "Close")] = [base + 1, base + 2]
        df[(t, "Adj Close")] = [base, base + 1]
        df[(t, "Volume")] = [1_000_000, 1_100_000]
    return df


def _single_frame():
    idx = pd.to_datetime(["2024-01-02", "2024-01-03"])
    return pd.DataFrame({
        "Open": [10.0, 11.0], "High": [10.5, 11.5], "Low": [9.5, 10.5],
        "Close": [10.2, 11.2], "Adj Close": [10.0, 11.0], "Volume": [500, 600],
    }, index=idx)


def test_batched_parse(monkeypatch):
    monkeypatch.setattr(yf_client, "_download", lambda t, s, e: _batched_frame(["AAPL", "MSFT"]))
    res = fetch_prices(["AAPL", "MSFT"], pace=0)
    assert set(res) == {"AAPL", "MSFT"}
    aapl = res["AAPL"]
    assert aapl.status == "ok" and aapl.n_obs == 2
    assert list(aapl.df.columns) == yf_client.COLS
    assert aapl.df["close"].tolist() == [101.0, 102.0]
    assert aapl.df["adj_close"].tolist() == [100.0, 101.0]      # kept separately


def test_single_ticker_parse(monkeypatch):
    monkeypatch.setattr(yf_client, "_download", lambda t, s, e: _single_frame())
    res = fetch_prices(["ONE"], pace=0)
    r = res["ONE"]
    assert r.status == "ok" and r.n_obs == 2
    assert r.df["close"].tolist() == [10.2, 11.2]


def test_missing_ticker_is_empty(monkeypatch):
    monkeypatch.setattr(yf_client, "_download", lambda t, s, e: _batched_frame(["AAPL"]))
    res = fetch_prices(["AAPL", "GHOST"], pace=0)
    assert res["AAPL"].status == "ok"
    assert res["GHOST"].status == "empty" and res["GHOST"].n_obs == 0


def test_rate_limit_retries_then_fails(monkeypatch):
    calls = {"n": 0}

    def boom(t, s, e):
        calls["n"] += 1
        raise RuntimeError("Too Many Requests. Rate limited.")

    monkeypatch.setattr(yf_client, "_download", boom)
    monkeypatch.setattr(yf_client.time, "sleep", lambda s: None)   # no real waiting
    res = fetch_prices(["AAPL"], pace=0, retries=3)
    assert res["AAPL"].status == "error"
    assert calls["n"] == 3                                          # retried the full 3


def test_batching_splits_requests(monkeypatch):
    seen = []

    def rec(t, s, e):
        seen.append(list(t))
        return _batched_frame(list(t))

    monkeypatch.setattr(yf_client, "_download", rec)
    fetch_prices([f"T{i}" for i in range(7)], batch_size=3, pace=0)
    assert [len(b) for b in seen] == [3, 3, 1]                      # 7 tickers -> 3 batches
