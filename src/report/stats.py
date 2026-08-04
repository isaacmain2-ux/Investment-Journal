"""
Summary-statistic helpers for the dashboard. Pure functions of pandas objects -
no database, no matplotlib - so they are trivially unit-testable.

The recurring idea: for any measure we don't just want its latest value, we want
its CONTEXT - how it has changed, how extreme it is versus its own history (a
z-score and a percentile), and its range. `describe_series` bundles that up.
"""
from __future__ import annotations

import math

import pandas as pd


# ----------------------------------------------------------------- formatting
def fmt_num(x, dp=2):
    if x is None or (isinstance(x, float) and math.isnan(x)):
        return "\u2014"
    return f"{x:,.{dp}f}"


def fmt_pct(x, dp=1):
    if x is None or (isinstance(x, float) and math.isnan(x)):
        return "\u2014"
    return f"{x * 100:,.{dp}f}%"


def fmt_bps(x, dp=0):
    if x is None or (isinstance(x, float) and math.isnan(x)):
        return "\u2014"
    return f"{x * 100:,.{dp}f} bps"


def fmt_sigma(z, dp=1):
    if z is None or (isinstance(z, float) and math.isnan(z)):
        return "\u2014"
    sign = "+" if z >= 0 else "\u2212"
    return f"{sign}{abs(z):.{dp}f}\u03c3"


def fmt_signed(x, dp=2):
    if x is None or (isinstance(x, float) and math.isnan(x)):
        return "\u2014"
    sign = "+" if x >= 0 else "\u2212"
    return f"{sign}{abs(x):,.{dp}f}"


def fmt_date(d):
    if d is None or (isinstance(d, float) and math.isnan(d)):
        return "\u2014"
    return pd.to_datetime(d).strftime("%Y-%m-%d")


# ----------------------------------------------------------------- series stats
def clean(series) -> pd.Series:
    """Drop NaNs and return a float Series (empty if none)."""
    if series is None or len(series) == 0:
        return pd.Series([], dtype="float64")
    return pd.to_numeric(series, errors="coerce").dropna()


def last(series):
    s = clean(series)
    return float(s.iloc[-1]) if len(s) else None


def change(series, periods=1):
    """Absolute change of the last value vs `periods` observations earlier."""
    s = clean(series)
    if len(s) <= periods:
        return None
    return float(s.iloc[-1] - s.iloc[-1 - periods])


def pct_change(series, periods=1):
    s = clean(series)
    if len(s) <= periods or s.iloc[-1 - periods] == 0:
        return None
    return float(s.iloc[-1] / s.iloc[-1 - periods] - 1)


def zscore_latest(series):
    """z-score of the last value against the whole (past) distribution."""
    s = clean(series)
    if len(s) < 3:
        return None
    mu, sd = s.mean(), s.std(ddof=1)
    if not sd or math.isnan(sd):
        return None
    return float((s.iloc[-1] - mu) / sd)


def percentile_latest(series):
    """Historical percentile (0-100) of the last value within its own history."""
    s = clean(series)
    if len(s) < 3:
        return None
    last_v = s.iloc[-1]
    return float((s <= last_v).mean() * 100)


def describe_series(series) -> dict:
    """Everything the report wants about one measure, in one call."""
    s = clean(series)
    if len(s) == 0:
        return {"last": None, "mean": None, "std": None, "min": None, "max": None,
                "z": None, "pctile": None, "n": 0}
    return {
        "last": float(s.iloc[-1]),
        "mean": float(s.mean()),
        "std": float(s.std(ddof=1)) if len(s) > 1 else None,
        "min": float(s.min()),
        "max": float(s.max()),
        "z": zscore_latest(s),
        "pctile": percentile_latest(s),
        "n": int(len(s)),
    }


# ----------------------------------------------------------------- as-of / coverage
def as_of(*frames, date_col="date"):
    """The latest date found across any of the given frames (or None)."""
    dates = []
    for df in frames:
        if df is not None and len(df) and date_col in df.columns:
            d = pd.to_datetime(df[date_col], errors="coerce").max()
            if pd.notna(d):
                dates.append(d)
    return max(dates).date() if dates else None


def coverage(df, date_col):
    """(min_date, max_date, n_rows) for a frame, tolerant of absence."""
    if df is None or len(df) == 0 or date_col not in df.columns:
        return (None, None, 0)
    d = pd.to_datetime(df[date_col], errors="coerce")
    return (d.min(), d.max(), int(len(df)))
