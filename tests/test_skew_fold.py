"""Tests for skew_summary + _fold_skew (point-in-time as-of onto the daily snapshot)."""
import datetime as dt
import pandas as pd
from src.transform import derive


def test_skew_summary_filters_and_notes():
    sk = pd.DataFrame([
        {"ticker_id": "spx", "capture_date": dt.date(2026, 8, 2), "put_skew": 0.08, "put_skew_pctile": 0.90},
        {"ticker_id": "ndx", "capture_date": dt.date(2026, 8, 2), "put_skew": 0.05, "put_skew_pctile": 0.40},
    ])
    summ = derive.skew_summary(sk)
    assert list(summ.columns) == ["capture_date", "put_skew", "put_skew_pctile", "skew_note"]
    assert len(summ) == 1 and "SPY put-skew +0.080" in summ.iloc[0]["skew_note"]
    assert "90%ile" in summ.iloc[0]["skew_note"]
    assert len(derive.skew_summary(None)) == 0


def test_fold_skew_point_in_time_mixed_resolution():
    sk = pd.DataFrame([
        {"ticker_id": "spx", "capture_date": dt.date(2026, 8, 3), "put_skew": 0.08, "put_skew_pctile": 0.90},
        {"ticker_id": "spx", "capture_date": dt.date(2026, 8, 5), "put_skew": 0.11, "put_skew_pctile": 0.97},
    ])
    summ = derive.skew_summary(sk)
    summ["capture_date"] = pd.to_datetime(summ["capture_date"]).astype("datetime64[us]")   # us
    snap = pd.DataFrame({"date": [dt.date(2026, 8, 2), dt.date(2026, 8, 4), dt.date(2026, 8, 6)],
                         "vix": [18.0, 19.0, 20.0]})
    snap["date"] = pd.to_datetime(snap["date"]).astype("datetime64[s]")                     # s (mismatch)
    out = derive._fold_skew(snap, summ)          # must not raise
    v = dict(zip(pd.to_datetime(out["date"]).dt.date, out["put_skew"]))
    assert pd.isna(v[dt.date(2026, 8, 2)])       # before first capture
    assert abs(v[dt.date(2026, 8, 4)] - 0.08) < 1e-9   # 08-03 capture
    assert abs(v[dt.date(2026, 8, 6)] - 0.11) < 1e-9   # 08-05 capture
