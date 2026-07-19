"""Test for 06_relative_strength.sql - runs the real SQL in in-memory DuckDB
against a fixture and checks excess return and the relative-price ratio.
Skips if duckdb absent."""
from pathlib import Path

import pytest

duckdb = pytest.importorskip("duckdb")

SQL = Path("src/transform/sql/06_relative_strength.sql").read_text(encoding="utf-8")


def _statements(text):
    no_comments = "\n".join(line.split("--", 1)[0] for line in text.splitlines())
    return [s.strip() for s in no_comments.split(";") if s.strip()]


def _con():
    con = duckdb.connect(":memory:")
    # a minimal fct_equity_analytics with just the columns 06 reads
    con.execute("""CREATE TABLE fct_equity_analytics
                   (ticker VARCHAR, price_date DATE, adj_close DOUBLE,
                    "group" VARCHAR, sector VARCHAR,
                    ret_21d DOUBLE, ret_63d DOUBLE, ret_252d DOUBLE)""")
    # market (S&P 500): +5% over 63d
    con.execute("INSERT INTO fct_equity_analytics VALUES "
                "('^GSPC','2024-01-02',5000,'indices',NULL,0.02,0.05,0.10)")
    # a sector ETF: +8% over 63d -> excess = +3%
    con.execute("INSERT INTO fct_equity_analytics VALUES "
                "('XLK','2024-01-02',200,'sector_etfs','Technology',0.03,0.08,0.15)")
    # a style ETF that lags: +2% over 63d -> excess = -3%
    con.execute("INSERT INTO fct_equity_analytics VALUES "
                "('VLUE','2024-01-02',100,'style_etfs','Factor',0.01,0.02,0.06)")
    return con


def test_excess_and_relative_ratio():
    con = _con()
    for stmt in _statements(SQL):
        con.execute(stmt)

    # XLK: excess_63d = 0.08 - 0.05 = 0.03 ; rel_close = 200 / 5000 = 0.04
    xlk = con.execute("SELECT excess_63d, rel_close FROM fct_relative_strength "
                      "WHERE ticker='XLK' AND price_date='2024-01-02'").fetchone()
    assert abs(xlk[0] - 0.03) < 1e-9
    assert abs(xlk[1] - 0.04) < 1e-9

    # VLUE lags the market: negative excess
    vlue_excess = con.execute("SELECT excess_63d FROM fct_relative_strength "
                              "WHERE ticker='VLUE' AND price_date='2024-01-02'").fetchone()[0]
    assert abs(vlue_excess - (-0.03)) < 1e-9

    # the market itself is not in the rotation table (only sector/style/country ETFs)
    n_mkt = con.execute("SELECT count(*) FROM fct_relative_strength WHERE ticker='^GSPC'").fetchone()[0]
    assert n_mkt == 0
