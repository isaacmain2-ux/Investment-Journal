"""Test for 01_series_analytics.sql.

Runs the actual transform SQL in an in-memory DuckDB against small, known
fixtures and asserts the computed columns - including the intended-transform
driven primary_value / primary_zscore. Skips if duckdb isn't installed.
"""
import statistics
from pathlib import Path

import pytest

duckdb = pytest.importorskip("duckdb")

SQL = Path("src/transform/sql/01_series_analytics.sql").read_text(encoding="utf-8")


def _statements(text):
    no_comments = "\n".join(line.split("--", 1)[0] for line in text.splitlines())
    return [s.strip() for s in no_comments.split(";") if s.strip()]


# M1: a trending monthly series (intended_transform = yoy)
M1 = list(range(100, 115))                       # 100..114, 15 values
# L1: a mean-reverting monthly series (intended_transform = level)
L1 = [5, 7, 4, 6, 5, 8, 3, 6, 5, 7, 4, 6, 5, 8, 3]


def _fixture_con():
    con = duckdb.connect(":memory:")
    con.execute("""CREATE TABLE stg_fred_observations
                   (series_id VARCHAR, obs_date DATE, value DOUBLE, loaded_at TIMESTAMP)""")
    con.execute("""CREATE TABLE dim_fred_series
                   (series_id VARCHAR, name VARCHAR, region VARCHAR, category VARCHAR,
                    freq VARCHAR, "transform" VARCHAR, verify BOOLEAN)""")
    for sid, vals in (("M1", M1), ("L1", L1)):
        for i, v in enumerate(vals):
            year = 2020 + (i // 12)
            month = (i % 12) + 1
            con.execute("INSERT INTO stg_fred_observations VALUES (?, ?, ?, NULL)",
                        [sid, f"{year}-{month:02d}-01", float(v)])
    con.execute("""INSERT INTO dim_fred_series VALUES
                   ('M1','Trending','US','growth','M','yoy',FALSE),
                   ('L1','Mean-reverting','US','growth','M','level',FALSE)""")
    return con


def test_analytics_maths_and_primary():
    con = _fixture_con()
    for stmt in _statements(SQL):
        con.execute(stmt)

    # reconciliation: one analytics row per staging row
    assert con.execute("SELECT count(*) FROM fct_series_analytics").fetchone()[0] == len(M1) + len(L1)

    # M1 period change is +1 everywhere after the first row
    chgs = [r[0] for r in con.execute(
        "SELECT chg FROM fct_series_analytics WHERE series_id='M1' AND prev_value IS NOT NULL "
        "ORDER BY obs_date").fetchall()]
    assert all(abs(c - 1.0) < 1e-9 for c in chgs)

    # M1 YoY at 2021-01-01 (112) vs 2020-01-01 (100) = 0.12; primary_value IS the YoY
    yoy, prim = con.execute(
        "SELECT chg_yoy, primary_value FROM fct_series_analytics "
        "WHERE series_id='M1' AND obs_date='2021-01-01'").fetchone()
    assert abs(yoy - 0.12) < 1e-9
    assert abs(prim - 0.12) < 1e-9

    # M1 metadata propagated
    freq, itransform = con.execute(
        "SELECT freq, intended_transform FROM fct_series_analytics WHERE series_id='M1' LIMIT 1").fetchone()
    assert freq == "M" and itransform == "yoy"

    # M1 expanding level z-score at the final row matches a hand computation
    z = con.execute("SELECT zscore FROM fct_series_analytics "
                    "WHERE series_id='M1' AND obs_date='2021-03-01'").fetchone()[0]
    expected_z = (M1[-1] - statistics.mean(M1)) / statistics.stdev(M1)
    assert abs(z - expected_z) < 1e-9

    # L1 is a level series: primary_value == value and primary_zscore == zscore
    rows = con.execute(
        "SELECT value, primary_value, zscore, primary_zscore FROM fct_series_analytics "
        "WHERE series_id='L1' ORDER BY obs_date").fetchall()
    for value, primary_value, zscore, primary_zscore in rows:
        assert abs(primary_value - value) < 1e-9
        if zscore is None:
            assert primary_zscore is None
        else:
            assert abs(primary_zscore - zscore) < 1e-9

    con.close()
