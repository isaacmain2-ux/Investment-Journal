"""Test for 05_equity_analytics.sql - runs the real SQL in in-memory DuckDB
against a fixture and checks returns and the GBP currency conversion (incl. the
pence /100 for UK shares). Skips if duckdb absent."""
from pathlib import Path

import pytest

duckdb = pytest.importorskip("duckdb")

SQL = Path("src/transform/sql/05_equity_analytics.sql").read_text(encoding="utf-8")


def _statements(text):
    no_comments = "\n".join(line.split("--", 1)[0] for line in text.splitlines())
    return [s.strip() for s in no_comments.split(";") if s.strip()]


def _con():
    con = duckdb.connect(":memory:")
    con.execute("""CREATE TABLE dim_security
                   (ticker VARCHAR, name VARCHAR, type VARCHAR, region VARCHAR,
                    sector VARCHAR, currency VARCHAR, "group" VARCHAR)""")
    con.execute("""CREATE TABLE stg_equity_prices
                   (ticker VARCHAR, price_date DATE, open DOUBLE, high DOUBLE, low DOUBLE,
                    close DOUBLE, adj_close DOUBLE, volume DOUBLE, loaded_at TIMESTAMP)""")
    con.execute("""CREATE TABLE fct_fx
                   (date DATE, gbp_per_usd DOUBLE, gbp_per_eur DOUBLE)""")
    # a USD stock and a UK pence stock
    con.execute("INSERT INTO dim_security VALUES ('AAPL','Apple','stock','US',NULL,'USD','watchlist')")
    con.execute("INSERT INTO dim_security VALUES ('SHEL.L','Shell','stock','UK','Energy','GBp','watchlist')")
    # FX: 1 USD = 0.80 GBP, 1 EUR = 0.88 GBP
    for d in ("2024-01-02", "2024-01-03"):
        con.execute("INSERT INTO fct_fx VALUES (?, 0.80, 0.88)", [d])
    # prices
    con.execute("INSERT INTO stg_equity_prices VALUES ('AAPL','2024-01-02',0,0,0,100,100,0,NULL)")
    con.execute("INSERT INTO stg_equity_prices VALUES ('AAPL','2024-01-03',0,0,0,110,110,0,NULL)")
    con.execute("INSERT INTO stg_equity_prices VALUES ('SHEL.L','2024-01-02',0,0,0,2500,2500,0,NULL)")
    con.execute("INSERT INTO stg_equity_prices VALUES ('SHEL.L','2024-01-03',0,0,0,2600,2600,0,NULL)")
    return con


def test_returns_and_currency_conversion():
    con = _con()
    for stmt in _statements(SQL):
        con.execute(stmt)

    # daily return AAPL 2024-01-03 = 110/100 - 1 = 0.10
    ret = con.execute("SELECT ret_1d FROM fct_equity_analytics "
                      "WHERE ticker='AAPL' AND price_date='2024-01-03'").fetchone()[0]
    assert abs(ret - 0.10) < 1e-9

    # USD -> GBP: 100 * 0.80 = 80
    aapl_gbp = con.execute("SELECT gbp_adj_close FROM fct_equity_analytics "
                           "WHERE ticker='AAPL' AND price_date='2024-01-02'").fetchone()[0]
    assert abs(aapl_gbp - 80.0) < 1e-9

    # GBp (pence) -> GBP: 2500 / 100 = 25
    shel_gbp = con.execute("SELECT gbp_adj_close FROM fct_equity_analytics "
                           "WHERE ticker='SHEL.L' AND price_date='2024-01-02'").fetchone()[0]
    assert abs(shel_gbp - 25.0) < 1e-9

    # metadata carried through
    grp, sector = con.execute("SELECT \"group\", sector FROM fct_equity_analytics "
                              "WHERE ticker='SHEL.L' LIMIT 1").fetchone()
    assert grp == "watchlist" and sector == "Energy"
