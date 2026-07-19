"""Test for 07_factor_scores.sql - runs the real SQL in in-memory DuckDB against
a 3-stock cross-section and checks the factor z-scores and composite. Skips if
duckdb absent."""
from pathlib import Path

import pytest

duckdb = pytest.importorskip("duckdb")

SQL = Path("src/transform/sql/07_factor_scores.sql").read_text(encoding="utf-8")


def _statements(text):
    no_comments = "\n".join(line.split("--", 1)[0] for line in text.splitlines())
    return [s.strip() for s in no_comments.split(";") if s.strip()]


def _con():
    con = duckdb.connect(":memory:")
    con.execute("""CREATE TABLE fct_equity_analytics
                   (ticker VARCHAR, price_date DATE, adj_close DOUBLE, ma_200 DOUBLE,
                    "group" VARCHAR, sector VARCHAR, ret_252d DOUBLE, vol_21d DOUBLE)""")
    # three watchlist stocks on one date:
    #   A: best momentum, lowest vol, above its MA   -> should top the composite
    #   B: middle on everything
    #   C: worst momentum, highest vol, below its MA -> should be bottom
    con.execute("INSERT INTO fct_equity_analytics VALUES ('A','2024-01-02',110,100,'watchlist','Tech', 0.30,0.01)")
    con.execute("INSERT INTO fct_equity_analytics VALUES ('B','2024-01-02',100,100,'watchlist','Tech', 0.10,0.02)")
    con.execute("INSERT INTO fct_equity_analytics VALUES ('C','2024-01-02', 90,100,'watchlist','Tech',-0.10,0.03)")
    return con


def test_factor_zscores_and_composite():
    con = _con()
    for stmt in _statements(SQL):
        con.execute(stmt)

    a = con.execute("SELECT mom_z, lowvol_z, trend_z, composite_z FROM fct_factor_scores "
                    "WHERE ticker='A'").fetchone()
    assert abs(a[0] - 1.0) < 1e-9        # momentum z
    assert abs(a[1] - 1.0) < 1e-9        # low-vol z (lowest vol -> highest score)
    assert abs(a[2] - 1.0) < 1e-9        # trend z
    assert abs(a[3] - 1.0) < 1e-9        # composite

    c_comp = con.execute("SELECT composite_z FROM fct_factor_scores WHERE ticker='C'").fetchone()[0]
    assert abs(c_comp - (-1.0)) < 1e-9

    # ordered so the strongest composite is first
    top = con.execute("SELECT ticker FROM fct_factor_scores "
                      "WHERE price_date='2024-01-02' ORDER BY composite_z DESC LIMIT 1").fetchone()[0]
    assert top == "A"
