"""Tests for src/load/load_securities.py against a DuckDB-compatible connection."""
import datetime as dt
import pytest
duckdb = pytest.importorskip("duckdb")
from src.load import load_securities as L


def _con():
    con = duckdb.connect(":memory:"); L.ensure_schema(con); return con


def _fund(ticker="AAPL", metric="revenue", pend=dt.date(2023,9,30), fp="FY",
          filed=dt.date(2023,11,3), val=383285e6):
    return {"ticker":ticker,"cik":"0000320193","metric":metric,"xbrl_tag":"Revenues",
            "period_end":pend,"fiscal_year":2023,"fiscal_period":fp,"form":"10-K",
            "filed_date":filed,"unit":"USD","value":val}


def _price(ticker="AAPL", d=dt.date(2026,8,3), close=190.0):
    return {"ticker":ticker,"date":d,"open":189.0,"high":191.0,"low":188.0,"close":close,"volume":1e6}


def test_upsert_securities():
    con=_con()
    n=L.upsert_securities(con,[{"ticker":"AAPL","name":"Apple","sector":"Tech","industry":"HW","cik":320193},
                               {"ticker":"MSFT","name":"Microsoft","sector":"Tech","cik":789019}])
    assert n==2
    sec,cik=con.execute("SELECT sector,cik FROM dim_security WHERE ticker='AAPL'").fetchone()
    assert sec=="Tech" and cik=="0000320193"
    # re-upsert replaces, no dup
    L.upsert_securities(con,[{"ticker":"AAPL","name":"Apple Inc","sector":"Technology","cik":320193}])
    assert con.execute("SELECT count(*) FROM dim_security").fetchone()[0]==2
    assert con.execute("SELECT sector FROM dim_security WHERE ticker='AAPL'").fetchone()[0]=="Technology"


def test_load_prices_idempotent_and_accumulates():
    con=_con()
    assert L.load_prices(con,[_price(d=dt.date(2026,8,3))])==(1,1)
    assert L.load_prices(con,[_price(d=dt.date(2026,8,3),close=195.0)])==(1,0)   # same day replaces
    assert con.execute("SELECT close FROM stg_security_prices").fetchone()[0]==195.0
    assert L.load_prices(con,[_price(d=dt.date(2026,8,4))])==(1,1)               # new day accumulates
    assert con.execute("SELECT count(*) FROM stg_security_prices").fetchone()[0]==2


def test_load_fundamentals_keeps_latest_filed():
    con=_con()
    assert L.load_fundamentals(con,[_fund(filed=dt.date(2023,11,3),val=100)])==(1,1)
    # a restatement of the SAME period, filed later, wins
    assert L.load_fundamentals(con,[_fund(filed=dt.date(2024,2,1),val=110)])==(1,0)
    assert con.execute("SELECT count(*) FROM stg_security_fundamentals").fetchone()[0]==1
    assert con.execute("SELECT value FROM stg_security_fundamentals").fetchone()[0]==110


def test_load_fundamentals_batch_picks_latest():
    con=_con()
    # two filings of the same period in one batch -> latest filed kept
    n_seen,n_new=L.load_fundamentals(con,[_fund(filed=dt.date(2023,11,3),val=100),
                                          _fund(filed=dt.date(2024,2,1),val=110)])
    assert (n_seen,n_new)==(1,1)
    assert con.execute("SELECT value FROM stg_security_fundamentals").fetchone()[0]==110


def test_load_fundamentals_distinct_periods_accumulate():
    con=_con()
    L.load_fundamentals(con,[_fund(pend=dt.date(2023,9,30)),_fund(pend=dt.date(2022,9,30))])
    assert con.execute("SELECT count(*) FROM stg_security_fundamentals").fetchone()[0]==2


def test_load_fundamentals_skips_null_value():
    con=_con()
    assert L.load_fundamentals(con,[_fund(val=None)])==(0,0)
