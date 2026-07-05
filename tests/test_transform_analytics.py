"""Test for 01_series_analytics.sql.

Runs the actual transform SQL in an in-memory DuckDB against a small, known
fixture and asserts the computed columns. Skips cleanly if duckdb isn't
installed (it is on the project machine).
"""
import statistics
from pathlib import Path

import pytest

duckdb = pytest.importorskip("duckdb")

SQL = Path("src/transform/sql/01_series_analytics.sql").read_text(encoding="utf-8")


def _statements(text):
    return [s.strip() for s in text.split(";") if s.strip()]


def _fixture_con():
    con = duckdb.connect(":memory:")
    con.execute("""CREATE TABLE stg_fred_observations
                   (series_id VARCHAR, obs_date DATE, value DOUBLE, loaded_at TIMESTAMP)""")
    con.execute("""CREATE TABLE dim_fred_series
                   (series_id VARCHAR, name VARCHAR, region VARCHAR, category VARCHAR,
                    freq VARCHAR, "transform" VARCHAR, verify BOOLEAN)""")
    # a 15-month monthly series: 100, 101, ... 114 on the 1st of each month
    vals = list(range(100, 115))          # 15 values
    for i, v in enumerate(vals):
        year = 2020 + (i // 12)
        month = (i % 12) + 1
        con.execute("INSERT INTO stg_fred_observations VALUES (?, ?, ?, NULL)",
                    ["M1", f"{year}-{month:02d}-01", float(v)])
    con.execute("""INSERT INTO dim_fred_series
                   VALUES ('M1','Test monthly','US','growth','M','yoy',FALSE)""")
    return con, vals


def test_analytics_columns_and_maths():
    con, vals = _fixture_con()
    for stmt in _statements(SQL):
        con.execute(stmt)

    # reconciliation: one analytics row per staging row
    n = con.execute("SELECT count(*) FROM fct_series_analytics").fetchone()[0]
    assert n == len(vals)

    # period change is +1 everywhere after the first row
    chgs = [r[0] for r in con.execute(
        "SELECT chg FROM fct_series_analytics WHERE prev_value IS NOT NULL "
        "ORDER BY obs_date").fetchall()]
    assert all(abs(c - 1.0) < 1e-9 for c in chgs)

    # YoY at 2021-01-01 (value 112) vs 2020-01-01 (value 100) = 0.12
    yoy = con.execute(
        "SELECT chg_yoy FROM fct_series_analytics WHERE obs_date = '2021-01-01'"
    ).fetchone()[0]
    assert abs(yoy - 0.12) < 1e-9

    # metadata propagated
    freq, itransform = con.execute(
        "SELECT freq, intended_transform FROM fct_series_analytics LIMIT 1").fetchone()
    assert freq == "M" and itransform == "yoy"

    # expanding z-score at the final row matches a hand computation
    z = con.execute(
        "SELECT zscore FROM fct_series_analytics WHERE obs_date = '2021-03-01'"
    ).fetchone()[0]
    mean = statistics.mean(vals)
    sd = statistics.stdev(vals)               # sample sd (ddof=1), matches STDDEV_SAMP
    expected_z = (vals[-1] - mean) / sd
    assert abs(z - expected_z) < 1e-9

    con.close()
