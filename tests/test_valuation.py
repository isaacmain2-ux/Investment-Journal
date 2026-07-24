"""Test for 07_valuation.sql - runs the real SQL in in-memory DuckDB and checks the
currency-safe valuation yields, including the case that would go wrong without the
reporting-currency conversion (a USD-reporting, pence-trading UK share). Skips if
duckdb absent."""
from pathlib import Path

import pytest

duckdb = pytest.importorskip("duckdb")

SQL = Path("src/transform/sql/07_valuation.sql").read_text(encoding="utf-8")


def _statements(text):
    no_comments = "\n".join(line.split("--", 1)[0] for line in text.splitlines())
    return [s.strip() for s in no_comments.split(";") if s.strip()]


def _con():
    con = duckdb.connect(":memory:")
    con.execute("""CREATE TABLE fct_equity_analytics
                   (ticker VARCHAR, price_date DATE, "group" VARCHAR, gbp_adj_close DOUBLE)""")
    con.execute("""CREATE TABLE fct_fundamentals
                   (ticker VARCHAR, period_end DATE, available_from DATE,
                    revenue DOUBLE, net_income DOUBLE, free_cash_flow DOUBLE)""")
    con.execute("""CREATE TABLE dim_company_meta
                   (ticker VARCHAR, financial_currency VARCHAR, shares_outstanding DOUBLE)""")
    con.execute("CREATE TABLE fct_fx (date DATE, gbp_per_usd DOUBLE, gbp_per_eur DOUBLE)")
    con.execute("INSERT INTO fct_fx VALUES ('2025-06-02', 0.80, 0.88)")

    # SHEL.L: price already in GBP (25 = 2500p /100), 1000 shares -> mcap 25,000 GBP.
    # Reports in USD; net_income 5000 USD -> 4000 GBP; earnings_yield = 4000/25000 = 0.16.
    con.execute("INSERT INTO fct_equity_analytics VALUES ('SHEL.L','2025-06-02','watchlist',25.0)")
    con.execute("INSERT INTO fct_fundamentals VALUES "
                "('SHEL.L','2024-12-31','2025-03-31', 25000.0, 5000.0, 2500.0)")
    con.execute("INSERT INTO dim_company_meta VALUES ('SHEL.L','USD',1000.0)")

    # TTE.PA: EUR reporter. gbp_adj_close 44 (=EUR50 x0.88), 200 shares -> mcap 8,800.
    # net_income 1000 EUR -> 880 GBP; earnings_yield = 880/8800 = 0.10.
    con.execute("INSERT INTO fct_equity_analytics VALUES ('TTE.PA','2025-06-02','watchlist',44.0)")
    con.execute("INSERT INTO fct_fundamentals VALUES "
                "('TTE.PA','2024-12-31','2025-03-31', 8800.0, 1000.0, 500.0)")
    con.execute("INSERT INTO dim_company_meta VALUES ('TTE.PA','EUR',200.0)")
    return con


def test_currency_safe_yields():
    con = _con()
    for stmt in _statements(SQL):
        con.execute(stmt)

    mc, ey, sy, fy, vr = con.execute(
        "SELECT market_cap_gbp, earnings_yield, sales_yield, fcf_yield, value_raw "
        "FROM fct_valuation WHERE ticker='SHEL.L'").fetchone()
    assert abs(mc - 25000.0) < 1e-6            # 25 GBP/share x 1000 shares
    assert abs(ey - 0.16) < 1e-9              # 5000 USD x0.80 / 25000
    assert abs(sy - 0.80) < 1e-9              # 25000 USD x0.80 / 25000
    assert abs(fy - 0.08) < 1e-9              # 2500 USD x0.80 / 25000
    assert abs(vr - (0.16 + 0.80 + 0.08) / 3) < 1e-9

    # EUR reporter converts with the EUR cross-rate
    ey_eur = con.execute("SELECT earnings_yield FROM fct_valuation "
                         "WHERE ticker='TTE.PA'").fetchone()[0]
    assert abs(ey_eur - 0.10) < 1e-9         # 1000 EUR x0.88 / 8800


def test_missing_currency_gives_null_not_wrong():
    con = _con()
    con.execute("UPDATE dim_company_meta SET financial_currency=NULL WHERE ticker='SHEL.L'")
    for stmt in _statements(SQL):
        con.execute(stmt)
    ey = con.execute("SELECT earnings_yield FROM fct_valuation "
                     "WHERE ticker='SHEL.L'").fetchone()[0]
    assert ey is None                        # unresolved currency -> NULL, never a wrong number
