"""Tests for the pure ranking/formatting functions in src/journal/scan_candidates.py.
No database - fct_security_factors / fct_security_metrics are synthesised directly."""
import datetime as dt

import pandas as pd

from src.journal import scan_candidates as sc


def _factors(asof=dt.date(2026, 8, 21)):
    rows = [
        {"ticker": "NVDA", "asof_date": asof, "sector": "Technology", "composite_z": 1.82,
         "composite_pct": 0.97, "value_pct": 0.41, "momentum_pct": 0.97, "quality_pct": 0.88,
         "growth_pct": 0.95},
        {"ticker": "LLY", "asof_date": asof, "sector": "Health Care", "composite_z": 1.55,
         "composite_pct": 0.93, "value_pct": 0.22, "momentum_pct": 0.79, "quality_pct": 0.94,
         "growth_pct": 0.88},
        {"ticker": "CAT", "asof_date": asof, "sector": "Industrials", "composite_z": 1.31,
         "composite_pct": 0.90, "value_pct": 0.68, "momentum_pct": 0.71, "quality_pct": 0.66,
         "growth_pct": 0.74},
        {"ticker": "COST", "asof_date": asof, "sector": "Consumer Staples", "composite_z": 1.24,
         "composite_pct": 0.88, "value_pct": 0.12, "momentum_pct": 0.85, "quality_pct": 0.91,
         "growth_pct": 0.61},
        {"ticker": "V", "asof_date": asof, "sector": "Financials", "composite_z": 1.19,
         "composite_pct": 0.85, "value_pct": 0.55, "momentum_pct": 0.62, "quality_pct": 0.89,
         "growth_pct": 0.58},
        {"ticker": "AAPL", "asof_date": asof, "sector": "Technology", "composite_z": 1.05,
         "composite_pct": 0.80, "value_pct": 0.45, "momentum_pct": 0.55, "quality_pct": 0.80,
         "growth_pct": 0.50},
        # a stale prior day - must be excluded by "latest asof_date only"
        {"ticker": "XOM", "asof_date": asof - dt.timedelta(days=1), "sector": "Energy",
         "composite_z": 5.0, "composite_pct": 0.99, "value_pct": 0.9, "momentum_pct": 0.9,
         "quality_pct": 0.9, "growth_pct": 0.9},
    ]
    return pd.DataFrame(rows)


def _metrics(asof=dt.date(2026, 8, 21)):
    return pd.DataFrame([
        {"ticker": "NVDA", "asof_date": asof, "last_close": 187.40},
        {"ticker": "LLY", "asof_date": asof, "last_close": 842.10},
        {"ticker": "CAT", "asof_date": asof, "last_close": 412.55},
    ])


def test_top_n_by_composite_z():
    top = sc.top_candidates(_factors(), n=5)
    assert list(top["ticker"]) == ["NVDA", "LLY", "CAT", "COST", "V"]


def test_only_latest_asof_date_considered():
    top = sc.top_candidates(_factors(), n=10)
    assert "XOM" not in list(top["ticker"])       # stale prior-day row excluded


def test_excludes_already_held_tickers():
    top = sc.top_candidates(_factors(), n=5, exclude={"nvda", "cat"})
    assert "NVDA" not in list(top["ticker"])
    assert "CAT" not in list(top["ticker"])
    assert list(top["ticker"]) == ["LLY", "COST", "V", "AAPL"]


def test_empty_factors_returns_empty_frame():
    out = sc.top_candidates(None)
    assert len(out) == 0
    out2 = sc.top_candidates(pd.DataFrame())
    assert len(out2) == 0


def test_merge_last_close():
    top = sc.top_candidates(_factors(), n=3)
    merged = sc.merge_last_close(top, _metrics())
    assert merged.set_index("ticker").loc["NVDA", "last_close"] == 187.40


def test_merge_last_close_tolerates_missing_metrics():
    top = sc.top_candidates(_factors(), n=3)
    merged = sc.merge_last_close(top, None)
    assert merged["last_close"].isna().all()


def test_open_tickers_from_positions():
    pos = pd.DataFrame([{"ticker": "NVDA", "status": "OPEN"},
                        {"ticker": "CAT", "status": "CLOSED"}])
    assert sc.open_tickers(pos) == {"NVDA"}
    assert sc.open_tickers(None) == set()
    assert sc.open_tickers(pd.DataFrame()) == set()


def test_format_table_contains_tickers():
    top = sc.merge_last_close(sc.top_candidates(_factors(), n=3), _metrics())
    text = sc.format_table(top)
    assert "NVDA" in text and "LLY" in text and "$187.40" in text


def test_format_table_empty():
    assert "no candidates" in sc.format_table(pd.DataFrame()).lower()


def test_thesis_snapshot_matches_build_plan_format():
    top = sc.top_candidates(_factors(), n=1)
    row = top.iloc[0]
    text = sc.thesis_snapshot(row, row["asof_date"])
    assert text.startswith("Top-5 scan 2026-08-21: composite +1.82")
    assert "value 41%" in text and "momentum 97%" in text and "quality 88%" in text \
        and "growth 95%" in text
