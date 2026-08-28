"""Tests for src/report/build_dashboard.py. render() is pure (tested here on a
small bundle and on an empty one); a DuckDB end-to-end test writes a real file
and skips if duckdb is absent."""
import datetime as dt
import pandas as pd
import pytest

from src.report import build_dashboard

SECTIONS = ["glance", "regime", "rates", "credit", "fx", "equity",
            "volterm", "positioning", "rotation", "factors", "valuation", "journal",
            "extremes", "headlines", "health"]


def _small_bundle():
    d = [dt.date(2026, 1, 1), dt.date(2026, 1, 2), dt.date(2026, 1, 3)]
    return {
        "regime": pd.DataFrame({"date": d, "growth_axis": [0.1, 0.2, 0.3],
                                "inflation_axis": [0.4, 0.4, 0.5], "conditions": [-0.1, 0.0, 0.1],
                                "regime_label": [None, None, "Growth Neutral \u00b7 Inflation Above-trend \u00b7 Conditions Loose"]}),
        "curve": pd.DataFrame({"date": d, "y2": [4.3, 4.3, 4.3], "y10": [4.0, 4.1, 4.2],
                               "slope_2s10s": [0.1, 0.0, -0.1], "real_10y": [1.8, 1.9, 2.0],
                               "breakeven_10y": [2.2, 2.2, 2.2]}),
        "snapshot": pd.DataFrame({"date": d, "dgs10": [4.0, 4.1, 4.2], "slope_2s10s": [0.1, 0.0, -0.1],
                                  "vix": [15, 16, 18], "spx": [5000, 5010, 5020]}),
        "series_analytics": pd.DataFrame({"series_id": ["A", "B"], "obs_date": [d[-1], d[-1]],
                                          "value": [1, 2], "primary_zscore": [2.1, -1.3]}),
        "vol_term": pd.DataFrame({"date": d, "vix": [14.0, 20.0, 28.0], "vix3m": [17.0, 20.5, 26.0],
                                  "vix_ts_ratio": [0.82, 0.98, 1.08],
                                  "ts_state": ["contango", "flat", "backwardation"]}),
        "positioning": pd.DataFrame({"market_id": ["vix", "sp500"], "market": ["VIX futures", "E-mini S&P 500"],
                                     "report_date": [d[-1], d[-1]], "net_lev": [-40000, 150000],
                                     "net_lev_pct_oi": [-0.15, 0.06], "net_lev_z": [-1.5, 1.2],
                                     "net_lev_pctile": [0.09, 0.93], "net_lev_wow": [-2000, 1000]}),
        "headlines": pd.DataFrame({"item_id": ["1"], "title": ["A headline"],
                                   "link": ["https://ft.com/x"], "published_at": [pd.Timestamp("2026-01-03 09:00")],
                                   "published_date": [d[-1]], "section": ["core"], "region": ["global"]}),
        "coverage": {"FRED macro": (d[0], d[-1], 2)},
    }


def test_render_has_all_sections():
    html = build_dashboard.render(_small_bundle())
    assert html.startswith("<!DOCTYPE html>")
    for s in SECTIONS:
        assert f'id="{s}"' in html
    assert "section error" not in html
    assert "INVERTED" in html                        # insight fired from the curve slope


def test_render_empty_is_graceful():
    empty = {k: (pd.DataFrame() if k != "coverage" else {}) for k in
             ["regime", "snapshot", "series_analytics", "headlines", "coverage"]}
    html = build_dashboard.render(empty)
    assert html.startswith("<!DOCTYPE html>") and "section error" not in html
    assert html.count("nodata") >= 8                 # every data section shows "no data"


def test_end_to_end_duckdb(tmp_path):
    duckdb = pytest.importorskip("duckdb")
    con = duckdb.connect(":memory:")
    con.execute("CREATE TABLE fct_regime (date DATE, growth_axis DOUBLE, inflation_axis DOUBLE, "
                "conditions DOUBLE, regime_label VARCHAR)")
    con.execute("INSERT INTO fct_regime VALUES (DATE '2026-01-03', 0.3, 0.5, 0.1, "
                "'Growth Neutral \u00b7 Inflation Above-trend \u00b7 Conditions Loose')")
    con.execute("CREATE TABLE fct_daily_snapshot (date DATE, dgs10 DOUBLE, slope_2s10s DOUBLE, vix DOUBLE)")
    con.execute("INSERT INTO fct_daily_snapshot VALUES (DATE '2026-01-03', 4.2, -0.1, 18.0)")
    path = build_dashboard.run(con=con, out_dir=str(tmp_path))
    html = open(path, encoding="utf-8").read()
    assert html.startswith("<!DOCTYPE html>")
    assert 'id="regime"' in html and "section error" not in html
