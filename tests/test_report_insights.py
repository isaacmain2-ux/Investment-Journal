"""Tests for the auto-insight engine (src/report/insights.py). Pure."""
import datetime as dt
import pandas as pd

from src.report import insights


def test_inversion_and_regime_fire():
    curve = pd.DataFrame({"date": [dt.date(2026, 1, 1), dt.date(2026, 1, 2)],
                          "slope_2s10s": [0.1, -0.3], "real_10y": [1.0, 1.1]})
    regime = pd.DataFrame({"date": [dt.date(2026, 1, 2)], "growth_axis": [0.1],
                           "inflation_axis": [1.4], "conditions": [-0.1],
                           "regime_label": ["Growth Neutral \u00b7 Inflation Above-trend \u00b7 Conditions Loose"]})
    flags = insights.build({"curve": curve, "regime": regime})
    texts = " ".join(f["text"] for f in flags)
    assert "INVERTED" in texts                      # negative slope flagged
    assert "regime" in texts.lower()
    assert flags[0]["severity"] >= 2                # inversion sorts to the top (CRIT)


def test_extremes_ranking():
    rows = []
    for sid, z in [("A", 0.2), ("B", -2.4), ("C", 1.1)]:
        rows.append({"series_id": sid, "obs_date": dt.date(2026, 1, 1), "primary_zscore": z})
    ex = insights.extremes(pd.DataFrame(rows), n=2)
    assert ex[0][0] == "B"                           # largest |z| first
    assert len(ex) == 2


def test_empty_bundle_is_safe():
    assert insights.build({}) == []
    assert insights.extremes(pd.DataFrame()) == []


def test_vol_backwardation_flag():
    import datetime as dt
    vol = pd.DataFrame({"date": [dt.date(2026, 1, 6)], "vix": [28.0],
                        "vix_ts_ratio": [1.08], "ts_state": ["backwardation"]})
    flags = insights.build({"vol_term": vol})
    assert any("INVERTED" in f["text"] for f in flags)


def test_vol_complacency_flag():
    import datetime as dt
    dates = pd.bdate_range("2025-01-01", periods=60)
    snap = pd.DataFrame({"date": [d.date() for d in dates], "vix": [30.0] * 59 + [12.0]})
    vol = pd.DataFrame({"date": [dates[-1].date()], "vix": [12.0],
                        "vix_ts_ratio": [0.80], "ts_state": ["contango"]})
    flags = insights.build({"vol_term": vol, "snapshot": snap})
    assert any("Complacency watch" in f["text"] for f in flags)


def test_vol_cross_asset_divergence_flag():
    import datetime as dt
    vol = pd.DataFrame({"date": [dt.date(2026, 1, 7)], "vix": [13.0],
                        "vix_ts_ratio": [0.93], "ts_state": ["contango"]})
    an = pd.DataFrame([
        {"series_id": "VIXCLS", "obs_date": dt.date(2026, 1, 7), "primary_zscore": -0.8},
        {"series_id": "OVXCLS", "obs_date": dt.date(2026, 1, 7), "primary_zscore": 1.5},
        {"series_id": "GVZCLS", "obs_date": dt.date(2026, 1, 7), "primary_zscore": 1.2}])
    flags = insights.build({"vol_term": vol, "series_analytics": an})
    assert any("Calm is narrow" in f["text"] for f in flags)


def _pos_row(mid="vix", market="VIX futures", net=-50000, pctile=0.08, wow=-2000):
    import datetime as dt
    return {"market_id": mid, "market": market, "report_date": dt.date(2026, 7, 28),
            "net_lev": net, "net_lev_pctile": pctile, "net_lev_z": -1.8, "net_lev_wow": wow,
            "net_lev_pct_oi": -0.2}


def test_positioning_crowded_short_vol():
    flags = insights.build({"positioning": pd.DataFrame([_pos_row()])})
    assert any("Crowded short vol" in f["text"] for f in flags)


def test_positioning_crowded_long_equity():
    pos = pd.DataFrame([_pos_row(mid="sp500", market="E-mini S&P 500", net=200000, pctile=0.94, wow=1000)])
    flags = insights.build({"positioning": pos})
    assert any("Crowded long equity" in f["text"] for f in flags)


def test_fragile_calm_is_critical():
    dates = pd.bdate_range("2025-01-01", periods=60)
    snap = pd.DataFrame({"date": [d.date() for d in dates], "vix": [30.0] * 59 + [12.0]})
    vol = pd.DataFrame({"date": [dates[-1].date()], "vix": [12.0], "vix_ts_ratio": [0.88], "ts_state": ["contango"]})
    pos = pd.DataFrame([_pos_row(net=-40000, pctile=0.10)])
    flags = insights.build({"vol_term": vol, "snapshot": snap, "positioning": pos})
    assert any(f["severity"] == insights.CRIT and "FRAGILE CALM" in f["text"] for f in flags)
