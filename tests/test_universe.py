"""Tests for the universe helper's parsing and the ingest orchestrator (all mocked)."""
import datetime as dt
import pytest
from src.extract import fetch_sp500_universe as U


def test_to_constituents_maps_columns():
    pd = pytest.importorskip("pandas")
    df = pd.DataFrame({"Symbol": ["AAPL", "MSFT"], "Security": ["Apple Inc.", "Microsoft Corp"],
                       "GICS Sector": ["Information Technology", "Information Technology"],
                       "CIK": [320193, 789019]})
    rows = U.to_constituents(df)
    assert rows[0] == {"ticker": "AAPL", "name": "Apple Inc.",
                       "sector": "Information Technology", "cik": "0000320193"}
    assert rows[1]["ticker"] == "MSFT" and rows[1]["cik"] == "0000789019"


# ---- orchestrator ----
duckdb = pytest.importorskip("duckdb")
from src.extract import universe_ingest as UI
from src.extract.sec_client import SecResult

CFG = {"meta": {"universe": "sp500", "constituents": "x.csv", "price_suffix": "us",
                "sec_user_agent": "Investment Journal/1.0 (me@real.com)"}}
NAMES = [{"ticker": "AAPL", "name": "Apple", "sector": "Tech", "cik": "0000320193"},
         {"ticker": "MSFT", "name": "Microsoft", "sector": "Tech", "cik": "0000789019"}]


class _NoClose:
    def __init__(self, con): self._c = con
    def __getattr__(self, k): return getattr(self._c, k)
    def close(self): pass


def _price_rows(tk):
    return [{"ticker": tk, "date": dt.date(2026, 8, 3), "open": 1, "high": 2, "low": 1,
             "close": 1.5, "volume": 100}]


def _fund_rows(tk):
    return [{"ticker": tk, "cik": "0000320193", "metric": "revenue", "xbrl_tag": "Revenues",
             "period_end": dt.date(2023, 9, 30), "fiscal_year": 2023, "fiscal_period": "FY",
             "form": "10-K", "filed_date": dt.date(2023, 11, 3), "unit": "USD", "value": 1e9}]


def _wire(monkeypatch):
    con = _NoClose(duckdb.connect(":memory:"))
    monkeypatch.setattr(UI, "get_connection", lambda: con)
    monkeypatch.setattr(UI, "load_securities_universe", lambda _p: CFG)
    monkeypatch.setattr(UI, "read_constituents", lambda _p: [dict(n) for n in NAMES])
    monkeypatch.setattr(UI.yahoo_prices, "fetch_prices_batch",
                        lambda tickers, start="2015-01-01", **k: (
                            [r for t in tickers for r in _price_rows(t)], []))
    monkeypatch.setattr(UI.sec_client, "fetch_fundamentals",
                        lambda tk, cik, ua, **k: SecResult(tk, cik, rows=_fund_rows(tk)))
    return con


def test_orchestrator_populates_all_three_tables(monkeypatch):
    con = _wire(monkeypatch)
    assert UI.run() == 0
    assert con.execute("SELECT count(*) FROM dim_security").fetchone()[0] == 2
    assert con.execute("SELECT count(*) FROM stg_security_prices").fetchone()[0] == 2
    assert con.execute("SELECT count(*) FROM stg_security_fundamentals").fetchone()[0] == 2


def test_only_filter(monkeypatch):
    con = _wire(monkeypatch)
    UI.run(only=["AAPL"])
    assert con.execute("SELECT count(*) FROM stg_security_prices").fetchone()[0] == 1
    assert con.execute("SELECT ticker FROM stg_security_prices").fetchone()[0] == "AAPL"


def test_no_fundamentals_flag(monkeypatch):
    con = _wire(monkeypatch)
    UI.run(fundamentals=False)
    assert con.execute("SELECT count(*) FROM stg_security_prices").fetchone()[0] == 2
    assert con.execute("SELECT count(*) FROM stg_security_fundamentals").fetchone()[0] == 0


def test_placeholder_user_agent_is_refused(monkeypatch):
    con = _wire(monkeypatch)
    monkeypatch.setattr(UI, "load_securities_universe",
                        lambda _p: {"meta": {**CFG["meta"], "sec_user_agent": "x (your-email@example.com)"}})
    assert UI.run() == 1                       # refuses to hit SEC with the placeholder UA