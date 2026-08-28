"""Tests for journal_positions.run() against an in-memory DuckDB (the warehouse-facing
wiring around the pure functions tested in test_journal_positions.py). Skips if
duckdb is absent."""
import datetime as dt
import pytest

duckdb = pytest.importorskip("duckdb")
from src.load import load_journal
from src.transform import journal_positions as jp


def _con():
    con = duckdb.connect(":memory:")
    load_journal.ensure_schema(con)
    con.execute("""CREATE TABLE stg_security_prices (
        ticker VARCHAR, date DATE, open DOUBLE, high DOUBLE, low DOUBLE,
        close DOUBLE, volume DOUBLE)""")
    return con


def _seed(con):
    load_journal.load_trades(con, [{
        "trade_id": "2026-08-01-NVDA-01", "trade_date": "2026-08-01", "portfolio": "main",
        "ticker": "NVDA", "action": "BUY", "quantity": 10.0, "price": 100.0, "currency": "USD",
        "fees": 0.0, "conviction": "high", "timeframe": "months", "catalyst": "capex",
        "thesis": "scan", "tags": "ai", "entered_at": "2026-08-01 09:00:00",
    }])
    con.executemany(
        "INSERT INTO stg_security_prices (ticker, date, close) VALUES (?, ?, ?)",
        [("NVDA", dt.date(2026, 8, 1), 100.0), ("NVDA", dt.date(2026, 8, 2), 110.0)])


def test_run_writes_both_tables():
    con = _con()
    _seed(con)
    n_pos, n_val = jp.run(con)
    assert n_pos == 1 and n_val == 2
    assert con.execute("SELECT ticker, status, quantity_open FROM fct_positions").fetchone() \
        == ("NVDA", "OPEN", 10.0)
    latest = con.execute(
        "SELECT market_value FROM fct_portfolio_value ORDER BY date DESC LIMIT 1").fetchone()
    assert latest[0] == 1100.0


def test_run_is_idempotent_on_rerun():
    con = _con()
    _seed(con)
    jp.run(con)
    n_pos, n_val = jp.run(con)      # re-run with no new trades - same result, no dupes
    assert n_pos == 1 and n_val == 2
    assert con.execute("SELECT count(*) FROM fct_positions").fetchone()[0] == 1


def test_run_tolerates_empty_ledger():
    con = _con()
    n_pos, n_val = jp.run(con)
    assert (n_pos, n_val) == (0, 0)
    assert con.execute("SELECT count(*) FROM fct_positions").fetchone()[0] == 0
    assert con.execute("SELECT count(*) FROM fct_portfolio_value").fetchone()[0] == 0
