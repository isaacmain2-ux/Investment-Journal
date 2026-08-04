"""
The auto-insight engine: turn the warehouse into a ranked list of plain-English
flags - the layer that makes the report insightful rather than a wall of charts.

`build(bundle)` returns a list of dicts {text, severity, category}. Every rule is
defensive: it only fires when its inputs are present, so a thin warehouse simply
yields fewer flags. Severity (0-3) drives ordering and colour.
"""
from __future__ import annotations

import pandas as pd

from . import stats

CRIT, WARN, NOTE, INFO = 3, 2, 1, 0


def _add(out, text, severity=NOTE, category="general"):
    out.append({"text": text, "severity": severity, "category": category})


def _latest_row(df, date_col="date"):
    if df is None or len(df) == 0 or date_col not in df.columns:
        return None
    d = df.copy()
    d[date_col] = pd.to_datetime(d[date_col], errors="coerce")
    d = d.dropna(subset=[date_col]).sort_values(date_col)
    return d.iloc[-1] if len(d) else None


def build(bundle: dict) -> list[dict]:
    out: list[dict] = []
    regime = bundle.get("regime")
    curve = bundle.get("curve")
    credit = bundle.get("credit")
    snap = bundle.get("snapshot")
    analytics = bundle.get("series_analytics")
    rs = bundle.get("rel_strength")
    factors = bundle.get("factors")
    valuation = bundle.get("valuation")
    headlines = bundle.get("headlines")

    # --- regime ---
    r = _latest_row(regime)
    if r is not None and pd.notna(r.get("regime_label")):
        _add(out, f"Macro regime: {r['regime_label']}.", WARN, "regime")
        for axis, name in [("growth_axis", "Growth"), ("inflation_axis", "Inflation"),
                           ("conditions", "Conditions")]:
            v = r.get(axis)
            if v is not None and pd.notna(v) and abs(v) >= 1.0:
                direction = "well above" if v > 0 else "well below"
                _add(out, f"{name} axis is {direction} its historical norm "
                          f"({stats.fmt_sigma(v)}).", WARN, "regime")

    # --- rates / curve ---
    c = _latest_row(curve)
    if c is not None:
        slope = c.get("slope_2s10s")
        if slope is not None and pd.notna(slope) and slope < 0:
            _add(out, f"2s10s curve is INVERTED ({stats.fmt_num(slope, 2)}%) - "
                      f"a classic recession signal.", CRIT, "rates")
        if curve is not None and "real_10y" in curve.columns:
            z = stats.zscore_latest(curve["real_10y"])
            if z is not None and abs(z) >= 1.5:
                _add(out, f"10y real yield is {stats.fmt_sigma(z)} vs its own history.",
                     WARN, "rates")

    # --- credit ---
    cr = _latest_row(credit)
    if cr is not None:
        ighy_z = cr.get("ig_hy_spread_z")
        qual_z = cr.get("quality_spread_z")
        if (qual_z is not None and pd.notna(qual_z) and qual_z > 1
                and ighy_z is not None and pd.notna(ighy_z) and ighy_z < 0.5):
            _add(out, "Credit shows stress beneath a calm surface: quality spread "
                      f"elevated ({stats.fmt_sigma(qual_z)}) while broad IG-HY is not.",
                 WARN, "credit")
        if credit is not None and "hy_oas" in credit.columns:
            p = stats.percentile_latest(credit["hy_oas"])
            if p is not None and (p >= 80 or p <= 20):
                where = "wide" if p >= 80 else "tight"
                _add(out, f"High-yield spreads are historically {where} "
                          f"({p:.0f}th percentile).", NOTE, "credit")

    # --- equity / vol ---
    s = _latest_row(snap)
    if s is not None:
        if snap is not None and "vix" in snap.columns:
            p = stats.percentile_latest(snap["vix"])
            v = s.get("vix")
            if p is not None and v is not None and pd.notna(v):
                if p >= 80:
                    _add(out, f"Volatility is elevated: VIX {stats.fmt_num(v,1)} "
                              f"({p:.0f}th percentile).", WARN, "equity")
                elif p <= 15:
                    _add(out, f"Volatility is unusually low: VIX {stats.fmt_num(v,1)} "
                              f"({p:.0f}th percentile).", NOTE, "equity")
        ret = s.get("spx_ret_1d")
        if ret is not None and pd.notna(ret) and abs(ret) >= 0.015:
            _add(out, f"S&P moved {stats.fmt_pct(ret)} on the day.", NOTE, "equity")

    # --- volatility term structure (the complacency test) ---
    vol = bundle.get("vol_term")
    vrow = _latest_row(vol)
    if vrow is not None:
        state = vrow.get("ts_state")
        ratio = vrow.get("vix_ts_ratio")
        vix_pct = None
        if snap is not None and "vix" in snap.columns:
            vix_pct = stats.percentile_latest(snap["vix"])
        elif vol is not None and "vix" in vol.columns:
            vix_pct = stats.percentile_latest(vol["vix"])
        if state == "backwardation":
            _add(out, "VIX term structure is INVERTED (backwardation) - near-term "
                      "volatility is priced above the 3-month; fear is being paid for now.",
                 WARN, "volatility")
        elif (state == "contango" and ratio is not None and pd.notna(ratio) and ratio < 0.90
              and vix_pct is not None and vix_pct <= 30):
            _add(out, f"Complacency watch: steep VIX contango (ratio {stats.fmt_num(ratio, 2)}) "
                      f"with VIX in the {vix_pct:.0f}th percentile - calm may be priced-in "
                      f"rather than earned.", WARN, "volatility")

        # cross-asset divergence: equity vol calm while oil/gold vol elevated
        zmap = _latest_zmap(analytics)
        eq_z = zmap.get("VIXCLS")
        others = [zmap[s] for s in ("OVXCLS", "GVZCLS") if s in zmap]
        if eq_z is not None and others and eq_z < 0 and (sum(others) / len(others)) > 0.8:
            _add(out, "Calm is narrow: equity vol is subdued while oil/gold vol is elevated "
                      "versus history - the quiet is not broad-based.", NOTE, "volatility")

        # calm looks earned: contango + low vol + tight credit all agree
        hy_pct = (stats.percentile_latest(credit["hy_oas"])
                  if credit is not None and "hy_oas" in credit.columns else None)
        if (state == "contango" and vix_pct is not None and vix_pct <= 30
                and hy_pct is not None and hy_pct <= 30):
            _add(out, "Calm looks earned: low volatility, tight credit and a normal "
                      "(contango) vol curve are aligned - benign rather than complacent.",
                 INFO, "volatility")

    # --- positioning / crowding (CFTC) ---
    pos = bundle.get("positioning")
    pos_latest = {}
    if pos is not None and len(pos):
        pp = pos.copy()
        pp["report_date"] = pd.to_datetime(pp["report_date"], errors="coerce")
        for mid, g in pp.sort_values("report_date").groupby("market_id"):
            pos_latest[mid] = g.iloc[-1].to_dict()
    vix_p, sp_p = pos_latest.get("vix"), pos_latest.get("sp500")

    if vix_p is not None:
        net, pct = vix_p.get("net_lev"), vix_p.get("net_lev_pctile")
        if net is not None and pd.notna(net) and net < 0 and pct is not None and pd.notna(pct) and pct <= 0.15:
            _add(out, f"Crowded short vol: Leveraged Funds are net-short VIX at the "
                      f"{pct * 100:.0f}th percentile of their history - a vol spike would force covering.",
                 WARN, "positioning")
    if sp_p is not None:
        pct = sp_p.get("net_lev_pctile")
        if pct is not None and pd.notna(pct) and pct >= 0.90:
            _add(out, f"Crowded long equity: Leveraged Funds net-long S&P at the {pct * 100:.0f}th percentile.",
                 NOTE, "positioning")
    for mid, r in pos_latest.items():
        pct = r.get("net_lev_pctile")
        if pct is not None and pd.notna(pct) and (pct >= 0.95 or pct <= 0.05):
            side = "long" if pct >= 0.95 else "short"
            _add(out, f"Positioning stretched: {r.get('market') or mid} net-{side} at the "
                      f"{pct * 100:.0f}th percentile.", NOTE, "positioning")
        wow, net = r.get("net_lev_wow"), r.get("net_lev")
        if (wow is not None and pd.notna(wow) and net is not None and pd.notna(net)
                and abs(net) > 0 and abs(wow) > abs(net)):
            _add(out, f"Positioning unwinding: {r.get('market') or mid} net position swung "
                      f"{wow:+,.0f} contracts week-on-week.", NOTE, "positioning")

    # --- FRAGILE CALM: contango + low VIX (from #1) AND crowded short vol (this) ---
    if vrow is not None and vix_p is not None:
        vix_pct_now = stats.percentile_latest(snap["vix"]) if snap is not None and "vix" in snap.columns else None
        vn, vp = vix_p.get("net_lev"), vix_p.get("net_lev_pctile")
        if (vrow.get("ts_state") == "contango" and vix_pct_now is not None and vix_pct_now <= 35
                and vn is not None and pd.notna(vn) and vn < 0
                and vp is not None and pd.notna(vp) and vp <= 0.20):
            _add(out, "FRAGILE CALM: the vol curve is in contango with VIX historically low, and "
                      "Leveraged Funds are crowded net-short VIX - calm that is both cheap and heavily "
                      "leaned on.", CRIT, "volatility")

    # --- options skew / tail risk ---
    skew = bundle.get("skew")
    spx_skew = None
    if skew is not None and len(skew):
        sk = skew.copy()
        sk["capture_date"] = pd.to_datetime(sk["capture_date"], errors="coerce")
        g = sk[sk["ticker_id"] == "spx"].sort_values("capture_date")
        if len(g):
            spx_skew = g.iloc[-1].to_dict()
    if spx_skew is not None:
        pct = spx_skew.get("put_skew_pctile")
        if pct is not None and pd.notna(pct) and pct >= 0.85:
            _add(out, f"Tail bid: SPY put-skew is steep, in the {pct * 100:.0f}th percentile of its "
                      f"accumulated history - downside protection is being bid.", WARN, "skew")
        elif pct is not None and pd.notna(pct) and pct <= 0.15:
            _add(out, f"Skew complacent: SPY put-skew is unusually flat ({pct * 100:.0f}th percentile) "
                      f"- little downside fear priced into options.", NOTE, "skew")

    # --- CALM SURFACE, NERVOUS TAILS: low VIX but skew bid (vol layer + skew) ---
    if spx_skew is not None and snap is not None and "vix" in snap.columns:
        vix_pct_now = stats.percentile_latest(snap["vix"])
        pct = spx_skew.get("put_skew_pctile")
        if (vix_pct_now is not None and vix_pct_now <= 35
                and pct is not None and pd.notna(pct) and pct >= 0.80):
            _add(out, "Calm surface, nervous tails: VIX is historically low while SPY put-skew is "
                      "elevated - the surface is calm but the wings are being hedged.", WARN, "skew")

    # --- rotation ---
    if rs is not None and len(rs):
        rr = rs.copy()
        rr["price_date"] = pd.to_datetime(rr.get("price_date"), errors="coerce")
        latest = rr[rr["price_date"] == rr["price_date"].max()]
        sect = latest[latest.get("group") == "sector_etfs"] if "group" in latest else latest
        if len(sect) and "excess_63d" in sect:
            sect = sect.dropna(subset=["excess_63d"])
            if len(sect):
                lead = sect.loc[sect["excess_63d"].idxmax()]
                lag = sect.loc[sect["excess_63d"].idxmin()]
                _add(out, f"Sector leadership: {lead['ticker']} leading, "
                          f"{lag['ticker']} lagging (63d excess).", NOTE, "rotation")

    # --- factors ---
    if factors is not None and len(factors) and "composite_z" in factors.columns:
        ff = factors.copy()
        ff["price_date"] = pd.to_datetime(ff.get("price_date"), errors="coerce")
        latest = ff[ff["price_date"] == ff["price_date"].max()].dropna(subset=["composite_z"])
        if len(latest):
            top = latest.loc[latest["composite_z"].idxmax()]
            _add(out, f"Top factor-screen name: {top['ticker']} "
                      f"(composite {stats.fmt_sigma(top['composite_z'])}).", NOTE, "factors")

    # --- valuation ---
    if valuation is not None and len(valuation) and "earnings_yield" in valuation.columns:
        vv = valuation.copy()
        vv["price_date"] = pd.to_datetime(vv.get("price_date"), errors="coerce")
        latest = vv[vv["price_date"] == vv["price_date"].max()].dropna(subset=["earnings_yield"])
        if len(latest):
            cheap = latest.loc[latest["earnings_yield"].idxmax()]
            _add(out, f"Cheapest watchlist name by earnings yield: {cheap['ticker']} "
                      f"({stats.fmt_pct(cheap['earnings_yield'])}).", NOTE, "valuation")

    # --- extremes (top macro series by |primary_zscore|) ---
    ex = extremes(analytics, n=3)
    for name, z in ex:
        _add(out, f"{name}: {stats.fmt_sigma(z)} vs history.", NOTE, "extremes")

    # --- news ---
    if headlines is not None and len(headlines) and "published_date" in headlines.columns:
        hd = headlines.copy()
        hd["published_date"] = pd.to_datetime(hd["published_date"], errors="coerce")
        recent = hd.dropna(subset=["published_date"])
        if len(recent):
            last_day = recent["published_date"].max()
            n_last = int((recent["published_date"] == last_day).sum())
            _add(out, f"{n_last} FT stories on {stats.fmt_date(last_day)} "
                      f"({len(recent)} in the window).", INFO, "news")

    out.sort(key=lambda f: -f["severity"])
    return out


def _latest_zmap(analytics) -> dict:
    """{series_id: latest primary_zscore} - for cross-series comparisons."""
    if analytics is None or len(analytics) == 0:
        return {}
    a = analytics.copy()
    if "primary_zscore" not in a.columns or "series_id" not in a.columns:
        return {}
    a["obs_date"] = pd.to_datetime(a.get("obs_date"), errors="coerce")
    a = a.dropna(subset=["primary_zscore"])
    if not len(a):
        return {}
    latest = a.sort_values("obs_date").groupby("series_id").tail(1)
    return {r["series_id"]: float(r["primary_zscore"]) for _, r in latest.iterrows()}


def extremes(analytics, n=5) -> list[tuple[str, float]]:
    """Top-n macro series by |primary_zscore| at their latest observation."""
    if analytics is None or len(analytics) == 0:
        return []
    a = analytics.copy()
    if "primary_zscore" not in a.columns or "series_id" not in a.columns:
        return []
    a["obs_date"] = pd.to_datetime(a.get("obs_date"), errors="coerce")
    a = a.dropna(subset=["primary_zscore"])
    if not len(a):
        return []
    latest = a.sort_values("obs_date").groupby("series_id").tail(1)
    latest = latest.reindex(latest["primary_zscore"].abs().sort_values(ascending=False).index)
    return [(row["series_id"], float(row["primary_zscore"]))
            for _, row in latest.head(n).iterrows()]
