"""Test for 08_factor_scores.sql - runs the real SQL in in-memory DuckDB and checks
the cross-sectional z-scores, the POINT-IN-TIME fundamentals join, the value factor,
and that the composite averages only the factors that exist. Skips if duckdb absent."""
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
    con.execute("""CREATE TABLE fct_valuation
                   (ticker VARCHAR, price_date DATE, value_raw DOUBLE)""")
    # three stocks on one date: A best, B middle, C worst on every factor
    for tk, close, mom, vol in (("A", 110, 0.30, 0.01), ("B", 100, 0.10, 0.02),
                                ("C", 90, -0.10, 0.03)):
        con.execute("INSERT INTO fct_equity_analytics VALUES (?, '2025-06-02', ?, 100, "
                    "'watchlist','Tech', ?, ?)", [tk, close, mom, vol])
    # fundamentals: FY2024 public 2025-03-31 (eligible); FY2025 not yet public
    for tk, nm, roe in (("A", 0.30, 0.25), ("B", 0.20, 0.15), ("C", 0.10, 0.05)):
        con.execute("INSERT INTO fct_fundamentals VALUES "
                    "(?, '2024-12-31', '2025-03-31', ?, ?, 0.10, 0.12)", [tk, nm, roe])
    con.execute("INSERT INTO fct_fundamentals VALUES "
                "('A','2025-12-31','2026-03-31', 0.99, 0.99, 0.99, 0.99)")
    # valuation: A cheapest (highest yield) -> best value
    for tk, vr in (("A", 0.10), ("B", 0.06), ("C", 0.02)):
        con.execute("INSERT INTO fct_valuation VALUES (?, '2025-06-02', ?)", [tk, vr])
    return con


def test_point_in_time_join_value_and_composite():
    con = _con()
    for stmt in _statements(SQL):
        con.execute(stmt)

    # the ASOF join must pick FY2024 (public), never the future FY2025
    period = con.execute("SELECT fund_period_end FROM fct_factor_scores "
                         "WHERE ticker='A' AND price_date='2025-06-02'").fetchone()[0]
    assert str(period) == "2024-12-31"

    # A leads on every factor -> top composite; C bottom
    top = con.execute("SELECT ticker FROM fct_factor_scores "
                      "WHERE price_date='2025-06-02' ORDER BY composite_z DESC LIMIT 1").fetchone()[0]
    bottom = con.execute("SELECT ticker FROM fct_factor_scores "
                         "WHERE price_date='2025-06-02' ORDER BY composite_z ASC LIMIT 1").fetchone()[0]
    assert top == "A" and bottom == "C"

    # value factor populated and A (cheapest) scores highest on it
    a_val, b_val, c_val = (con.execute("SELECT value_z FROM fct_factor_scores WHERE ticker=?",
                                       [t]).fetchone()[0] for t in ("A", "B", "C"))
    assert abs(a_val - 1.0) < 1e-9 and abs(c_val + 1.0) < 1e-9

    # A's price and quality factors also line up
    mom_z, lowvol_z, q = con.execute("SELECT mom_z, lowvol_z, quality_z FROM fct_factor_scores "
                                     "WHERE ticker='A'").fetchone()
    assert abs(mom_z - 1.0) < 1e-9 and abs(lowvol_z - 1.0) < 1e-9 and q > 0


def test_composite_ignores_missing_factors():
    """A stock with no fundamentals or valuation still scores on its price factors."""
    con = _con()
    con.execute("DELETE FROM fct_fundamentals WHERE ticker='C'")
    con.execute("DELETE FROM fct_valuation WHERE ticker='C'")
    for stmt in _statements(SQL):
        con.execute(stmt)
    q, val, comp = con.execute("SELECT quality_z, value_z, composite_z FROM fct_factor_scores "
                               "WHERE ticker='C'").fetchone()
    assert q is None and val is None        # no fundamentals / valuation for C
    assert comp is not None                 # but it still has a composite from price factors
