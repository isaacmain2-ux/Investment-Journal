"""
Dashboard orchestrator.

    python -m src.report.build_dashboard            -> reports/dashboard_<date>.html
    python -m src.report.build_dashboard --open     -> also open it in the browser
    python -m src.report.build_dashboard --out DIR  -> custom output folder

`render(bundle)` is pure - it turns a bundle of DataFrames into the full HTML
string, so it is fully testable without a database. `run(con)` gathers the
bundle from DuckDB, renders it, and writes the dated, self-contained file.
"""
from __future__ import annotations

import argparse
import sys
from datetime import date, datetime
from pathlib import Path

from . import charts, insights, queries, sections, stats
from src.common.cli import clean_argv

CSS = (Path(__file__).parent / "assets" / "dashboard.css").read_text(encoding="utf-8")
FONTS = ("https://fonts.googleapis.com/css2?family=IBM+Plex+Serif:wght@400;500;600"
         "&family=IBM+Plex+Sans:wght@400;500;600&family=IBM+Plex+Mono:wght@400;500&display=swap")


def _hero(bundle):
    aod = stats.as_of(bundle.get("snapshot"), bundle.get("regime"))
    reg = bundle.get("regime")
    label = None
    if reg is not None and len(reg) and "regime_label" in reg.columns:
        rl = reg.dropna(subset=["regime_label"])
        if len(rl):
            label = rl.sort_values("date").iloc[-1]["regime_label"]
    regime_html = (f'<div class="regime"><span>Current regime</span><b>{label}</b></div>'
                   if label else "")
    return (f'<div class="hero"><div><h1>Investment Journal \u2014 Dashboard</h1>'
            f'<div class="sub">generated {datetime.now():%Y-%m-%d %H:%M} \u00b7 '
            f'data as of {stats.fmt_date(aod) if aod else "n/a"}</div></div>'
            f'{regime_html}</div>')


def render(bundle: dict) -> str:
    """Pure: bundle of DataFrames -> full self-contained HTML string."""
    flags = insights.build(bundle)
    reg = sections.registry()

    # nav
    nav = '<div class="brand">Investment Journal<small>data dashboard</small></div><nav class="nav">'
    for anchor, navtitle, _, _ in reg:
        nav += f'<a href="#{anchor}">{navtitle}</a>'
    nav += "</nav>"

    # sections
    body = ""
    for anchor, _, heading, builder in reg:
        if anchor == "glance":
            inner = sections.glance(bundle, flags)
        else:
            try:
                inner = builder(bundle)
            except Exception as e:      # noqa: BLE001 - a section must never sink the report
                inner = sections.no_data(f"section error: {e}")
        body += (f'<section id="{anchor}"><div class="eyebrow">// {anchor}</div>'
                 f'<h2>{heading}</h2>{inner}</section>')

    foot = ('<div class="foot">Generated locally from the DuckDB warehouse \u2014 no network, '
            'no external data. See the master handbook and code deep-dive for the methodology '
            'behind every measure.</div>')

    return (f'<!DOCTYPE html><html lang="en"><head><meta charset="UTF-8">'
            f'<meta name="viewport" content="width=device-width, initial-scale=1.0">'
            f'<title>Investment Journal \u2014 Dashboard</title>'
            f'<link rel="preconnect" href="https://fonts.googleapis.com">'
            f'<link href="{FONTS}" rel="stylesheet"><style>{CSS}</style></head><body>'
            f'<div class="shell"><aside class="sidebar">{nav}</aside>'
            f'<main class="content">{_hero(bundle)}{body}{foot}</main></div></body></html>')


def run(con=None, out_dir: str = "reports", open_after: bool = False) -> str:
    close = False
    if con is None:
        from src.load import load_fred
        con = load_fred.get_connection()
        close = True
    try:
        bundle = queries.gather(con)
    finally:
        if close:
            con.close()

    html = render(bundle)
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    path = out / f"dashboard_{date.today().isoformat()}.html"
    path.write_text(html, encoding="utf-8")
    print(f"Dashboard written: {path}")
    if open_after:
        import webbrowser
        webbrowser.open(path.resolve().as_uri())
    return str(path)


def main() -> None:
    ap = argparse.ArgumentParser(description="Build the Investment Journal dashboard report.")
    ap.add_argument("--out", default="reports", help="output folder (default: reports)")
    ap.add_argument("--open", action="store_true", help="open the report after building")
    args = ap.parse_args(clean_argv())
    run(out_dir=args.out, open_after=args.open)


if __name__ == "__main__":
    main()
