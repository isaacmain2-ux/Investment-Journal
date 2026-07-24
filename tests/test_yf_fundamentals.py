"""Tests for src/extract/yf_fundamentals.py - the network call is mocked, so
these run offline."""
import datetime as dt

import pandas as pd

from src.extract import yf_fundamentals
from src.extract.yf_fundamentals import fetch_fundamentals, REPORTING_LAG_DAYS


def _statement_frame():
    """Yahoo shape: metrics as the index, period-end dates as columns."""
    return pd.DataFrame(
        {pd.Timestamp("2024-12-31"): [1000.0, 250.0],
         pd.Timestamp("2023-12-31"): [900.0, float("nan")]},   # a missing value
        index=["Total Revenue", "Net Income"])


def _frames():
    return {("income", "annual"): _statement_frame(),
            ("balance", "annual"): None,                        # patchy - absent
            ("cashflow", "quarterly"): pd.DataFrame()}          # patchy - empty


def test_tidy_long_format_and_missing_dropped(monkeypatch):
    monkeypatch.setattr(yf_fundamentals, "_fetch_statements", lambda tk: _frames())
    res = fetch_fundamentals(["AAPL"], pace=0)["AAPL"]
    assert res.status == "ok"
    # 2 metrics x 2 periods = 4, minus the one NaN = 3 rows
    assert res.n_obs == 3
    assert list(res.df.columns) == yf_fundamentals.COLS
    rev = res.df[(res.df["metric"] == "Total Revenue") &
                 (res.df["period_end"] == dt.date(2024, 12, 31))]
    assert abs(rev["value"].iloc[0] - 1000.0) < 1e-9
    assert set(res.df["statement"]) == {"income"}               # empty frames skipped


def test_point_in_time_lag_applied(monkeypatch):
    monkeypatch.setattr(yf_fundamentals, "_fetch_statements", lambda tk: _frames())
    res = fetch_fundamentals(["AAPL"], pace=0)["AAPL"]
    row = res.df[res.df["period_end"] == dt.date(2024, 12, 31)].iloc[0]
    expected = dt.date(2024, 12, 31) + dt.timedelta(days=REPORTING_LAG_DAYS)
    assert row["available_from"] == expected
    assert row["available_from"] > row["period_end"]            # never same-day


def test_empty_and_error_are_graceful(monkeypatch):
    monkeypatch.setattr(yf_fundamentals, "_fetch_statements", lambda tk: {})
    assert fetch_fundamentals(["X"], pace=0)["X"].status == "empty"

    def boom(tk):
        raise RuntimeError("Too Many Requests")

    monkeypatch.setattr(yf_fundamentals, "_fetch_statements", boom)
    monkeypatch.setattr(yf_fundamentals.time, "sleep", lambda s: None)
    r = fetch_fundamentals(["Y"], pace=0, retries=2)["Y"]
    assert r.status == "error" and r.n_obs == 0


def test_fetch_meta_captures_reporting_currency(monkeypatch):
    """Shell reports in USD but trades in pence - capturing financialCurrency is
    what makes valuation ratios safe later."""
    fake = {"SHEL.L": {"financialCurrency": "USD", "sharesOutstanding": 3.0e9,
                       "marketCap": 2.0e11},
            "AAPL": {"financialCurrency": "USD", "sharesOutstanding": 1.5e10,
                     "marketCap": 3.0e12}}
    monkeypatch.setattr(yf_fundamentals, "_fetch_info", lambda tk: fake[tk])
    meta = yf_fundamentals.fetch_meta(["SHEL.L", "AAPL"], pace=0)
    assert meta["SHEL.L"]["financial_currency"] == "USD"
    assert meta["AAPL"]["shares_outstanding"] == 1.5e10


def test_fetch_meta_is_graceful(monkeypatch):
    def boom(tk):
        raise RuntimeError("no info")

    monkeypatch.setattr(yf_fundamentals, "_fetch_info", boom)
    meta = yf_fundamentals.fetch_meta(["X"], pace=0)
    assert meta["X"]["financial_currency"] is None      # None, not an exception
