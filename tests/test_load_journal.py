"""Tests for src/load/load_journal.py against an in-memory DuckDB. Skips if absent."""
import datetime as dt
import pytest

duckdb = pytest.importorskip("duckdb")
from src.load import load_journal


def _con():
    con = duckdb.connect(":memory:"); load_journal.ensure_schema(con); return con


def _row(tid="2026-08-23-NVDA-01", d="2026-08-23", ticker="NVDA", action="BUY",
         qty=10.0, price=187.40):
    return {"trade_id": tid, "trade_date": d, "portfolio": "main", "ticker": ticker,
            "action": action, "quantity": qty, "price": price, "currency": "USD",
            "fees": 0.0, "conviction": "high", "timeframe": "months", "catalyst": "capex",
            "thesis": "Top-5 scan 2026-08-21: composite +1.82", "tags": "ai,momentum",
            "entered_at": "2026-08-23 09:00:00"}


def test_load_and_columns():
    con = _con()
    n = load_journal.load_trades(con, [_row()])
    assert n == 1
    tid, ticker, action, qty, price, td = con.execute(
        "SELECT trade_id, ticker, action, quantity, price, trade_date "
        "FROM stg_journal_trades").fetchone()
    assert tid == "2026-08-23-NVDA-01" and ticker == "NVDA" and action == "BUY"
    assert qty == 10.0 and price == 187.40
    assert td == dt.date(2026, 8, 23)


def test_full_refresh_replaces_all_rows():
    con = _con()
    load_journal.load_trades(con, [_row(tid="T1"), _row(tid="T2", ticker="CAT")])
    assert con.execute("SELECT count(*) FROM stg_journal_trades").fetchone()[0] == 2
    # a second load with only one row (e.g. a corrupted ledger read) replaces, not adds
    n = load_journal.load_trades(con, [_row(tid="T1")])
    assert n == 1
    assert con.execute("SELECT count(*) FROM stg_journal_trades").fetchone()[0] == 1


def test_empty_ledger_clears_table():
    con = _con()
    load_journal.load_trades(con, [_row()])
    n = load_journal.load_trades(con, [])
    assert n == 0
    assert con.execute("SELECT count(*) FROM stg_journal_trades").fetchone()[0] == 0


def test_rerun_is_idempotent_in_effect():
    con = _con()
    load_journal.load_trades(con, [_row(), _row(tid="T2", ticker="CAT")])
    load_journal.load_trades(con, [_row(), _row(tid="T2", ticker="CAT")])
    assert con.execute("SELECT count(*) FROM stg_journal_trades").fetchone()[0] == 2


@pytest.mark.parametrize("bad", [
    {"trade_id": "", "trade_date": "2026-08-23", "ticker": "NVDA", "action": "BUY",
     "quantity": 1, "price": 1},
    {"trade_id": "T1", "trade_date": "2026-08-23", "ticker": "", "action": "BUY",
     "quantity": 1, "price": 1},
    {"trade_id": "T1", "trade_date": "2026-08-23", "ticker": "NVDA", "action": "HOLD",
     "quantity": 1, "price": 1},
    {"trade_id": "T1", "trade_date": "2026-08-23", "ticker": "NVDA", "action": "BUY",
     "quantity": 0, "price": 1},
    {"trade_id": "T1", "trade_date": "2026-08-23", "ticker": "NVDA", "action": "BUY",
     "quantity": 1, "price": None},
    {"trade_id": "T1", "trade_date": None, "ticker": "NVDA", "action": "BUY",
     "quantity": 1, "price": 1},
])
def test_malformed_rows_are_dropped(bad):
    con = _con()
    n = load_journal.load_trades(con, [bad])
    assert n == 0
    assert con.execute("SELECT count(*) FROM stg_journal_trades").fetchone()[0] == 0


def test_run_reads_ledger_csv(tmp_path, monkeypatch):
    p = tmp_path / "trades.csv"
    from src.journal import ledger
    ledger.append_trades([_row()], str(p))
    con = duckdb.connect(":memory:")
    n = load_journal.run(con=con, path=str(p))
    assert n == 1
    assert con.execute("SELECT count(*) FROM stg_journal_trades").fetchone()[0] == 1
