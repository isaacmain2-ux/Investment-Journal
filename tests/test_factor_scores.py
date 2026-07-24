"""Test for 08_factor_scores.sql - runs the real SQL in in-memory DuckDB and checks
the cross-sectional z-scores, the POINT-IN-TIME fundamentals join, and that the
composite averages only the factors that exist. Skips if duckdb absent."""
from pathlib import Path

import pytest

duckdb = pytest.importorskip("duckdb")

SQL = Path("src/transform/sql/08_factor_scores.sql").read_text(encoding="utf-8")


def _statements(text):
    no_comments = "\n".join(line.split("--", 1)[0] for line in text.splitlines())
    return [s.strip() for s in no_comments.split(";") if s.strip()]


def _con():
    con = duckdb.connect(":memory:")
    con.execute("""CREATE TABLE fct_equity_analytics
                   (ticker VARCHAR, price_date DATE, adj_close DOUBLE, ma_200 DOUBLE,
                    "group" VARCHAR, sector VARCHAR, ret_252d DOUBLE, vol_21d DOUBLE)""")
    con.execute("""CREATE TABLE fct_fundamentals
                   (ticker VARCHAR, period_end DATE, available_from DATE,
                    net_margin DOUBLE, roe DOUBLE,
                    revenue_growth_yoy DOUBLE, eps_growth_yoy DOUBLE)""")
    # three stocks on one date: A best, B middle, C worst on the price factors
    for tk, close, mom, vol in (("A", 110, 0.30, 0.01), ("B", 100, 0.10, 0.02),
                                ("C", 90, -0.10, 0.03)):
        con.execute("INSERT INTO fct_equity_analytics VALUES (?, '2025-06-02', ?, 100, "
                    "'watchlist','Tech', ?, ?)", [tk, close, mom, vol])
    # fundamentals: FY2024 published 2025-03-31 (eligible), FY2025 not yet public
    for tk, nm, roe in (("A", 0.30, 0.25), ("B", 0.20, 0.15), ("C", 0.10, 0.05)):
        con.execute("INSERT INTO fct_fundamentals VALUES "
                    "(?, '2024-12-31', '2025-03-31', ?, ?, 0.10, 0.12)", [tk, nm, roe])
    con.execute("INSERT INTO fct_fundamentals VALUES "
                "('A','2025-12-31','2026-03-31', 0.99, 0.99, 0.99, 0.99)")
    return con


def test_point_in_time_join_and_composite():
    con = _con()
    for stmt in _statements(SQL):
        con.execute(stmt)

    # the ASOF join must pick FY2024 (public), never the future FY2025 row
    period = con.execute("SELECT fund_period_end FROM fct_factor_scores "
                         "WHERE ticker='A' AND price_date='2025-06-02'").fetchone()[0]
    assert str(period) == "2024-12-31"

    # A leads on every factor -> top composite; C bottom
    top = con.execute("SELECT ticker FROM fct_factor_scores "
                      "WHERE price_date='2025-06-02' ORDER BY composite_z DESC LIMIT 1"
                      ).fetchone()[0]
    bottom = con.execute("SELECT ticker FROM fct_factor_scores "
                         "WHERE price_date='2025-06-02' ORDER BY composite_z ASC LIMIT 1"
                         ).fetchone()[0]
    assert top == "A" and bottom == "C"

    # quality and growth columns are populated (fundamentals actually joined)
    q, g = con.execute("SELECT quality_z, growth_z FROM fct_factor_scores "
                       "WHERE ticker='A'").fetchone()
    assert q is not None and q > 0

    # A's factor z-scores are each +1 across three evenly spaced stocks
    mom_z, lowvol_z = con.execute("SELECT mom_z, lowvol_z FROM fct_factor_scores "
                                  "WHERE ticker='A'").fetchone()
    assert abs(mom_z - 1.0) < 1e-9
    assert abs(lowvol_z - 1.0) < 1e-9      # lowest vol -> highest score


def test_composite_ignores_missing_factors():
    """A stock with no fundamentals still scores on its price factors alone."""
    con = _con()
    con.execute("DELETE FROM fct_fundamentals WHERE ticker='C'")
    for stmt in _statements(SQL):
        con.execute(stmt)
    q, comp = con.execute("SELECT quality_z, composite_z FROM fct_factor_scores "
                          "WHERE ticker='C'").fetchone()
    assert q is None                        # no fundamentals for C
    assert comp is not None                 # but it still has a composite
