"""Test for 11_positioning.sql - runs the real SQL in in-memory DuckDB. Checks net
positioning, %-of-OI, expanding point-in-time z & percentile, and WoW. Skips if
duckdb absent."""
import datetime as dt
from pathlib import Path
import pytest

duckdb = pytest.importorskip("duckdb")
SQL = Path("src/transform/sql/11_positioning.sql").read_text(encoding="utf-8")


def _statements(text):
    nc = "\n".join(l.split("--", 1)[0] for l in text.splitlines())
    return [s.strip() for s in nc.split(";") if s.strip()]


def _con():
    con = duckdb.connect(":memory:")
    con.execute("""CREATE TABLE stg_cot (market_id VARCHAR, market VARCHAR, report_date DATE,
        available_from DATE, open_interest BIGINT, lev_long BIGINT, lev_short BIGINT,
        lev_spread BIGINT, am_long BIGINT, am_short BIGINT, dealer_long BIGINT, dealer_short BIGINT)""")
    rows = [  # net_lev sequence: -100, 0, 100, 60
        ("sp500", "2026-07-07", 1000, 100, 200), ("sp500", "2026-07-14", 1000, 150, 150),
        ("sp500", "2026-07-21", 1000, 200, 100), ("sp500", "2026-07-28", 1000, 180, 120)]
    con.executemany("INSERT INTO stg_cot (market_id, market, report_date, available_from, "
        "open_interest, lev_long, lev_short, am_long, am_short) VALUES (?,?,?,?,?,?,?,?,?)",
        [(m, m, d, d, oi, ll, ls, 0, 0) for (m, d, oi, ll, ls) in rows])
    return con


def _build(con):
    for s in _statements(SQL):
        con.execute(s)


def _get(con, d):
    return con.execute("SELECT net_lev, net_lev_pct_oi, net_lev_z, net_lev_pctile, net_lev_wow "
                       f"FROM fct_positioning WHERE report_date = DATE '{d}'").fetchone()


def test_net_and_pct_oi():
    con = _con(); _build(con)
    net, pct, *_ = _get(con, "2026-07-21")
    assert net == 100 and abs(pct - 0.1) < 1e-9


def test_expanding_pctile_point_in_time():
    con = _con(); _build(con)
    assert abs(_get(con, "2026-07-14")[3] - 1.0) < 1e-9      # 0 is the max so far
    assert abs(_get(con, "2026-07-28")[3] - 0.75) < 1e-9     # 60 is 3rd of 4


def test_expanding_z_point_in_time():
    con = _con(); _build(con)
    assert _get(con, "2026-07-07")[2] is None                # 1 obs -> undefined
    assert abs(_get(con, "2026-07-21")[2] - 1.0) < 1e-6      # (100-0)/100


def test_wow():
    con = _con(); _build(con)
    assert _get(con, "2026-07-07")[4] is None
    assert _get(con, "2026-07-28")[4] == -40                 # 60 - 100


def test_available_from_carried():
    con = _con(); _build(con)
    assert con.execute("SELECT count(available_from) FROM fct_positioning").fetchone()[0] == 4
