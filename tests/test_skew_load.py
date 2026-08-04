"""Tests for src/load/load_skew.py against an in-memory DuckDB. Skips if absent."""
import datetime as dt
import pytest

duckdb = pytest.importorskip("duckdb")
from src.load import load_skew


def _con():
    con = duckdb.connect(":memory:"); load_skew.ensure_schema(con); return con


def _row(tid="spx", d=dt.date(2026, 8, 2), ps=0.08):
    return {"ticker_id": tid, "ticker": "SPY", "capture_date": d, "expiry": "2026-09-04",
            "dte": 33, "spot": 500.0, "atm_iv": 0.20, "put_iv": 0.28, "call_iv": 0.16,
            "put_skew": ps, "risk_reversal": 0.12}


def test_load_and_columns():
    con = _con()
    n_seen, n_new = load_skew.load_skew(con, [_row()])
    assert (n_seen, n_new) == (1, 1)
    ps, spot, exp = con.execute("SELECT put_skew, spot, expiry FROM stg_options_skew").fetchone()
    assert abs(ps - 0.08) < 1e-9 and spot == 500.0 and exp == "2026-09-04"


def test_idempotent_same_day_replaces():
    con = _con()
    load_skew.load_skew(con, [_row(ps=0.08)])
    n_seen, n_new = load_skew.load_skew(con, [_row(ps=0.11)])     # same capture_date, new value
    assert (n_seen, n_new) == (1, 0)
    assert con.execute("SELECT count(*) FROM stg_options_skew").fetchone()[0] == 1
    assert abs(con.execute("SELECT put_skew FROM stg_options_skew").fetchone()[0] - 0.11) < 1e-9


def test_accumulates_across_days():
    con = _con()
    load_skew.load_skew(con, [_row(d=dt.date(2026, 8, 2))])
    n_seen, n_new = load_skew.load_skew(con, [_row(d=dt.date(2026, 8, 3))])
    assert (n_seen, n_new) == (1, 1)
    assert con.execute("SELECT count(*) FROM stg_options_skew").fetchone()[0] == 2


def test_dedupe_within_batch():
    con = _con()
    n_seen, n_new = load_skew.load_skew(con, [_row(ps=0.08), _row(ps=0.09)])   # same key twice
    assert (n_seen, n_new) == (1, 1)
    assert con.execute("SELECT count(*) FROM stg_options_skew").fetchone()[0] == 1


def test_get_max_capture_date():
    con = _con()
    assert load_skew.get_max_capture_date(con, "spx") is None
    load_skew.load_skew(con, [_row(d=dt.date(2026, 8, 2)), _row(d=dt.date(2026, 8, 3))])
    assert load_skew.get_max_capture_date(con, "spx") == dt.date(2026, 8, 3)


def test_record_status():
    con = _con()
    load_skew.record_status(con, "spx", "S&P 500 (SPY)", "ok", 0.08, None)
    assert con.execute("SELECT status FROM skew_status WHERE ticker_id='spx'").fetchone()[0] == "ok"


def test_ignores_rows_without_keys():
    con = _con()
    n_seen, n_new = load_skew.load_skew(con, [_row(), {"ticker_id": None}, None])
    assert (n_seen, n_new) == (1, 1)
