"""Tests for the optional volatility dimension on the regime label (derive.compute).
The term structure's contango/backwardation state feeds an extra Vol clause; when
no vol data is supplied the three-axis label is unchanged."""
import datetime as dt
import pandas as pd
from src.transform import derive


def _analytics(dates):
    rows = []
    for d in dates:
        for sid, z in [("INDPRO", 1.0), ("CPIAUCSL", 1.0), ("NFCI", 1.0), ("VIXCLS", 0.5)]:
            rows.append({"series_id": sid, "obs_date": d, "value": 10.0,
                         "primary_value": 10.0, "primary_zscore": z})
    return pd.DataFrame(rows)


def test_vol_state_appended_from_term_structure():
    dates = [dt.date(2026, 1, 5), dt.date(2026, 1, 6)]
    vt = pd.DataFrame({"date": dates, "vix_ts_ratio": [0.85, 1.05],
                       "ts_state": ["contango", "backwardation"]})
    regime, _ = derive.compute(_analytics(dates), vol_term_df=vt)
    lab = dict(zip(regime["date"], regime["regime_label"]))
    assert lab[dt.date(2026, 1, 5)].endswith("Vol Calm")
    assert lab[dt.date(2026, 1, 6)].endswith("Vol Stressed")
    assert "vol_state" in regime.columns


def test_label_unchanged_when_no_vol_supplied():
    regime, _ = derive.compute(_analytics([dt.date(2026, 1, 5)]))
    lab = regime["regime_label"].iloc[0]
    assert lab is not None and "Vol" not in lab


def test_flat_maps_to_neutral():
    d = [dt.date(2026, 1, 5)]
    vt = pd.DataFrame({"date": d, "vix_ts_ratio": [0.97], "ts_state": ["flat"]})
    regime, _ = derive.compute(_analytics(d), vol_term_df=vt)
    assert regime["regime_label"].iloc[0].endswith("Vol Neutral")
