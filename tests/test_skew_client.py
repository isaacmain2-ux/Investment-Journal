"""Tests for src/extract/skew_client.py. compute_skew is pure; the fetch path
mocks the yfinance seams, so everything runs offline."""
import datetime as dt
import pandas as pd
from src.extract import skew_client


def _smile(spot=100.0):
    # downside-skewed smile: puts richer than calls
    puts = pd.DataFrame({"strike": [80, 85, 90, 95, 100],
                         "impliedVolatility": [1.0 - 0.8 * (k / 100) for k in [80, 85, 90, 95, 100]]})
    calls = pd.DataFrame({"strike": [100, 105, 110, 115, 120],
                          "impliedVolatility": [0.60 - 0.4 * (k / 100) for k in [100, 105, 110, 115, 120]]})
    return spot, calls, puts


def test_compute_skew_interpolation():
    spot, calls, puts = _smile()
    m = skew_client.compute_skew(spot, calls, puts)
    assert abs(m["put_iv"] - 0.28) < 1e-9        # IV at 90% moneyness
    assert abs(m["atm_iv"] - 0.20) < 1e-9        # IV at spot
    assert abs(m["call_iv"] - 0.16) < 1e-9       # IV at 110% moneyness
    assert abs(m["put_skew"] - 0.08) < 1e-9      # put_iv - atm
    assert abs(m["risk_reversal"] - 0.12) < 1e-9 # put_iv - call_iv


def test_compute_skew_needs_spot():
    _, calls, puts = _smile()
    assert skew_client.compute_skew(0, calls, puts)["put_skew"] is None


def test_compute_skew_too_few_strikes_is_none():
    puts = pd.DataFrame({"strike": [90], "impliedVolatility": [0.3]})
    calls = pd.DataFrame({"strike": [110], "impliedVolatility": [0.15]})
    m = skew_client.compute_skew(100, calls, puts)
    assert m["put_iv"] is None and m["risk_reversal"] is None


def test_pairs_filters_bad_iv():
    df = pd.DataFrame({"strike": [90, 95, 100], "impliedVolatility": [0.30, 0.0, float("nan")]})
    pts = skew_client._pairs(df, None, None)
    assert pts == [(90.0, 0.30)]                 # zero and NaN dropped


def test_pick_expiry_nearest_to_target():
    today = dt.date(2026, 8, 2)
    exp = ["2026-08-05", "2026-08-14", "2026-09-04", "2026-07-01"]  # last is in the past
    chosen, dte = skew_client._pick_expiry(exp, 30, today)
    assert chosen == "2026-09-04" and dte == 33   # closest to 30, past one skipped


def test_fetch_skew_happy_path(monkeypatch):
    spot, calls, puts = _smile()
    monkeypatch.setattr(skew_client, "_expiries", lambda t: ["2026-08-14", "2026-09-04"])
    monkeypatch.setattr(skew_client, "_spot", lambda t: spot)
    monkeypatch.setattr(skew_client, "_chain", lambda t, e: (calls, puts))
    res = skew_client.fetch_skew("spx", "SPY", target_dte=30, capture_date=dt.date(2026, 8, 2))
    assert res.status == "ok"
    assert res.expiry == "2026-09-04" and res.dte == 33
    assert abs(res.measures["put_skew"] - 0.08) < 1e-9
    r = res.row()
    assert r["ticker_id"] == "spx" and r["capture_date"] == dt.date(2026, 8, 2) and r["spot"] == 100.0


def test_fetch_skew_no_expiries(monkeypatch):
    monkeypatch.setattr(skew_client, "_expiries", lambda t: [])
    res = skew_client.fetch_skew("spx", "SPY", pace=0)
    assert res.status == "empty" and res.row() is None


def test_fetch_skew_handles_exception(monkeypatch):
    def boom(t): raise RuntimeError("yahoo down")
    monkeypatch.setattr(skew_client, "_expiries", boom)
    res = skew_client.fetch_skew("spx", "SPY", pace=0)
    assert res.status == "error" and "yahoo down" in res.error


def test_fetch_skew_retries_then_succeeds(monkeypatch):
    spot, calls, puts = _smile()
    calls_seen = {"n": 0}
    def flaky_expiries(t):
        calls_seen["n"] += 1
        if calls_seen["n"] == 1:
            raise RuntimeError("Too Many Requests. Rate limited.")   # first attempt fails
        return ["2026-09-04"]
    monkeypatch.setattr(skew_client, "_expiries", flaky_expiries)
    monkeypatch.setattr(skew_client, "_spot", lambda t: spot)
    monkeypatch.setattr(skew_client, "_chain", lambda t, e: (calls, puts))
    res = skew_client.fetch_skew("spx", "SPY", capture_date=dt.date(2026, 8, 2), pace=0)
    assert res.status == "ok" and calls_seen["n"] == 2          # retried once, then succeeded
