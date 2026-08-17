"""Tests for src/extract/yahoo_prices.py - yfinance mocked, parsing exercised for real."""
import datetime as dt
import pytest
pd = pytest.importorskip("pandas")
from src.extract import yahoo_prices as Y


def test_to_yahoo_dotted():
    assert Y.to_yahoo("AAPL") == "AAPL"
    assert Y.to_yahoo("brk.b") == "BRK-B"      # the dotted-ticker fix


def _multi_df():
    idx = pd.to_datetime(["2026-08-03", "2026-08-04"])
    cols = pd.MultiIndex.from_product([["AAPL", "BRK-B"],
                                       ["Open", "High", "Low", "Close", "Volume"]])
    data = [[189, 191, 188, 190, 1e6,  400, 405, 399, 402, 2e5],
            [190, 193, 190, 192, 9e5,  402, 404, 401, 403, 1e5]]
    return pd.DataFrame(data, index=idx, columns=cols)


def test_parse_download_multi_ticker_maps_back():
    ymap = {"AAPL": "AAPL", "BRK-B": "BRK.B"}
    rows = Y.parse_download(_multi_df(), ymap)
    assert len(rows) == 4
    aapl = [r for r in rows if r["ticker"] == "AAPL"]
    assert aapl[0]["date"] == dt.date(2026, 8, 3) and aapl[0]["close"] == 190.0
    # dotted ticker mapped back from the Yahoo dash form
    assert any(r["ticker"] == "BRK.B" and r["close"] == 402.0 for r in rows)


def test_parse_download_single_ticker_flat_columns():
    idx = pd.to_datetime(["2026-08-03"])
    df = pd.DataFrame([[189, 191, 188, 190, 1e6]], index=idx,
                      columns=["Open", "High", "Low", "Close", "Volume"])
    rows = Y.parse_download(df, {"AAPL": "AAPL"})
    assert len(rows) == 1 and rows[0]["ticker"] == "AAPL" and rows[0]["close"] == 190.0


def test_parse_download_skips_nan_close():
    idx = pd.to_datetime(["2026-08-03", "2026-08-04"])
    df = pd.DataFrame([[1, 2, 1, float("nan"), 10], [1, 2, 1, 1.5, 20]], index=idx,
                      columns=["Open", "High", "Low", "Close", "Volume"])
    rows = Y.parse_download(df, {"X": "X"})
    assert len(rows) == 1 and rows[0]["close"] == 1.5


def test_fetch_prices_batch_chunks_and_tracks_failures(monkeypatch):
    calls = {"n": 0}
    def fake_dl(symbols, start, session):
        calls["n"] += 1
        # return data only for AAPL; MSFT/ZZZZ get no columns -> counted failed
        idx = pd.to_datetime(["2026-08-03"])
        cols = pd.MultiIndex.from_product([["AAPL"], ["Open", "High", "Low", "Close", "Volume"]])
        return pd.DataFrame([[1, 2, 1, 1.5, 10]], index=idx, columns=cols)
    monkeypatch.setattr(Y, "_download", fake_dl)
    monkeypatch.setattr(Y.time, "sleep", lambda s: None)
    rows, failed = Y.fetch_prices_batch(["AAPL", "MSFT"], chunk=80)
    assert calls["n"] == 1                       # one chunk
    assert [r["ticker"] for r in rows] == ["AAPL"]
    assert "MSFT" in failed                      # no data returned -> flagged


def test_fetch_prices_batch_multiple_chunks(monkeypatch):
    seen_chunks = []
    def fake_dl(symbols, start, session):
        seen_chunks.append(len(symbols)); return None    # all fail -> all failed
    monkeypatch.setattr(Y, "_download", fake_dl)
    monkeypatch.setattr(Y.time, "sleep", lambda s: None)
    rows, failed = Y.fetch_prices_batch([f"T{i}" for i in range(5)], chunk=2, retries=1)
    assert seen_chunks == [2, 2, 1] and len(failed) == 5 and rows == []
