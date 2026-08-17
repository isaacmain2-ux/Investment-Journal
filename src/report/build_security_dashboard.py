"""
P4 - the Securities dashboard: a self-contained HTML page over the factor scores.

Renders the screens (best-overall, cheapest, momentum, quality, cheap-and-good) as
tables, a value-vs-momentum scatter, and a sector view. Factor strength shows as inline
percentile bars, so a name missing a whole factor (e.g. a nulled value score) reads as
a blank bar rather than a hidden gap - you can see what a ranking is and isn't built on.

Data prep is pure and tested; render() assembles a portable HTML document (inline CSS +
a little JS for the tabs) that works on GitHub Pages and on mobile.
"""
from __future__ import annotations

import html
from datetime import date, datetime

import pandas as pd

from src.load import load_securities

get_connection = load_securities.get_connection

# (id, label, sort column, optional filter predicate on the merged row)
SCREENS = [
    ("composite", "Best overall", "composite_z", None),
    ("value", "Cheapest (value)", "value_z", lambda r: pd.notna(r.get("value_z"))),
    ("momentum", "Momentum leaders", "momentum_z", lambda r: pd.notna(r.get("momentum_z"))),
    ("quality", "Highest quality", "quality_z", lambda r: pd.notna(r.get("quality_z"))),
    ("cheapgood", "Cheap & good", "composite_z",
     lambda r: (pd.notna(r.get("value_pct")) and r.get("value_pct", 0) > 0.7
                and pd.notna(r.get("quality_pct")) and r.get("quality_pct", 0) > 0.7)),
]
_FACTORS = ["value", "momentum", "quality", "growth"]
_PALETTE = ["#4C78A8", "#F58518", "#54A24B", "#B279A2", "#E45756", "#72B7B2",
            "#EECA3B", "#FF9DA6", "#9D755D", "#BAB0AC", "#17BECF"]


# ------------------------------------------------------------------ data prep
def merge(factors: pd.DataFrame, metrics: pd.DataFrame) -> pd.DataFrame:
    m = metrics[["ticker", "asof_date", "earnings_yield", "ret_12_1m", "roe",
                 "market_cap", "pe"]] if len(metrics) else metrics
    return factors.merge(m, on=["ticker", "asof_date"], how="left", suffixes=("", "_m"))


def screen_rows(df: pd.DataFrame, sort_col: str, filt, n=25) -> list[dict]:
    d = df
    if filt is not None:
        d = d[d.apply(filt, axis=1)]
    d = d.sort_values(sort_col, ascending=False, na_position="last").head(n)
    return d.to_dict("records")


def scatter_points(df: pd.DataFrame) -> list[dict]:
    out = []
    for _, r in df.iterrows():
        if pd.notna(r.get("value_pct")) and pd.notna(r.get("momentum_pct")):
            out.append({"ticker": r["ticker"], "sector": r.get("sector"),
                        "x": float(r["value_pct"]), "y": float(r["momentum_pct"]),
                        "z": None if pd.isna(r.get("composite_z")) else float(r["composite_z"])})
    return out


def sector_summary(df: pd.DataFrame) -> list[dict]:
    rows = []
    for sector, g in df.groupby("sector"):
        cz = g["composite_z"].dropna()
        rows.append({"sector": sector or "-", "n": len(g),
                     "avg_composite": float(cz.mean()) if len(cz) else None})
    return sorted(rows, key=lambda r: (r["avg_composite"] is None, -(r["avg_composite"] or 0)))


# ------------------------------------------------------------------ render helpers
def _esc(x):
    return html.escape(str(x)) if x is not None else ""


def _fmt(x, nd=2):
    if x is None or (isinstance(x, float) and pd.isna(x)):
        return "\u2013"
    try:
        return f"{float(x):.{nd}f}"
    except (TypeError, ValueError):
        return _esc(x)


def _pct(x):
    if x is None or (isinstance(x, float) and pd.isna(x)):
        return "\u2013"
    return f"{float(x) * 100:.0f}"


def _bar(pct):
    """A small percentile bar; blank slot if the factor is absent."""
    if pct is None or (isinstance(pct, float) and pd.isna(pct)):
        return '<span class="bar empty" title="no data"></span>'
    w = max(2, min(100, float(pct) * 100))
    return f'<span class="bar"><span class="fill" style="width:{w:.0f}%"></span></span>'


def _sector_colors(df):
    secs = [s for s in dict.fromkeys(df.get("sector", pd.Series(dtype=str)).tolist()) if s]
    return {s: _PALETTE[i % len(_PALETTE)] for i, s in enumerate(sorted(secs))}


def _screen_table(rows):
    head = ("<tr><th>#</th><th>Ticker</th><th>Sector</th><th>Comp</th>"
            "<th>Value</th><th>Mom</th><th>Qual</th><th>Grow</th>"
            "<th>E/P</th><th>12-1m</th><th>ROE</th></tr>")
    body = []
    for i, r in enumerate(rows, 1):
        body.append(
            f"<tr><td class=rk>{i}</td><td class=tk>{_esc(r['ticker'])}</td>"
            f"<td class=se>{_esc(r.get('sector'))}</td>"
            f"<td class=cz>{_fmt(r.get('composite_z'))}</td>"
            f"<td>{_bar(r.get('value_pct'))}</td><td>{_bar(r.get('momentum_pct'))}</td>"
            f"<td>{_bar(r.get('quality_pct'))}</td><td>{_bar(r.get('growth_pct'))}</td>"
            f"<td class=n>{_fmt(r.get('earnings_yield'), 3)}</td>"
            f"<td class=n>{_fmt(r.get('ret_12_1m'), 2)}</td>"
            f"<td class=n>{_fmt(r.get('roe'), 2)}</td></tr>")
    return f"<table class=screen>{head}{''.join(body)}</table>"


def _scatter_svg(points, colors, w=680, h=420, pad=44):
    def X(v): return pad + v * (w - 2 * pad)
    def Y(v): return (h - pad) - v * (h - 2 * pad)
    dots = []
    for p in points:
        c = colors.get(p["sector"], "#888")
        dots.append(f'<circle cx="{X(p["x"]):.0f}" cy="{Y(p["y"]):.0f}" r="4" '
                    f'fill="{c}" opacity="0.75"><title>{_esc(p["ticker"])} '
                    f'(val {_pct(p["x"])}%, mom {_pct(p["y"])}%)</title></circle>')
    mid_x, mid_y = X(0.5), Y(0.5)
    grid = (f'<line x1="{mid_x}" y1="{pad}" x2="{mid_x}" y2="{h-pad}" class="q"/>'
            f'<line x1="{pad}" y1="{mid_y}" x2="{w-pad}" y2="{mid_y}" class="q"/>')
    labels = (f'<text x="{w-pad}" y="{pad-14}" class="ql" text-anchor="end">cheap &amp; rising \u2197</text>'
              f'<text x="{pad}" y="{h-pad+28}" class="qs">expensive \u00b7 falling</text>'
              f'<text x="{w-pad}" y="{h-pad+28}" class="ql" text-anchor="end">cheap \u00b7 falling</text>'
              f'<text x="{(w)/2:.0f}" y="{h-8}" class="ax" text-anchor="middle">value percentile \u2192</text>'
              f'<text x="14" y="{h/2:.0f}" class="ax" text-anchor="middle" '
              f'transform="rotate(-90 14 {h/2:.0f})">momentum percentile \u2192</text>')
    return (f'<svg viewBox="0 0 {w} {h}" class="scatter" xmlns="http://www.w3.org/2000/svg">'
            f'<rect x="{pad}" y="{pad}" width="{w-2*pad}" height="{h-2*pad}" class="plot"/>'
            f'{grid}{"".join(dots)}{labels}</svg>')


def _sector_table(rows):
    body = "".join(
        f"<tr><td class=tk>{_esc(r['sector'])}</td><td class=n>{r['n']}</td>"
        f"<td class=cz>{_fmt(r['avg_composite'])}</td></tr>" for r in rows)
    return f"<table class=screen><tr><th>Sector</th><th>N</th><th>Avg composite</th></tr>{body}</table>"


# ------------------------------------------------------------------ page
_CSS = """
:root{--ink:#1a2330;--mut:#6b7683;--line:#e6e9ee;--card:#fff;--bg:#f4f6f9;--accent:#2f6f4f}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);
font:14px/1.5 -apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif}
.wrap{max-width:980px;margin:0 auto;padding:20px}
h1{font-size:20px;margin:0 0 2px}.sub{color:var(--mut);font-size:13px;margin-bottom:16px}
.tabs{display:flex;flex-wrap:wrap;gap:6px;margin-bottom:14px}
.tab{padding:7px 12px;border:1px solid var(--line);border-radius:999px;background:var(--card);
cursor:pointer;font-size:13px;color:var(--mut)}.tab.on{background:var(--accent);color:#fff;border-color:var(--accent)}
.panel{display:none}.panel.on{display:block}
.card{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:14px;margin-bottom:14px;overflow-x:auto}
table.screen{border-collapse:collapse;width:100%;font-size:13px}
table.screen th{text-align:left;color:var(--mut);font-weight:600;padding:6px 8px;border-bottom:1px solid var(--line);white-space:nowrap}
table.screen td{padding:6px 8px;border-bottom:1px solid #f0f2f5;white-space:nowrap}
td.tk{font-weight:700}td.rk{color:var(--mut)}td.se{color:var(--mut)}td.n{text-align:right;font-variant-numeric:tabular-nums}
td.cz{text-align:right;font-weight:700;font-variant-numeric:tabular-nums}
.bar{display:inline-block;width:46px;height:8px;background:#eef1f4;border-radius:4px;vertical-align:middle;overflow:hidden}
.bar .fill{display:block;height:100%;background:var(--accent)}.bar.empty{background:repeating-linear-gradient(45deg,#f0f2f5,#f0f2f5 3px,#e6e9ee 3px,#e6e9ee 6px)}
svg.scatter{width:100%;height:auto}.plot{fill:#fbfcfd;stroke:var(--line)}.q{stroke:#d5dae1;stroke-dasharray:4 4}
.ql,.qs{fill:var(--mut);font-size:11px}.ax{fill:var(--mut);font-size:11px}
.note{color:var(--mut);font-size:12px;margin-top:6px}
"""

_JS = """
document.querySelectorAll('.tab').forEach(function(t){t.onclick=function(){
document.querySelectorAll('.tab').forEach(x=>x.classList.remove('on'));
document.querySelectorAll('.panel').forEach(x=>x.classList.remove('on'));
t.classList.add('on');document.getElementById(t.dataset.p).classList.add('on');};});
"""


def render(factors: pd.DataFrame, metrics: pd.DataFrame, dim: pd.DataFrame, asof) -> str:
    df = merge(factors, metrics)
    colors = _sector_colors(df)
    tabs, panels = [], []
    for i, (sid, label, sort_col, filt) in enumerate(SCREENS):
        rows = screen_rows(df, sort_col, filt)
        tabs.append(f'<div class="tab{" on" if i == 0 else ""}" data-p="p_{sid}">{_esc(label)}</div>')
        note = ('<div class=note>Cheap AND good: names in the top 30% on both value and quality.</div>'
                if sid == "cheapgood" else
                '<div class=note>Bars are cross-sectional percentiles; a hatched bar means that '
                'factor was unavailable for the name.</div>' if i == 0 else "")
        panels.append(f'<div class="panel{" on" if i == 0 else ""}" id="p_{sid}">'
                      f'<div class=card>{_screen_table(rows)}{note}</div></div>')
    # scatter + sector tabs
    tabs.append('<div class="tab" data-p="p_scatter">Value vs momentum</div>')
    tabs.append('<div class="tab" data-p="p_sector">Sectors</div>')
    legend = " ".join(f'<span style="color:{c}">\u25cf</span> {_esc(s)}' for s, c in colors.items())
    panels.append('<div class="panel" id="p_scatter"><div class=card>'
                  + _scatter_svg(scatter_points(df), colors)
                  + f'<div class=note>{legend}</div></div></div>')
    panels.append('<div class="panel" id="p_sector"><div class=card>'
                  + _sector_table(sector_summary(df)) + '</div></div>')

    n = len(df)
    return (f"<!doctype html><html><head><meta charset=utf-8>"
            f"<meta name=viewport content='width=device-width,initial-scale=1'>"
            f"<title>Securities \u2013 {_esc(asof)}</title><style>{_CSS}</style></head><body><div class=wrap>"
            f"<h1>Security selection</h1>"
            f"<div class=sub>{n} names \u00b7 ranked cross-sectionally \u00b7 as of {_esc(asof)}</div>"
            f"<div class=tabs>{''.join(tabs)}</div>{''.join(panels)}"
            f"<script>{_JS}</script></div></body></html>")


# ------------------------------------------------------------------ run
def _read(con, sql):
    cur = con.execute(sql)
    return pd.DataFrame(cur.fetchall(), columns=[d[0] for d in cur.description])


def run(con=None, out_dir="reports", asof: date | None = None) -> int:
    own = con is None
    con = con or get_connection()
    try:
        factors = _read(con, "SELECT * FROM fct_security_factors")
        if len(factors) == 0:
            print("No fct_security_factors - run build_security_factors first.")
            return 1
        if asof is None:
            asof = max(factors["asof_date"])
        factors = factors[factors["asof_date"] == asof]
        metrics = _read(con, "SELECT * FROM fct_security_metrics")
        metrics = metrics[metrics["asof_date"] == asof] if len(metrics) else metrics
        html_doc = render(factors, metrics, pd.DataFrame(), asof)
        import os
        os.makedirs(out_dir, exist_ok=True)
        path = os.path.join(out_dir, f"dashboard_securities_{asof}.html")
        with open(path, "w", encoding="utf-8") as f:
            f.write(html_doc)
        print(f"Securities dashboard: {path} ({len(factors)} names)")
        return 0
    finally:
        if own:
            con.close()


def main():
    import argparse
    import sys
    ap = argparse.ArgumentParser(description="Build the Securities dashboard page.")
    ap.add_argument("--out", default="reports")
    args = ap.parse_args()
    sys.exit(run(out_dir=args.out))


if __name__ == "__main__":
    main()
