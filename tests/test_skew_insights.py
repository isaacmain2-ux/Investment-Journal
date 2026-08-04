"""Tests for the options-skew section and tail-risk insight rules."""
import datetime as dt
import pandas as pd
from src.report import insights, sections


def _skew(pctile, put_skew=0.09):
    return pd.DataFrame([{"ticker_id": "spx", "ticker": "SPY", "capture_date": dt.date(2026, 8, 5),
                          "put_skew": put_skew, "put_skew_pctile": pctile, "put_skew_z": 1.5,
                          "risk_reversal": 0.13, "atm_iv": 0.20}])


def test_tail_bid_fires():
    flags = insights.build({"skew": _skew(0.90)})
    assert any("Tail bid" in f["text"] for f in flags)


def test_skew_complacent_fires():
    flags = insights.build({"skew": _skew(0.05)})
    assert any("Skew complacent" in f["text"] for f in flags)


def test_calm_surface_nervous_tails():
    dates = pd.bdate_range("2025-01-01", periods=60)
    snap = pd.DataFrame({"date": [d.date() for d in dates], "vix": [30.0] * 59 + [12.0]})
    flags = insights.build({"skew": _skew(0.85), "snapshot": snap})
    assert any(f["severity"] == insights.WARN and "nervous tails" in f["text"] for f in flags)


def test_no_skew_no_flags():
    flags = insights.build({})
    assert not any("skew" == f.get("category") for f in flags)


def test_section_renders_latest_table():
    html = sections.skew({"skew": _skew(0.90)})
    assert "Implied-vol skew" in html and "SPY" in html
