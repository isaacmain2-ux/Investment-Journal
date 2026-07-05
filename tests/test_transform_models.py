"""Tests for 02_curve.sql, 03_credit.sql, 04_fx.sql.

Each runs the real SQL in an in-memory DuckDB against a tiny fixture and checks
the derived arithmetic (slopes, spreads, cross-rates). Skips if duckdb absent.
"""
from pathlib import Path

import pytest

duckdb = pytest.importorskip("duckdb")


def _statements(path):
    text = Path(path).read_text(encoding="utf-8")
    no_comments = "\n".join(line.split("--", 1)[0] for line in text.splitlines())
    return [s.strip() for s in no_comments.split(";") if s.strip()]


def _con_with(series_rows):
    """series_rows: list of (series_id, date_str, value)."""
    con = duckdb.connect(":memory:")
    con.execute("""CREATE TABLE stg_fred_observations
                   (series_id VARCHAR, obs_date DATE, value DOUBLE, loaded_at TIMESTAMP)""")
    for sid, d, v in series_rows:
        con.execute("INSERT INTO stg_fred_observations VALUES (?, ?, ?, NULL)", [sid, d, float(v)])
    return con


def _run(con, path):
    for stmt in _statements(path):
        con.execute(stmt)


def test_curve_pivots_and_slope():
    con = _con_with([
        ("DGS2", "2026-01-02", 4.0), ("DGS10", "2026-01-02", 4.5),
        ("DGS3MO", "2026-01-02", 4.2), ("DGS5", "2026-01-02", 4.3),
        ("DGS30", "2026-01-02", 4.7), ("T10Y2Y", "2026-01-02", 0.5),
        ("T10Y3M", "2026-01-02", 0.3), ("DFII10", "2026-01-02", 2.0),
        ("T10YIE", "2026-01-02", 2.5), ("THREEFYTP10", "2026-01-02", 0.1),
    ])
    _run(con, "src/transform/sql/02_curve.sql")
    row = con.execute("""SELECT y2, y10, slope_2s10s, slope_2s10s_calc, real_10y, breakeven_10y
                         FROM fct_curve WHERE date='2026-01-02'""").fetchone()
    y2, y10, slope_fred, slope_calc, real10, be10 = row
    assert (y2, y10) == (4.0, 4.5)
    assert abs(slope_calc - (y10 - y2)) < 1e-9        # computed 2s10s = 0.5
    assert abs(slope_fred - 0.5) < 1e-9               # FRED's T10Y2Y agrees
    assert real10 == 2.0 and be10 == 2.5


def test_credit_spreads():
    con = _con_with([
        ("BAMLC0A0CM", "2026-01-02", 1.0),    # IG
        ("BAMLH0A0HYM2", "2026-01-02", 3.5),  # HY
        ("BAMLH0A1HYBB", "2026-01-02", 2.5),  # BB
        ("BAMLH0A3HYC", "2026-01-02", 8.0),   # CCC
        ("BAMLC0A4CBBB", "2026-01-02", 1.4),
        ("BAMLC0A1CAAA", "2026-01-02", 0.6),
        ("BAMLEMCBPIOAS", "2026-01-02", 3.0),
    ])
    _run(con, "src/transform/sql/03_credit.sql")
    ig_hy, quality = con.execute(
        "SELECT ig_hy_spread, quality_spread FROM fct_credit WHERE date='2026-01-02'").fetchone()
    assert abs(ig_hy - (3.5 - 1.0)) < 1e-9            # HY - IG = 2.5
    assert abs(quality - (8.0 - 2.5)) < 1e-9          # CCC - BB = 5.5


def test_fx_cross_rates():
    con = _con_with([
        ("DEXUSUK", "2026-01-02", 1.25),   # USD per GBP
        ("DEXUSEU", "2026-01-02", 1.10),   # USD per EUR
    ])
    _run(con, "src/transform/sql/04_fx.sql")
    gbp_usd, eur_gbp, gbp_eur = con.execute(
        "SELECT gbp_per_usd, eur_per_gbp, gbp_per_eur FROM fct_fx WHERE date='2026-01-02'").fetchone()
    assert abs(gbp_usd - 1 / 1.25) < 1e-9
    assert abs(eur_gbp - 1.25 / 1.10) < 1e-9
    assert abs(gbp_eur - 1.10 / 1.25) < 1e-9
