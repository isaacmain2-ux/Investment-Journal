"""Test for 12_skew.sql - runs the real SQL in in-memory DuckDB. Checks expanding
point-in-time z & percentile and day-over-day change. Skips if duckdb absent."""
import datetime as dt
from pathlib import Path
import pytest

duckdb = pytest.importorskip("duckdb")
SQL = Path("src/transform/sql/12_skew.sql").read_text(encoding="utf-8")


def _statements(text):
    nc = "\n".join(l.split("--", 1)[0] for l in text.splitlines())
    return [s.strip() for s in nc.split(";") if s.strip()]


def _con():
    con = duckdb.connect(":memory:")
    con.execute("""CREATE TABLE stg_options_skew (ticker_id VARCHAR, ticker VARCHAR,
        capture_date DATE, expiry VARCHAR, dte INTEGER, spot DOUBLE, atm_iv DOUBLE,
        put_iv DOUBLE, call_iv DOUBLE, put_skew DOUBLE, risk_reversal DOUBLE)""")
    rows = [("spx", "2026-08-02", 0.05), ("spx", "2026-08-03", 0.08),
            ("spx", "2026-08-04", 0.06), ("spx", "2026-08-05", 0.10)]
    con.executemany("INSERT INTO stg_options_skew (ticker_id, ticker, capture_date, put_skew, "
                    "risk_reversal) VALUES (?, 'SPY', ?, ?, ?)",
                    [(t, d, ps, ps + 0.04) for (t, d, ps) in rows])
    return con


def _build(con):
    for s in _statements(SQL):
        con.execute(s)


def _get(con, d):
    return con.execute("SELECT put_skew, put_skew_z, put_skew_pctile, put_skew_chg "
                       f"FROM fct_skew WHERE capture_date = DATE '{d}'").fetchone()


def test_pctile_point_in_time():
    con = _con(); _build(con)
    assert abs(_get(con, "2026-08-04")[2] - 2 / 3) < 1e-9     # 0.06 is 2nd of {0.05,0.08,0.06}
    assert abs(_get(con, "2026-08-05")[2] - 1.0) < 1e-9       # 0.10 is the max so far


def test_z_point_in_time():
    con = _con(); _build(con)
    assert _get(con, "2026-08-02")[1] is None                # 1 obs -> undefined
    assert _get(con, "2026-08-03")[1] > 0                     # 0.08 above running mean


def test_change():
    con = _con(); _build(con)
    assert _get(con, "2026-08-02")[3] is None
    assert abs(_get(con, "2026-08-05")[3] - 0.04) < 1e-9      # 0.10 - 0.06
