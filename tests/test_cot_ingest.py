"""Tests for src/extract/cot_ingest.py - network mocked, in-memory warehouse."""
import datetime as dt
import pytest

duckdb = pytest.importorskip("duckdb")
from src.extract import cot_ingest
from src.load import load_cot
from src.extract.cot_client import CotResult

FAKE_CFG = {"meta": {"dataset": "yw9f-hn96", "base": "http://x", "release_lag_days": 3,
                     "history_start": "2010-01-01"},
            "markets": [{"id": "sp500", "match": "E-MINI S&P 500", "label": "E-mini S&P 500"},
                        {"id": "vix", "match": "VIX FUTURES", "label": "VIX futures"}]}


class _NoClose:
    def __init__(self, con): self._c = con
    def __getattr__(self, k): return getattr(self._c, k)
    def close(self): pass


def _rows(mid, d=dt.date(2026, 7, 28)):
    return [{"market_id": mid, "market": mid.upper(), "report_date": d, "open_interest": 100,
             "lev_long": 10, "lev_short": 20, "lev_spread": 1, "am_long": 5, "am_short": 3,
             "dealer_long": 2, "dealer_short": 4, "raw": b"[]"}]


def _wire(monkeypatch, fetch_impl, cap):
    con = _NoClose(duckdb.connect(":memory:"))
    monkeypatch.setattr(cot_ingest, "get_connection", lambda: con)
    monkeypatch.setattr(cot_ingest, "load_cot_markets", lambda _p: FAKE_CFG)
    monkeypatch.setattr(cot_ingest, "probe_schema", lambda *a, **k: {"ok"})
    monkeypatch.setattr(cot_ingest, "fetch_market", fetch_impl)
    monkeypatch.setattr(cot_ingest, "write_report", lambda md, path: cap.update(md=md, path=path) or path)
    monkeypatch.setattr(load_cot, "save_raw_json", lambda *a, **k: None)
    return con


def test_happy_path_loads_all(monkeypatch):
    def fetch(mid, match, dataset=None, base=None, since=None, **k):
        return CotResult(mid, match, rows=_rows(mid), status="ok", http_status=200, raw=b"[]")
    cap = {}; con = _wire(monkeypatch, fetch, cap)
    assert cot_ingest.run() == 0
    assert con.execute("SELECT count(*) FROM stg_cot").fetchone()[0] == 2      # one row per market
    assert con.execute("SELECT count(*) FROM cot_status").fetchone()[0] == 2
    assert "PASS" in cap["md"]


def test_incremental_since_passed(monkeypatch):
    calls = {}
    def fetch(mid, match, dataset=None, base=None, since=None, **k):
        calls[mid] = since
        return CotResult(mid, match, rows=_rows(mid), status="ok", raw=b"[]")
    con = _wire(monkeypatch, fetch, {})
    load_cot.ensure_schema(con)                      # schema must exist before pre-seeding
    # pre-seed sp500 up to a date -> next run should fetch since that date
    load_cot.load_cot(con, "sp500", _rows("sp500", d=dt.date(2026, 7, 21)))
    cot_ingest.run(only=["sp500"])
    assert calls["sp500"] == "2026-07-21"          # incremental from stored max


def test_full_ignores_state(monkeypatch):
    calls = {}
    def fetch(mid, match, dataset=None, base=None, since=None, **k):
        calls[mid] = since
        return CotResult(mid, match, rows=_rows(mid), status="ok", raw=b"[]")
    con = _wire(monkeypatch, fetch, {})
    load_cot.ensure_schema(con)                      # schema must exist before pre-seeding
    load_cot.load_cot(con, "sp500", _rows("sp500", d=dt.date(2026, 7, 21)))
    cot_ingest.run(only=["sp500"], full=True)
    assert calls["sp500"] == "2010-01-01"          # history_start, not stored state


def test_only_filter(monkeypatch):
    seen = []
    def fetch(mid, match, dataset=None, base=None, since=None, **k):
        seen.append(mid); return CotResult(mid, match, rows=_rows(mid), status="ok", raw=b"[]")
    _wire(monkeypatch, fetch, {})
    cot_ingest.run(only=["vix"])
    assert seen == ["vix"]


def test_empty_match_recorded(monkeypatch):
    def fetch(mid, match, dataset=None, base=None, since=None, **k):
        return CotResult(mid, match, rows=[], status="empty", raw=b"[]")
    cap = {}; con = _wire(monkeypatch, fetch, cap)
    cot_ingest.run(only=["sp500"])
    assert con.execute("SELECT status FROM cot_status WHERE market_id='sp500'").fetchone()[0] == "empty"
    assert "ISSUES" in cap["md"]
