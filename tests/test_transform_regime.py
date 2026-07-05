"""Tests for src/transform/derive.py compute() - pure pandas, no database."""
import datetime as dt

import pandas as pd

from src.transform.derive import compute


def _rows(extra=None):
    rows = [
        # NFCI only on 2026-06-01 -> must forward-fill to 2026-07-01
        {"series_id": "NFCI", "obs_date": "2026-06-01", "primary_zscore": 0.8, "value": 0.8},
        {"series_id": "CPIAUCSL", "obs_date": "2026-07-01", "primary_zscore": 1.5, "value": 0.03},
        {"series_id": "DGS2",         "obs_date": "2026-07-01", "primary_zscore": 1.0, "value": 4.0},
        {"series_id": "DGS10",        "obs_date": "2026-07-01", "primary_zscore": 1.3, "value": 4.5},
        {"series_id": "BAMLC0A0CM",   "obs_date": "2026-07-01", "primary_zscore": -0.5, "value": 1.0},
        {"series_id": "BAMLH0A0HYM2", "obs_date": "2026-07-01", "primary_zscore": 0.2, "value": 3.5},
        {"series_id": "VIXCLS",       "obs_date": "2026-07-01", "primary_zscore": -0.3, "value": 18.0},
        {"series_id": "DTWEXBGS",     "obs_date": "2026-07-01", "primary_zscore": 0.1, "value": 120.0},
        {"series_id": "DCOILWTICO",   "obs_date": "2026-07-01", "primary_zscore": 0.0, "value": 75.0},
    ]
    rows += (extra or [])
    df = pd.DataFrame(rows)
    df["obs_date"] = pd.to_datetime(df["obs_date"])
    df["primary_value"] = df["value"]
    return df


LABEL = "Growth Above-trend \u00b7 Inflation Above-trend \u00b7 Conditions Tight"


def test_regime_axes_and_label():
    # INDPRO +2 and UNRATE +1 (inverted -> -1) => growth mean 0.5 (Above-trend)
    df = _rows([
        {"series_id": "INDPRO", "obs_date": "2026-07-01", "primary_zscore": 2.0, "value": 100},
        {"series_id": "UNRATE", "obs_date": "2026-07-01", "primary_zscore": 1.0, "value": 4.0},
    ])
    regime, snap = compute(df)
    r = regime[regime["date"] == dt.date(2026, 7, 1)].iloc[0]
    assert abs(r["growth_axis"] - 0.5) < 1e-9
    assert abs(r["inflation_axis"] - 1.5) < 1e-9
    assert abs(r["conditions"] - 0.8) < 1e-9        # NFCI forward-filled
    assert r["regime_label"] == LABEL


def test_snapshot_derived_fields():
    df = _rows([
        {"series_id": "INDPRO", "obs_date": "2026-07-01", "primary_zscore": 2.0, "value": 100},
        {"series_id": "UNRATE", "obs_date": "2026-07-01", "primary_zscore": 1.0, "value": 4.0},
    ])
    regime, snap = compute(df)
    s = snap[snap["date"] == dt.date(2026, 7, 1)].iloc[0]
    assert abs(s["slope_2s10s"] - 0.5) < 1e-9        # 4.5 - 4.0
    assert abs(s["ig_hy_spread"] - 2.5) < 1e-9       # 3.5 - 1.0
    assert abs(s["vix"] - 18.0) < 1e-9
    assert s["regime_label"] == LABEL


def test_neutral_band():
    # growth axis lands inside the +/-0.25 band -> "Neutral", not directional
    df = _rows([
        {"series_id": "INDPRO", "obs_date": "2026-07-01", "primary_zscore": 0.2, "value": 100},
        {"series_id": "UNRATE", "obs_date": "2026-07-01", "primary_zscore": 0.0, "value": 4.0},
    ])
    regime, snap = compute(df)
    r = regime[regime["date"] == dt.date(2026, 7, 1)].iloc[0]
    assert abs(r["growth_axis"] - 0.1) < 1e-9        # mean(0.2, -0.0) = 0.1
    assert r["growth_state"] == "Neutral"
    assert "Growth Neutral" in r["regime_label"]
