"""Tests for src/extract/skew_ingest.py - Yahoo mocked, in-memory warehouse."""
import datetime as dt
import pytest

duckdb = pytest.importorskip("duckdb")
from src.extract import skew_ingest
from src.extract.skew_client import SkewResult

FAKE_CFG = {"meta": {"target_dte": 30, "moneyness": {"put": 0.90, "atm": 1.00, "call": 1.10}},
            "tickers": [{"id": "spx", "ticker": "SPY", "label": "S&P 500 (SPY)"},
                        {"id": "ndx", "ticker": "QQQ", "label": "Nasdaq 100 (QQQ)"}]}


class _NoClose:
    def __init__(self, con): self._c = con
    def __getattr__(self, k): return getattr(self._c, k)
    def close(self): pass


def _ok(tid, tk):
    return SkewResult(tid, tk, capture_date=dt.date(2026, 8, 2), expiry="2026-09-04", dte=33,
                      spot=500.0, measures={"atm_iv": 0.20, "put_iv": 0.28, "call_iv": 0.16,
                                            "put_skew": 0.08, "risk_reversal": 0.12}, status="ok")


def _wire(monkeypatch, fetch_impl, cap):
    con = _NoClose(duckdb.connect(":memory:"))
    monkeypatch.setattr(skew_ingest, "get_connection", lambda: con)
    monkeypatch.setattr(skew_ingest, "load_skew_tickers", lambda _p: FAKE_CFG)
    monkeypatch.setattr(skew_ingest, "fetch_skew", fetch_impl)
    monkeypatch.setattr(skew_ingest, "write_report", lambda md, path: cap.update(md=md) or path)
    return con


def test_happy_path_captures_all(monkeypatch):
    cap = {}; con = _wire(monkeypatch, lambda tid, tk, **k: _ok(tid, tk), cap)
    assert skew_ingest.run() == 0
    assert con.execute("SELECT count(*) FROM stg_options_skew").fetchone()[0] == 2
    assert con.execute("SELECT count(*) FROM skew_status").fetchone()[0] == 2
    assert "PASS" in cap["md"]


def test_only_filter(monkeypatch):
    seen = []
    def fetch(tid, tk, **k): seen.append(tid); return _ok(tid, tk)
    _wire(monkeypatch, fetch, {})
    skew_ingest.run(only=["ndx"])
    assert seen == ["ndx"]


def test_empty_not_loaded_but_recorded(monkeypatch):
    cap = {}
    def fetch(tid, tk, **k):
        return SkewResult(tid, tk, capture_date=dt.date(2026, 8, 2), status="empty", error="no expiries")
    con = _wire(monkeypatch, fetch, cap)
    skew_ingest.run(only=["spx"])
    assert con.execute("SELECT count(*) FROM stg_options_skew").fetchone()[0] == 0     # nothing loaded
    assert con.execute("SELECT status FROM skew_status WHERE ticker_id='spx'").fetchone()[0] == "empty"
    assert "ISSUES" in cap["md"]


def test_error_recorded(monkeypatch):
    def fetch(tid, tk, **k):
        return SkewResult(tid, tk, capture_date=dt.date(2026, 8, 2), status="error", error="yahoo down")
    con = _wire(monkeypatch, fetch, {})
    skew_ingest.run(only=["spx"])
    assert con.execute("SELECT status FROM skew_status WHERE ticker_id='spx'").fetchone()[0] == "error"
