"""Tests for src/extract/stooq_client.py - network mocked."""
import datetime as dt
from src.extract import stooq_client


class _Resp:
    def __init__(self, text, status=200): self.text=text; self.status_code=status


CSV = "Date,Open,High,Low,Close,Volume\n2026-08-01,100.0,102.0,99.5,101.5,1200000\n2026-08-04,101.5,103.0,101.0,102.8,900000\n"


def test_to_symbol():
    assert stooq_client.to_symbol("AAPL") == "aapl.us"
    assert stooq_client.to_symbol(" msft ") == "msft.us"


def test_parse_csv_shapes_rows():
    rows = stooq_client.parse_csv(CSV, "AAPL")
    assert len(rows)==2
    assert rows[0]=={"ticker":"AAPL","date":dt.date(2026,8,1),"open":100.0,"high":102.0,
                     "low":99.5,"close":101.5,"volume":1200000.0}


def test_parse_csv_empty_and_nd():
    assert stooq_client.parse_csv("", "X") == []
    assert stooq_client.parse_csv("No data", "X") == []


def test_fetch_prices_ok(monkeypatch):
    monkeypatch.setattr(stooq_client, "_get", lambda u, timeout=30: _Resp(CSV))
    monkeypatch.setattr(stooq_client.time, "sleep", lambda s: None)
    res = stooq_client.fetch_prices("AAPL")
    assert res.status=="ok" and len(res.rows)==2 and res.ticker=="AAPL"


def test_fetch_prices_empty(monkeypatch):
    monkeypatch.setattr(stooq_client, "_get", lambda u, timeout=30: _Resp("No data"))
    monkeypatch.setattr(stooq_client.time, "sleep", lambda s: None)
    res = stooq_client.fetch_prices("ZZZ")
    assert res.status=="empty"


def test_fetch_prices_error(monkeypatch):
    monkeypatch.setattr(stooq_client, "_get", lambda u, timeout=30: _Resp("", status=500))
    monkeypatch.setattr(stooq_client.time, "sleep", lambda s: None)
    res = stooq_client.fetch_prices("AAPL")
    assert res.status=="error" and "500" in res.error
