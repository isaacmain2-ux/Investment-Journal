"""
Section builders: each turns the relevant slice of the warehouse into an HTML
fragment (stat tables + charts + callouts). Every builder degrades gracefully -
a missing or empty frame yields a muted "no data" card rather than an error.

Pure functions of the data bundle, so they're testable without a database.
"""
from __future__ import annotations

import pandas as pd

from . import charts, stats
from .insights import extremes

SEV_CLASS = {3: "sev-crit", 2: "sev-warn", 1: "sev-note", 0: "sev-info"}


# --------------------------------------------------------------- small helpers
def card(title, body, sub=None):
    s = f'<div class="card-sub">{sub}</div>' if sub else ""
    return f'<div class="card"><div class="card-h">{title}</div>{s}{body}</div>'


def no_data(msg="Not yet ingested"):
    return f'<div class="nodata">{msg}</div>'


def table(headers, rows):
    if not rows:
        return no_data("No rows")
    h = "".join(f"<th>{c}</th>" for c in headers)
    body = "".join("<tr>" + "".join(f"<td>{c}</td>" for c in r) + "</tr>" for r in rows)
    return f'<table class="rt"><thead><tr>{h}</tr></thead><tbody>{body}</tbody></table>'


def _latest_row(df, date_col="date"):
    if df is None or len(df) == 0 or date_col not in df.columns:
        return None
    d = df.copy()
    d[date_col] = pd.to_datetime(d[date_col], errors="coerce")
    d = d.dropna(subset=[date_col]).sort_values(date_col)
    return d.iloc[-1] if len(d) else None


def kpi(label, value_html, sub=None, spark_vals=None):
    sp = charts.sparkline(spark_vals) if spark_vals is not None else ""
    subhtml = f'<div class="kpi-sub">{sub}</div>' if sub else ""
    return (f'<div class="kpi"><div class="kpi-label">{label}</div>'
            f'<div class="kpi-value">{value_html}</div>{subhtml}'
            f'<div class="kpi-spark">{sp}</div></div>')


def _zpct(series):
    z = stats.zscore_latest(series)
    p = stats.percentile_latest(series)
    bits = []
    if z is not None:
        bits.append(stats.fmt_sigma(z))
    if p is not None:
        bits.append(f"{p:.0f}%ile")
    return " \u00b7 ".join(bits)


# ===================================================================== GLANCE
def glance(bundle, insight_list):
    snap = bundle.get("snapshot")
    row = _latest_row(snap)
    kpis = ""
    if row is not None:
        tail = snap.sort_values("date").tail(90) if "date" in snap.columns else snap
        def col(c):
            return list(tail[c]) if c in tail.columns else None
        specs = [
            ("US 10y yield", "dgs10", stats.fmt_num, "%"),
            ("2s10s slope", "slope_2s10s", stats.fmt_num, "%"),
            ("IG\u2013HY spread", "ig_hy_spread", stats.fmt_num, "%"),
            ("VIX", "vix", stats.fmt_num, ""),
            ("Broad USD", "usd_broad", stats.fmt_num, ""),
            ("WTI oil", "oil_wti", stats.fmt_num, ""),
            ("S&P 500", "spx", stats.fmt_num, ""),
        ]
        for label, c, fmt, unit in specs:
            if c not in snap.columns or pd.isna(row.get(c)):
                continue
            val = f"{fmt(row.get(c))}{unit}"
            sub = _zpct(snap[c]) if c in snap.columns else None
            kpis += kpi(label, val, sub=sub, spark_vals=col(c))
        if "journal_value" in snap.columns and pd.notna(row.get("journal_value")):
            kpis += kpi("Journal value (hypothetical)",
                        f"${stats.fmt_num(row.get('journal_value'), 0)}",
                        sub=None, spark_vals=col("journal_value"))
    kpi_block = f'<div class="kpi-row">{kpis}</div>' if kpis else no_data("Run a transform to populate the snapshot")

    # insights
    if insight_list:
        items = "".join(
            f'<li class="{SEV_CLASS.get(f["severity"], "sev-info")}">{f["text"]}</li>'
            for f in insight_list[:16])
        ins = f'<ul class="insights">{items}</ul>'
    else:
        ins = no_data("No insights yet")
    return kpi_block + card("Auto-insights", ins)


# ===================================================================== REGIME
def regime(bundle):
    reg = bundle.get("regime")
    if reg is None or len(reg) == 0:
        return no_data()
    chart = charts.line(reg, "date", ["growth_axis", "inflation_axis", "conditions"],
                        labels=["Growth", "Inflation", "Conditions"],
                        band=(-0.25, 0.25), ylabel="z (mean of drivers)")
    row = _latest_row(reg)
    rows = []
    for axis, name, pos, neg in [("growth_axis", "Growth", "Above-trend", "Below-trend"),
                                 ("inflation_axis", "Inflation", "Above-trend", "Below-trend"),
                                 ("conditions", "Conditions", "Tight", "Loose")]:
        v = row.get(axis) if row is not None else None
        state = "\u2014"
        if v is not None and pd.notna(v):
            state = pos if v > 0.25 else neg if v < -0.25 else "Neutral"
        rows.append([name, stats.fmt_num(v, 2), state])
    label = row.get("regime_label") if row is not None else None
    lab = f'<div class="regime-label">{label}</div>' if label and pd.notna(label) else ""
    return card("Regime axes over time", chart) + \
        card("Current reading", lab + table(["Axis", "Value", "State"], rows))


# ===================================================================== RATES
def rates(bundle):
    curve = bundle.get("curve")
    if curve is None or len(curve) == 0:
        return no_data()
    out = ""
    if "slope_2s10s" in curve.columns:
        c = curve.copy()
        c["neg"] = c["slope_2s10s"]
        out += card("2s10s slope (inverted regions shaded)",
                    charts.line(c, "date", ["slope_2s10s"], labels=["2s10s"],
                                shade_negative="neg", ylabel="%"))
    decomp = [x for x in ["real_10y", "breakeven_10y"] if x in curve.columns]
    if decomp:
        out += card("Real yield & breakeven inflation (10y)",
                    charts.line(curve, "date", decomp,
                                labels=["Real 10y", "Breakeven"], ylabel="%"))
    row = _latest_row(curve)
    if row is not None:
        rows = []
        for c, name, unit in [("y2", "2y yield", "%"), ("y10", "10y yield", "%"),
                              ("slope_2s10s", "2s10s slope", "%"),
                              ("real_10y", "Real 10y", "%"),
                              ("breakeven_10y", "Breakeven 10y", "%"),
                              ("term_premium_10y", "Term premium", "%")]:
            if c in curve.columns and pd.notna(row.get(c)):
                rows.append([name, f"{stats.fmt_num(row.get(c))}{unit}", _zpct(curve[c])])
        out += card("Current levels", table(["Measure", "Level", "vs history"], rows))
    return out or no_data()


# ===================================================================== CREDIT
def credit(bundle):
    cr = bundle.get("credit")
    if cr is None or len(cr) == 0:
        return no_data()
    out = ""
    oas = [x for x in ["ig_oas", "hy_oas"] if x in cr.columns]
    if oas:
        out += card("Investment-grade & high-yield OAS",
                    charts.line(cr, "date", oas, labels=["IG OAS", "HY OAS"], ylabel="%"))
    spreads = [x for x in ["ig_hy_spread", "quality_spread"] if x in cr.columns]
    if spreads:
        out += card("Derived spreads",
                    charts.line(cr, "date", spreads,
                                labels=["IG\u2013HY", "Quality (CCC\u2212BB)"], ylabel="%"))
    row = _latest_row(cr)
    if row is not None:
        rows = []
        for c, name in [("ig_oas", "IG OAS"), ("hy_oas", "HY OAS"),
                        ("ig_hy_spread", "IG\u2013HY spread"), ("quality_spread", "Quality spread")]:
            if c in cr.columns and pd.notna(row.get(c)):
                rows.append([name, f"{stats.fmt_num(row.get(c))}%", _zpct(cr[c])])
        out += card("Current levels vs history", table(["Measure", "Level", "vs history"], rows))
    return out or no_data()


# ===================================================================== VOL TERM
def vol_term(bundle):
    vt = bundle.get("vol_term")
    if vt is None or len(vt) == 0:
        return no_data("No volatility term-structure data (ingest the vol series)")
    out = ""
    if "vix" in vt.columns and "vix3m" in vt.columns:
        out += card("VIX vs 3-month VIX (term structure)",
                    charts.line(vt, "date", ["vix", "vix3m"], labels=["VIX (30d)", "VIX3M"]))
    if "vix_ts_ratio" in vt.columns:
        out += card("Contango / backwardation (VIX \u00f7 VIX3M \u2014 \u2265 1 = inverted)",
                    charts.line(vt, "date", ["vix_ts_ratio"], labels=["ratio"]))
    labels = {"vix": "Equity (VIX)", "ovx": "Oil (OVX)", "gvz": "Gold (GVZ)", "vxeem": "EM"}
    cross = [c for c in ["vix", "ovx", "gvz", "vxeem"] if c in vt.columns and vt[c].notna().any()]
    if len(cross) >= 2:
        out += card("Cross-asset volatility",
                    charts.line(vt, "date", cross, labels=[labels[c] for c in cross]))
    row = _latest_row(vt)
    if row is not None:
        rows = [["VIX (30d)", stats.fmt_num(row.get("vix"))],
                ["VIX3M", stats.fmt_num(row.get("vix3m"))],
                ["VIX \u00f7 VIX3M", stats.fmt_num(row.get("vix_ts_ratio"), 3)],
                ["State", row.get("ts_state") or "\u2014"]]
        out += card("Current term structure", table(["Measure", "Value"], rows))
    return out or no_data()


# ===================================================================== POSITIONING
def positioning(bundle):
    pos = bundle.get("positioning")
    if pos is None or len(pos) == 0:
        return no_data("No positioning data (run cot_ingest)")
    p = pos.copy()
    p["report_date"] = pd.to_datetime(p["report_date"], errors="coerce")
    latest = p.sort_values("report_date").groupby("market_id").tail(1)
    rows = []
    for _, r in latest.sort_values("market_id").iterrows():
        rows.append([r.get("market") or r["market_id"],
                     stats.fmt_num(r.get("net_lev"), 0),
                     stats.fmt_pct(r.get("net_lev_pct_oi")),
                     stats.fmt_num(r.get("net_lev_z"), 2),
                     stats.fmt_pct(r.get("net_lev_pctile"))])
    out = card("Leveraged Funds net positioning (latest week)",
               table(["Market", "Net", "% OI", "z", "hist %ile"], rows))
    for mid, label in (("vix", "VIX futures"), ("sp500", "E-mini S&P 500")):
        sub = p[p["market_id"] == mid].sort_values("report_date")
        if len(sub) and sub["net_lev"].notna().any():
            out += card(f"{label}: Leveraged Funds net position",
                        charts.line(sub, "report_date", ["net_lev"], labels=["net contracts"]))
    return out or no_data()


# ===================================================================== SKEW
def skew(bundle):
    sk = bundle.get("skew")
    if sk is None or len(sk) == 0:
        return no_data("No skew data yet (run skew_ingest; history accumulates daily)")
    s = sk.copy()
    s["capture_date"] = pd.to_datetime(s["capture_date"], errors="coerce")
    latest = s.sort_values("capture_date").groupby("ticker_id").tail(1)
    rows = []
    for _, r in latest.sort_values("ticker_id").iterrows():
        rows.append([r.get("ticker") or r["ticker_id"],
                     stats.fmt_pct(r.get("put_skew")),
                     stats.fmt_pct(r.get("risk_reversal")),
                     stats.fmt_pct(r.get("atm_iv")),
                     stats.fmt_num(r.get("put_skew_z"), 2),
                     stats.fmt_pct(r.get("put_skew_pctile"))])
    out = card("Implied-vol skew (latest capture)",
               table(["Ticker", "Put skew", "Risk rev.", "ATM IV", "z", "hist %ile"], rows))
    spx = s[s["ticker_id"] == "spx"].sort_values("capture_date")
    if len(spx) >= 2 and spx["put_skew"].notna().any():
        out += card("SPY put-skew (accumulated history)",
                    charts.line(spx, "capture_date", ["put_skew"], labels=["put skew"]))
    elif len(spx) < 2:
        out += card("SPY put-skew", "<p class='muted'>History is still accumulating - "
                    "one capture per run. The trend chart appears once there are a few days.</p>")
    return out or no_data()


# ===================================================================== FX
def fx(bundle):
    fxd = bundle.get("fx")
    snap = bundle.get("snapshot")
    out = ""
    if fxd is not None and len(fxd):
        cols = [x for x in ["gbp_per_usd", "gbp_per_eur"] if x in fxd.columns]
        if cols:
            out += card("Sterling cross-rates",
                        charts.line(fxd, "date", cols,
                                    labels=["GBP per USD", "GBP per EUR"]))
    if snap is not None and len(snap):
        cols = [x for x in ["usd_broad", "oil_wti"] if x in snap.columns]
        if cols:
            out += card("Dollar index & oil (WTI)",
                        charts.line(snap, "date", cols, labels=["Broad USD", "WTI oil"]))
    return out or no_data()


# ===================================================================== EQUITY
def equity(bundle):
    eq = bundle.get("equity")
    snap = bundle.get("snapshot")
    out = ""
    if eq is not None and len(eq) and "ticker" in eq.columns:
        idx_map = {"^GSPC": "S&P 500", "^FTSE": "FTSE 100", "^STOXX50E": "Euro Stoxx 50"}
        piv = eq[eq["ticker"].isin(idx_map)].copy()
        if len(piv):
            piv["price_date"] = pd.to_datetime(piv["price_date"], errors="coerce")
            wide = piv.pivot_table(index="price_date", columns="ticker",
                                   values="adj_close", aggfunc="last").reset_index()
            wide = wide.rename(columns={"price_date": "date"})
            cols = [c for c in idx_map if c in wide.columns]
            out += card("Index performance (rebased to 100)",
                        charts.line(wide, "date", cols,
                                    labels=[idx_map[c] for c in cols], rebase=True))
            # returns table
            rows = []
            latest = piv.sort_values("price_date").groupby("ticker").tail(1)
            for tk in cols:
                r = latest[latest["ticker"] == tk]
                if not len(r):
                    continue
                rr = r.iloc[0]
                rows.append([idx_map[tk],
                             stats.fmt_pct(rr.get("ret_1d")), stats.fmt_pct(rr.get("ret_21d")),
                             stats.fmt_pct(rr.get("ret_63d")), stats.fmt_pct(rr.get("ret_252d"))])
            out += card("Index returns",
                        table(["Index", "1d", "21d", "63d", "252d"], rows))
    if snap is not None and "vix" in snap.columns:
        out += card("Volatility (VIX)", charts.line(snap, "date", ["vix"], labels=["VIX"]))
    return out or no_data()


# ===================================================================== ROTATION
def rotation(bundle):
    rs = bundle.get("rel_strength")
    if rs is None or len(rs) == 0:
        return no_data()
    rr = rs.copy()
    rr["price_date"] = pd.to_datetime(rr.get("price_date"), errors="coerce")
    latest = rr[rr["price_date"] == rr["price_date"].max()]
    sect = latest[latest.get("group") == "sector_etfs"] if "group" in latest else latest
    out = ""
    if len(sect) and "excess_63d" in sect:
        s = sect.dropna(subset=["excess_63d"])
        out += card("Sector excess return vs S&P (63d)",
                    charts.diverging_bar(list(s["ticker"]),
                                         [v * 100 for v in s["excess_63d"]], xlabel="%"))
        if "rs_trend_21d" in s.columns:
            out += card("Rotation map (excess return vs RS momentum)",
                        charts.scatter([v * 100 for v in s["excess_63d"]],
                                       [v * 100 for v in s["rs_trend_21d"]],
                                       labels=list(s["ticker"]),
                                       xlabel="63d excess %", ylabel="21d RS momentum %",
                                       quadrants=True))
    return out or no_data()


# ===================================================================== FACTORS
def factors(bundle):
    fs = bundle.get("factors")
    if fs is None or len(fs) == 0 or "composite_z" not in fs.columns:
        return no_data()
    ff = fs.copy()
    ff["price_date"] = pd.to_datetime(ff.get("price_date"), errors="coerce")
    latest = ff[ff["price_date"] == ff["price_date"].max()].dropna(subset=["composite_z"])
    if not len(latest):
        return no_data("No factor scores for the latest date")
    out = card("Composite factor ranking",
               charts.hbar(list(latest["ticker"]), list(latest["composite_z"]),
                           xlabel="composite z"))
    fcols = [c for c in ["mom_z", "lowvol_z", "trend_z", "quality_z", "growth_z", "value_z"]
             if c in latest.columns]
    if fcols:
        top = latest.reindex(latest["composite_z"].abs().sort_values(ascending=False).index).head(12)
        m = top.set_index("ticker")[fcols]
        m.columns = [c.replace("_z", "") for c in m.columns]
        out += card("Factor breakdown (z-scores)", charts.heatmap(m))
    return out


# ===================================================================== VALUATION
def valuation(bundle):
    val = bundle.get("valuation")
    fun = bundle.get("fundamentals")
    if (val is None or len(val) == 0) and (fun is None or len(fun) == 0):
        return no_data()
    out = ""
    if val is not None and len(val) and "earnings_yield" in val.columns:
        vv = val.copy()
        vv["price_date"] = pd.to_datetime(vv.get("price_date"), errors="coerce")
        latest = vv[vv["price_date"] == vv["price_date"].max()]
        rows = []
        for _, r in latest.sort_values("earnings_yield", ascending=False).iterrows():
            rows.append([r.get("ticker"),
                         stats.fmt_pct(r.get("earnings_yield")),
                         stats.fmt_pct(r.get("sales_yield")),
                         stats.fmt_pct(r.get("fcf_yield")),
                         stats.fmt_num(r.get("market_cap_gbp") / 1e9, 2) if pd.notna(r.get("market_cap_gbp")) else "\u2014"])
        out += card("Valuation yields (GBP-consistent)",
                    table(["Ticker", "Earnings", "Sales", "FCF", "Mktcap \u00a3bn"], rows))
    if fun is not None and len(fun):
        fu = fun.copy()
        if "period_end" in fu.columns:
            fu["period_end"] = pd.to_datetime(fu["period_end"], errors="coerce")
            fu = fu.sort_values("period_end").groupby("ticker").tail(1)
        # quality vs value scatter
        if val is not None and "earnings_yield" in val.columns and "roe" in fu.columns:
            vv = val.copy()
            vv["price_date"] = pd.to_datetime(vv.get("price_date"), errors="coerce")
            vlatest = vv[vv["price_date"] == vv["price_date"].max()][["ticker", "earnings_yield"]]
            merged = fu.merge(vlatest, on="ticker", how="inner")
            if len(merged):
                out += card("Quality vs value (ROE vs earnings yield)",
                            charts.scatter([v * 100 for v in merged["earnings_yield"]],
                                           [v * 100 for v in merged["roe"]],
                                           labels=list(merged["ticker"]),
                                           xlabel="earnings yield %", ylabel="ROE %"))
        rows = []
        for _, r in fu.iterrows():
            rows.append([r.get("ticker"),
                         stats.fmt_pct(r.get("net_margin")), stats.fmt_pct(r.get("roe")),
                         stats.fmt_num(r.get("debt_to_equity")),
                         stats.fmt_pct(r.get("revenue_growth_yoy"))])
        out += card("Fundamentals (latest period)",
                    table(["Ticker", "Net margin", "ROE", "D/E", "Rev growth"], rows))
    return out or no_data()


# ===================================================================== JOURNAL
JOURNAL_PORTFOLIO = "main"
THESIS_TRUNC = 90


def journal(bundle):
    """Hypothetical journal & portfolio: KPI row, open positions, equity curve vs
    S&P 500, and the trade log. Always labelled hypothetical - this is a paper book,
    never to be confused with real money (see the build plan's risk register)."""
    trades = bundle.get("journal_trades")
    positions = bundle.get("positions")
    pv = bundle.get("portfolio_value")
    last_close = bundle.get("security_last_close")
    label = ('<div class="card-sub"><strong>Hypothetical</strong> - a paper journal for '
             'testing decision quality, not a brokerage account.</div>')
    if (trades is None or len(trades) == 0) and (positions is None or len(positions) == 0):
        return label + no_data("No trades logged yet - run `python -m src.journal.scan_candidates --log`")

    out = label

    # --- KPI row ---
    pv_main = pv[pv.get("portfolio") == JOURNAL_PORTFOLIO].copy() if pv is not None and len(pv) else pd.DataFrame()
    kpis = ""
    if len(pv_main):
        pv_main["date"] = pd.to_datetime(pv_main["date"], errors="coerce")
        pv_main = pv_main.dropna(subset=["date"]).sort_values("date")
        row = pv_main.iloc[-1]
        first_total = pv_main["total_value"].iloc[0]
        ret = (row["total_value"] / first_total - 1) if first_total else None
        kpis += kpi("Portfolio value", f"${stats.fmt_num(row['market_value'], 0)}",
                    spark_vals=list(pv_main["total_value"].tail(90)))
        kpis += kpi("Total return since inception",
                    stats.fmt_pct(ret) if ret is not None else "—")
        kpis += kpi("Unrealised P&L", f"${stats.fmt_num(row['unrealized_pnl'], 0)}")
        kpis += kpi("Realised P&L", f"${stats.fmt_num(row['realized_pnl_cum'], 0)}")
        kpis += kpi("Open positions", f"{int(row['n_positions_open'])}")
    if kpis:
        out += f'<div class="kpi-row">{kpis}</div>'

    # --- open positions table ---
    if positions is not None and len(positions):
        p = positions[positions.get("status") == "OPEN"].copy()
        close_map = {}
        if last_close is not None and len(last_close):
            close_map = dict(zip(last_close["ticker"], last_close["last_close"]))
        rows = []
        today = pd.Timestamp.today().normalize()
        for _, r in p.sort_values("ticker").iterrows():
            cur = close_map.get(r["ticker"])
            unreal_pct = None
            if cur is not None and pd.notna(cur) and r.get("avg_cost"):
                unreal_pct = cur / r["avg_cost"] - 1
            first = pd.to_datetime(r.get("first_entry_date"), errors="coerce")
            days_held = int((today - first).days) if pd.notna(first) else None
            thesis = (r.get("thesis") or "")
            thesis_s = (thesis[:THESIS_TRUNC] + "…") if len(thesis) > THESIS_TRUNC else thesis
            rows.append([r["ticker"], stats.fmt_num(r.get("quantity_open"), 2),
                        f"${stats.fmt_num(r.get('avg_cost'), 2)}",
                        f"${stats.fmt_num(cur, 2)}" if cur is not None else "—",
                        stats.fmt_pct(unreal_pct) if unreal_pct is not None else "—",
                        f"{days_held}d" if days_held is not None else "—",
                        r.get("conviction") or "—", thesis_s or "—"])
        out += card("Open positions (hypothetical)",
                    table(["Ticker", "Qty", "Avg cost", "Current", "Unrl. %", "Held",
                          "Conviction", "Thesis"], rows))

    # --- equity curve: journal total value vs S&P 500, both rebased to 100 ---
    if len(pv_main) >= 2:
        eq = bundle.get("equity")
        curve = pv_main[["date", "total_value"]].copy()
        if eq is not None and len(eq) and "ticker" in eq.columns:
            spx = eq[eq["ticker"] == "^GSPC"][["price_date", "adj_close"]].rename(
                columns={"price_date": "date", "adj_close": "spx"})
            spx["date"] = pd.to_datetime(spx["date"], errors="coerce")
            curve = curve.merge(spx, on="date", how="left")
        ys = [c for c in ["total_value", "spx"] if c in curve.columns]
        out += card("Equity curve vs S&P 500 (rebased to 100)",
                    charts.line(curve, "date", ys,
                                labels=["Journal (hypothetical)", "S&P 500"][:len(ys)],
                                rebase=True))

    # --- trade log ---
    if trades is not None and len(trades):
        t = trades.copy()
        t["trade_date"] = pd.to_datetime(t["trade_date"], errors="coerce")
        recent = t.sort_values("trade_date", ascending=False).head(25)
        rows = []
        for _, r in recent.iterrows():
            thesis = (r.get("thesis") or "")
            thesis_s = (thesis[:THESIS_TRUNC] + "…") if len(thesis) > THESIS_TRUNC else thesis
            rows.append([stats.fmt_date(r.get("trade_date")), r.get("ticker"), r.get("action"),
                        stats.fmt_num(r.get("quantity"), 2), f"${stats.fmt_num(r.get('price'), 2)}",
                        r.get("conviction") or "—", thesis_s or "—"])
        out += card("Trade log (most recent)",
                    table(["Date", "Ticker", "Action", "Qty", "Price", "Conviction", "Thesis"], rows))

    return out


# ===================================================================== EXTREMES
def extremes_section(bundle):
    a = bundle.get("series_analytics")
    ex = extremes(a, n=15)
    if not ex:
        return no_data()
    names = [e[0] for e in ex]
    vals = [e[1] for e in ex]
    return card("Macro series ranked by |z-score| (primary)",
                charts.diverging_bar(names, vals, xlabel="primary z-score")) + \
        card("Reading", '<div class="card-sub">Bars right of zero are unusually high '
             'versus that series\u2019 own history; left, unusually low. This is '
             '"what is unusual today".</div>')


# ===================================================================== HEADLINES
def headlines(bundle):
    hd = bundle.get("headlines")
    if hd is None or len(hd) == 0:
        return no_data("No FT headlines ingested")
    d = hd.copy()
    d["published_at"] = pd.to_datetime(d.get("published_at"), errors="coerce")
    d["published_date"] = pd.to_datetime(d.get("published_date"), errors="coerce")
    out = ""
    # volume per day
    vol = d.dropna(subset=["published_date"]).groupby(d["published_date"].dt.date).size()
    if len(vol):
        vdf = pd.DataFrame({"date": list(vol.index), "n": list(vol.values)})
        out += card("Headline volume per day",
                    charts.line(vdf, "date", ["n"], labels=["stories"], ylabel="count"))
    # recent list, grouped by day
    recent = d.sort_values("published_at", ascending=False).head(40)
    blocks = ""
    for day, g in recent.groupby(recent["published_at"].dt.date, sort=False):
        items = ""
        for _, r in g.iterrows():
            sect = f'<span class="tag">{r.get("section")}</span>' if pd.notna(r.get("section")) else ""
            link = r.get("link")
            title = r.get("title") or "\u2014"
            t = f'<a href="{link}" target="_blank" rel="noopener">{title}</a>' if pd.notna(link) else title
            items += f'<li>{sect}{t}</li>'
        blocks += f'<div class="hl-day"><div class="hl-date">{stats.fmt_date(day)}</div><ul class="hl-list">{items}</ul></div>'
    out += card("Recent headlines", blocks or no_data())
    return out


# ===================================================================== HEALTH
def health(bundle):
    cov = bundle.get("coverage") or {}
    rows = []
    for label, (mn, mx, n) in cov.items():
        stale = ""
        if mx is not None:
            days = (pd.Timestamp.today().normalize() - pd.to_datetime(mx).normalize()).days
            stale = f"{days}d ago"
        rows.append([label, stats.fmt_date(mn) if mn is not None else "\u2014",
                     stats.fmt_date(mx) if mx is not None else "\u2014",
                     f"{n:,}", stale])
    out = card("Data coverage & freshness",
               table(["Source", "From", "To", "Rows", "Last update"], rows) if rows else no_data())
    fstat = bundle.get("feed_status")
    if fstat is not None and len(fstat):
        frows = [[r.get("feed"), r.get("status"), r.get("n_items"), r.get("n_new")]
                 for _, r in fstat.iterrows()]
        out += card("FT feed status (last run)",
                    table(["Feed", "Status", "Seen", "New"], frows))
    return out


# The ordered section registry: (anchor, nav-title, heading, builder)
def registry():
    return [
        ("glance", "At a glance", "At a glance", None),   # glance handled specially (needs insights)
        ("regime", "Regime", "Macro regime", regime),
        ("rates", "Rates", "Rates & the yield curve", rates),
        ("credit", "Credit", "Credit & risk appetite", credit),
        ("volterm", "Volatility", "Volatility & term structure", vol_term),
        ("positioning", "Positioning", "Positioning (CFTC)", positioning),
        ("skew", "Skew", "Options skew", skew),
        ("fx", "FX & commodities", "FX & commodities", fx),
        ("equity", "Equity", "Equity markets", equity),
        ("rotation", "Rotation", "Sector & style rotation", rotation),
        ("factors", "Factors", "Factor screen", factors),
        ("valuation", "Valuation", "Fundamentals & valuation", valuation),
        ("journal", "Journal", "Investment journal (hypothetical)", journal),
        ("extremes", "Extremes", "Statistical extremes", extremes_section),
        ("headlines", "Headlines", "FT headlines", headlines),
        ("health", "Data health", "Data coverage & health", health),
    ]
