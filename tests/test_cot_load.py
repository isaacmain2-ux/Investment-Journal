"""Tests for src/load/load_cot.py against an in-memory DuckDB. Skips if absent."""
import datetime as dt
import pytest

duckdb = pytest.importorskip("duckdb")
from src.load import load_cot


def _con():
    con = duckdb.connect(":memory:"); load_cot.ensure_schema(con); return con


def _row(mid="sp500", d=dt.date(2026, 7, 28), ll=180000, ls=240000):
    return {"market_id": mid, "market": "E-MINI S&P 500 - CME", "report_date": d,
            "open_interest": 2500000, "lev_long": ll, "lev_short": ls, "lev_spread": 30000,
            "am_long": 900000, "am_short": 300000, "dealer_long": 50000, "dealer_short": 70000}


def test_load_and_available_from():
    con = _con()
    n_seen, n_new = load_cot.load_cot(con, "sp500", [_row()], lag_days=3)
    assert (n_seen, n_new) == (1, 1)
    rd, af, ll = con.execute("SELECT report_date, available_from, lev_long FROM stg_cot").fetchone()
    assert rd == dt.date(2026, 7, 28)
    assert af == dt.date(2026, 7, 31)          # Tuesday + 3 days = Friday release
    assert ll == 180000


def test_idempotent_reload():
    con = _con()
    load_cot.load_cot(con, "sp500", [_row()])
    n_seen, n_new = load_cot.load_cot(con, "sp500", [_row()])       # same week again
    assert (n_seen, n_new) == (1, 0)
    assert con.execute("SELECT count(*) FROM stg_cot").fetchone()[0] == 1


def test_revision_replaces():
    con = _con()
    load_cot.load_cot(con, "sp500", [_row(ll=180000)])
    load_cot.load_cot(con, "sp500", [_row(ll=195000)])             # revised value, same date
    val = con.execute("SELECT lev_long FROM stg_cot").fetchone()[0]
    assert val == 195000 and con.execute("SELECT count(*) FROM stg_cot").fetchone()[0] == 1


def test_incremental_new_weeks():
    con = _con()
    load_cot.load_cot(con, "sp500", [_row(d=dt.date(2026, 7, 28))])
    n_seen, n_new = load_cot.load_cot(con, "sp500", [_row(d=dt.date(2026, 8, 4))])
    assert (n_seen, n_new) == (1, 1)
    assert con.execute("SELECT count(*) FROM stg_cot").fetchone()[0] == 2


def test_get_max_report_date():
    con = _con()
    assert load_cot.get_max_report_date(con, "sp500") is None
    load_cot.load_cot(con, "sp500", [_row(d=dt.date(2026, 7, 28)), _row(d=dt.date(2026, 8, 4))])
    assert load_cot.get_max_report_date(con, "sp500") == dt.date(2026, 8, 4)


def test_record_status():
    con = _con()
    load_cot.record_status(con, "sp500", "E-mini S&P 500", "ok", 100, 3, None)
    row = con.execute("SELECT status, n_rows, n_new FROM cot_status WHERE market_id='sp500'").fetchone()
    assert row == ("ok", 100, 3)


def test_ignores_rows_without_date():
    con = _con()
    n_seen, n_new = load_cot.load_cot(con, "sp500", [_row(), {"market_id": "sp500", "report_date": None}])
    assert (n_seen, n_new) == (1, 1)


def test_dedupe_duplicate_weeks_no_crash():
    con = _con()
    dup = [_row(d=dt.date(2014, 6, 10), ll=100, ls=50),          # net favours one row
           _row(d=dt.date(2014, 6, 10), ll=999, ls=50)]
    dup[0]["open_interest"] = 100; dup[1]["open_interest"] = 900  # higher-OI row wins
    n_seen, n_new = load_cot.load_cot(con, "eur", dup)
    assert (n_seen, n_new) == (1, 1)
    assert con.execute("SELECT count(*) FROM stg_cot").fetchone()[0] == 1
    assert con.execute("SELECT open_interest FROM stg_cot").fetchone()[0] == 900
