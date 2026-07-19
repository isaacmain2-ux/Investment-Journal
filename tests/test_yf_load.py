"""Tests for src/load/load_yf.py against an in-memory DuckDB. Skips if duckdb absent."""
import pandas as pd
import pytest

duckdb = pytest.importorskip("duckdb")

from src.load import load_yf


def _con():
    con = duckdb.connect(":memory:")
    load_yf.ensure_schema(con)
    return con


def _px():
    return pd.DataFrame({
        "price_date": [pd.Timestamp("2024-01-02").date(), pd.Timestamp("2024-01-03").date()],
        "open": [100.0, 101.0], "high": [102.0, 103.0], "low": [99.0, 100.0],
        "close": [101.0, 102.0], "adj_close": [100.0, 101.0], "volume": [1e6, 1.1e6],
    })


def test_idempotent_price_load():
    con = _con()
    n1 = load_yf.load_prices(con, "AAPL", _px())
    load_yf.load_prices(con, "AAPL", _px())          # reload the same data
    total = con.execute("SELECT count(*) FROM stg_equity_prices WHERE ticker='AAPL'").fetchone()[0]
    assert n1 == 2 and total == 2                     # no duplication
    # close and adj_close are stored separately
    row = con.execute("SELECT close, adj_close FROM stg_equity_prices "
                      "WHERE ticker='AAPL' ORDER BY price_date LIMIT 1").fetchone()
    assert row == (101.0, 100.0)


def test_upsert_dim_and_status():
    con = _con()
    load_yf.upsert_dim(con, [{"ticker": "SHEL.L", "name": "Shell", "type": "stock",
                              "region": "UK", "sector": "Energy", "currency": "GBp",
                              "group": "watchlist"}])
    assert con.execute('SELECT currency, "group" FROM dim_security WHERE ticker=\'SHEL.L\''
                       ).fetchone() == ("GBp", "watchlist")
    load_yf.record_status(con, "SHEL.L", "ok", 100, None, None, None)
    assert con.execute("SELECT status, n_obs FROM equity_status WHERE ticker='SHEL.L'"
                       ).fetchone() == ("ok", 100)
