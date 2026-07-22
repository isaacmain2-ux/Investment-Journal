"""Tests for the equity signals folded into the daily snapshot (derive.equity_summary).
Pure pandas - no database needed."""
import datetime as dt

import pandas as pd

from src.transform.derive import equity_summary


def _frames():
    d = "2024-01-03"
    eq = pd.DataFrame([
        {"ticker": "^GSPC",     "price_date": d, "adj_close": 5000.0, "ret_1d": 0.01},
        {"ticker": "^FTSE",     "price_date": d, "adj_close": 7700.0, "ret_1d": -0.002},
        {"ticker": "^STOXX50E", "price_date": d, "adj_close": 4500.0, "ret_1d": 0.003},
        {"ticker": "AAPL",      "price_date": d, "adj_close": 190.0,  "ret_1d": 0.02},
    ])
    rs = pd.DataFrame([
        {"ticker": "XLK",  "price_date": d, "group": "sector_etfs", "excess_63d": 0.08},
        {"ticker": "XLE",  "price_date": d, "group": "sector_etfs", "excess_63d": 0.05},
        {"ticker": "XLF",  "price_date": d, "group": "sector_etfs", "excess_63d": 0.02},
        {"ticker": "XLU",  "price_date": d, "group": "sector_etfs", "excess_63d": -0.06},
        {"ticker": "MTUM", "price_date": d, "group": "style_etfs",  "excess_63d": 0.09},
    ])
    fs = pd.DataFrame([
        {"ticker": "NVDA", "price_date": d, "composite_z": 1.8},
        {"ticker": "MSFT", "price_date": d, "composite_z": 1.1},
        {"ticker": "LLY",  "price_date": d, "composite_z": 0.7},
        {"ticker": "BP.L", "price_date": d, "composite_z": -1.4},
    ])
    return eq, rs, fs


def test_equity_summary_fields():
    eq, rs, fs = _frames()
    out = equity_summary(eq, rs, fs)
    row = out[out["date"] == dt.date(2024, 1, 3)].iloc[0]

    # index levels and daily returns pivot into named columns
    assert abs(row["spx"] - 5000.0) < 1e-9
    assert abs(row["spx_ret_1d"] - 0.01) < 1e-9
    assert abs(row["ftse"] - 7700.0) < 1e-9
    assert abs(row["estoxx"] - 4500.0) < 1e-9

    # sector leadership: only sector ETFs, best first / worst first
    assert row["sectors_leading"] == "XLK, XLE, XLF"
    assert row["sectors_lagging"].startswith("XLU")
    assert "MTUM" not in row["sectors_leading"]        # style ETF excluded

    # factor screen: strongest and weakest composite names
    assert row["top_factor_names"] == "NVDA, MSFT, LLY"
    assert row["weak_factor_names"].startswith("BP.L")


def test_equity_summary_handles_missing_tables():
    # equity tables absent (None) -> empty frame, no crash
    out = equity_summary(None, None, None)
    assert len(out) == 0
