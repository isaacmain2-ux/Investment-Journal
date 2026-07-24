"""Test for 07_fundamentals.sql - runs the real SQL in in-memory DuckDB against a
fixture and checks the currency-safe ratios, YoY growth, and that a bank (no gross
profit) still gets its other ratios. Skips if duckdb absent."""
from pathlib import Path

import pytest

duckdb = pytest.importorskip("duckdb")

SQL = Path("src/transform/sql/07_fundamentals.sql").read_text(encoding="utf-8")


def _statements(text):
    no_comments = "\n".join(line.split("--", 1)[0] for line in text.splitlines())
    return [s.strip() for s in no_comments.split(";") if s.strip()]


def _con():
    con = duckdb.connect(":memory:")
    con.execute("""CREATE TABLE stg_fundamentals
                   (ticker VARCHAR, statement VARCHAR, freq VARCHAR, metric VARCHAR,
                    period_end DATE, available_from DATE, value DOUBLE, loaded_at TIMESTAMP)""")

    def ins(ticker, period, avail, pairs):
        for metric, val in pairs.items():
            con.execute("INSERT INTO stg_fundamentals VALUES (?,?,?,?,?,?,?,NULL)",
                        [ticker, "income", "annual", metric, period, avail, val])

    # ACME: two years, full income + balance data
    ins("ACME", "2023-12-31", "2024-03-30", {
        "Total Revenue": 380.0, "Gross Profit": 170.0, "Operating Income": 80.0,
        "Net Income Common Stockholders": 90.0, "Diluted EPS": 5.9,
        "Stockholders Equity": 75.0, "Total Assets": 340.0, "Total Debt": 150.0})
    ins("ACME", "2024-12-31", "2025-03-31", {
        "Total Revenue": 400.0, "Gross Profit": 180.0, "Operating Income": 90.0,
        "Net Income Common Stockholders": 100.0, "Diluted EPS": 6.5,
        "Stockholders Equity": 80.0, "Total Assets": 360.0, "Total Debt": 160.0})
    # BANK: no gross profit line (as real banks don't report one)
    ins("BANK", "2024-12-31", "2025-03-31", {
        "Total Revenue": 200.0, "Net Income Common Stockholders": 50.0,
        "Stockholders Equity": 250.0, "Total Assets": 3000.0})
    return con


def test_ratios_growth_and_bank_nulls():
    con = _con()
    for stmt in _statements(SQL):
        con.execute(stmt)

    row = con.execute("""SELECT net_margin, roe, roa, gross_margin, debt_to_equity,
                                revenue_growth_yoy, eps_growth_yoy
                         FROM fct_fundamentals
                         WHERE ticker='ACME' AND period_end='2024-12-31'""").fetchone()
    net_margin, roe, roa, gross_margin, d2e, rev_g, eps_g = row
    assert abs(net_margin - 100 / 400) < 1e-9
    assert abs(roe - 100 / 80) < 1e-9
    assert abs(roa - 100 / 360) < 1e-9
    assert abs(gross_margin - 180 / 400) < 1e-9
    assert abs(d2e - 160 / 80) < 1e-9
    assert abs(rev_g - (400 / 380 - 1)) < 1e-9        # YoY vs the prior period
    assert abs(eps_g - (6.5 / 5.9 - 1)) < 1e-9

    # the first period has no prior year -> growth is NULL, not an error
    first_g = con.execute("SELECT revenue_growth_yoy FROM fct_fundamentals "
                          "WHERE ticker='ACME' AND period_end='2023-12-31'").fetchone()[0]
    assert first_g is None

    # bank: gross margin NULL by nature, but net margin / ROE still computed
    b_gross, b_net, b_roe = con.execute(
        "SELECT gross_margin, net_margin, roe FROM fct_fundamentals "
        "WHERE ticker='BANK'").fetchone()
    assert b_gross is None
    assert abs(b_net - 50 / 200) < 1e-9
    assert abs(b_roe - 50 / 250) < 1e-9

    # point-in-time date carried through
    avail = con.execute("SELECT available_from FROM fct_fundamentals "
                        "WHERE ticker='ACME' AND period_end='2024-12-31'").fetchone()[0]
    assert str(avail) == "2025-03-31"
