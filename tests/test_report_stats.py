"""Pure tests for src/report/stats.py - no database, no matplotlib."""
import datetime as dt
import numpy as np
import pandas as pd

from src.report import stats


def test_formatters():
    assert stats.fmt_pct(0.1234) == "12.3%"
    assert stats.fmt_sigma(1.5) == "+1.5\u03c3"
    assert stats.fmt_sigma(-2.0) == "\u22122.0\u03c3"
    assert stats.fmt_num(None) == "\u2014"
    assert stats.fmt_num(1234.5) == "1,234.50"


def test_zscore_and_percentile():
    s = pd.Series(list(range(100)) + [200])       # last value is an extreme high
    z = stats.zscore_latest(s)
    assert z is not None and z > 2
    assert stats.percentile_latest(s) == 100.0


def test_change_and_last():
    s = pd.Series([10.0, 11.0, 13.0])
    assert stats.last(s) == 13.0
    assert stats.change(s) == 2.0
    assert stats.pct_change(s) is not None


def test_describe_handles_empty():
    d = stats.describe_series(pd.Series([], dtype="float64"))
    assert d["n"] == 0 and d["last"] is None


def test_as_of_and_coverage():
    df = pd.DataFrame({"date": [dt.date(2026, 1, 1), dt.date(2026, 3, 1)], "x": [1, 2]})
    assert stats.as_of(df) == dt.date(2026, 3, 1)
    mn, mx, n = stats.coverage(df, "date")
    assert n == 2 and pd.notna(mn) and pd.notna(mx)
    assert stats.coverage(pd.DataFrame(), "date") == (None, None, 0)
