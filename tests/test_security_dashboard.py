"""Tests for P4 Securities dashboard: data prep + render."""
import datetime as dt
import pytest
pd = pytest.importorskip("pandas")
from src.report import build_security_dashboard as D


def _factors():
    A = dt.date(2026, 8, 3)
    return pd.DataFrame([
        dict(ticker="WDC", sector="Tech", asof_date=A, value_z=-0.5, momentum_z=2.0, quality_z=2.1,
             growth_z=0.3, value_pct=0.19, momentum_pct=0.98, quality_pct=0.99, growth_pct=0.5,
             composite_z=1.99, composite_pct=1.0),
        dict(ticker="ALL", sector="Fin", asof_date=A, value_z=2.0, momentum_z=0.8, quality_z=1.5,
             growth_z=0.2, value_pct=0.99, momentum_pct=0.78, quality_pct=0.94, growth_pct=0.4,
             composite_z=1.09, composite_pct=0.9),
        dict(ticker="CVNA", sector="Cons", asof_date=A, value_z=None, momentum_z=-0.4, quality_z=-0.5,
             growth_z=1.8, value_pct=None, momentum_pct=0.28, quality_pct=0.30, growth_pct=0.95,
             composite_z=0.94, composite_pct=0.7),
    ])


def _metrics():
    A = dt.date(2026, 8, 3)
    return pd.DataFrame([
        dict(ticker="WDC", asof_date=A, earnings_yield=0.03, ret_12_1m=0.5, roe=0.4, market_cap=5e10, pe=15),
        dict(ticker="ALL", asof_date=A, earnings_yield=0.15, ret_12_1m=0.18, roe=0.3, market_cap=4e10, pe=6),
        dict(ticker="CVNA", asof_date=A, earnings_yield=None, ret_12_1m=-0.1, roe=None, market_cap=3e10, pe=None),
    ])


def test_merge_and_screen_composite_order():
    df = D.merge(_factors(), _metrics())
    rows = D.screen_rows(df, "composite_z", None)
    assert [r["ticker"] for r in rows] == ["WDC", "ALL", "CVNA"]     # composite desc
    assert rows[0]["earnings_yield"] == 0.03                          # metric joined in


def test_cheapgood_filter_excludes_incomplete():
    df = D.merge(_factors(), _metrics())
    cg = SCREEN = next(s for s in D.SCREENS if s[0] == "cheapgood")
    rows = D.screen_rows(df, cg[2], cg[3])
    # ALL passes (value .99, quality .94); WDC fails (value .19); CVNA fails (value None)
    assert [r["ticker"] for r in rows] == ["ALL"]


def test_scatter_points_skip_missing_value():
    pts = D.scatter_points(_factors())
    assert {p["ticker"] for p in pts} == {"WDC", "ALL"}              # CVNA has no value_pct -> skipped


def test_sector_summary():
    s = D.sector_summary(_factors())
    secs = {r["sector"]: r for r in s}
    assert secs["Tech"]["n"] == 1 and abs(secs["Tech"]["avg_composite"] - 1.99) < 1e-9


def test_render_produces_html_with_screens_and_scatter():
    doc = D.render(_factors(), _metrics(), pd.DataFrame(), dt.date(2026, 8, 3))
    assert doc.startswith("<!doctype html>")
    assert "Security selection" in doc and "WDC" in doc and "ALL" in doc
    assert "svg" in doc and "value vs momentum".replace(" ", "") in doc.replace(" ", "").lower()
    assert 'class="bar empty"' in doc         # CVNA's missing value factor shows as a hatched bar
    assert "Cheap &amp; good" in doc or "Cheap &amp;amp; good" in doc


def test_bar_and_fmt_guards():
    assert "empty" in D._bar(None)
    assert D._fmt(None) == "\u2013" and D._fmt(1.234, 2) == "1.23"
    assert D._pct(0.9) == "90"
