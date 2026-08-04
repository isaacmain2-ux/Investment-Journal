"""Test for 10_vol_term.sql - runs the real SQL in in-memory DuckDB. Checks the
contango/backwardation ratio, the banded state, and the cross-asset pivot.
Skips if duckdb is absent."""
from datetime import date
from pathlib import Path
import pytest

duckdb = pytest.importorskip("duckdb")
SQL = Path("src/transform/sql/10_vol_term.sql").read_text(encoding="utf-8")


def _statements(text):
    nc = "\n".join(l.split("--", 1)[0] for l in text.splitlines())
    return [s.strip() for s in nc.split(";") if s.strip()]


def _con():
    con = duckdb.connect(":memory:")
    con.execute("CREATE TABLE stg_fred_observations (series_id VARCHAR, obs_date DATE, value DOUBLE)")
    con.executemany("INSERT INTO stg_fred_observations VALUES (?,?,?)", [
        ("VIXCLS", "2026-01-05", 14.0), ("VXVCLS", "2026-01-05", 17.0),   # contango
        ("OVXCLS", "2026-01-05", 30.0), ("GVZCLS", "2026-01-05", 15.0),
        ("VIXCLS", "2026-01-06", 28.0), ("VXVCLS", "2026-01-06", 26.0),   # backwardation
        ("VIXCLS", "2026-01-07", 19.4), ("VXVCLS", "2026-01-07", 20.0),   # flat (0.97)
    ])
    return con


def _build(con):
    for s in _statements(SQL):
        con.execute(s)


def test_contango_row():
    con = _con(); _build(con)
    vix, vix3m, ratio, state = con.execute(
        "SELECT vix, vix3m, vix_ts_ratio, ts_state FROM fct_vol_term WHERE date=DATE '2026-01-05'").fetchone()
    assert (vix, vix3m) == (14.0, 17.0)
    assert abs(ratio - 14 / 17) < 1e-9
    assert state == "contango"


def test_backwardation_row():
    con = _con(); _build(con)
    assert con.execute("SELECT ts_state FROM fct_vol_term WHERE date=DATE '2026-01-06'").fetchone()[0] == "backwardation"


def test_flat_row():
    con = _con(); _build(con)
    assert con.execute("SELECT ts_state FROM fct_vol_term WHERE date=DATE '2026-01-07'").fetchone()[0] == "flat"


def test_cross_asset_columns():
    con = _con(); _build(con)
    ovx, gvz = con.execute(
        "SELECT ovx, gvz FROM fct_vol_term WHERE date=DATE '2026-01-05'").fetchone()
    assert (ovx, gvz) == (30.0, 15.0)


def test_row_count():
    con = _con(); _build(con)
    assert con.execute("SELECT count(*) FROM fct_vol_term").fetchone()[0] == 3


def test_curve_has_inflation_forwards():
    """02_curve.sql now pivots the 5y inflation/real term-structure series."""
    curve_sql = Path("src/transform/sql/02_curve.sql").read_text(encoding="utf-8")
    for ident in ("DFII5", "T5YIE", "T5YIFR", "breakeven_5y5y", "real_5y"):
        assert ident in curve_sql
