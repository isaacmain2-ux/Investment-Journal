"""Markdown run-report builders (shared by the FRED, equity, and transform runs)."""
from __future__ import annotations
from pathlib import Path


def build_report(rows: list[dict], run_date: str, duration_s: float,
                 history_start: str, title: str = "FRED Ingestion") -> str:
    n = len(rows)
    ok = sum(1 for r in rows if r["status"] == "ok")
    empty = sum(1 for r in rows if r["status"] == "empty")
    err = sum(1 for r in rows if r["status"] == "error")
    total_obs = sum(r["n_obs"] for r in rows)
    banner = "PASS" if err == 0 else "COMPLETED WITH ISSUES"

    out = []
    out.append(f"# {title} Run \u2014 {run_date}")
    out.append("")
    out.append(f"**Result: {banner}**")
    out.append("")
    out.append(f"- Series attempted: **{n}**")
    out.append(f"- OK: **{ok}** \u00b7 Empty: **{empty}** \u00b7 Errors: **{err}**")
    out.append(f"- Total observations loaded: **{total_obs:,}**")
    out.append(f"- History start: {history_start}")
    out.append(f"- Duration: {duration_s:.1f}s")
    out.append("")

    fails = [r for r in rows if r["status"] == "error"]
    if fails:
        out.append("## Failures / flagged")
        out.append("")
        out.append("| Series | Category | Verify? | Error |")
        out.append("|---|---|---|---|")
        for r in fails:
            out.append(f"| `{r['series_id']}` | {r['category']} | "
                       f"{'yes' if r.get('verify') else ''} | {r.get('error') or ''} |")
        out.append("")

    out.append("## All series")
    out.append("")
    out.append("| Series | Name | Category | Status | Obs | First | Last |")
    out.append("|---|---|---|---|---|---|---|")
    for r in sorted(rows, key=lambda x: (x["category"], x["series_id"])):
        out.append(f"| `{r['series_id']}` | {r['name']} | {r['category']} | {r['status']} | "
                   f"{r['n_obs']} | {r.get('first_obs') or ''} | {r.get('last_obs') or ''} |")
    out.append("")
    return "\n".join(out)


def build_transform_report(table_counts: dict, regime_label, run_date: str,
                           reconciled: bool) -> str:
    banner = "PASS" if reconciled else "COMPLETED WITH ISSUES"
    out = [f"# Transform Run \u2014 {run_date}", "", f"**Result: {banner}**", "",
           f"- Gold tables built: **{len(table_counts)}**",
           f"- Reconciliation (analytics vs staging): **{'MATCH' if reconciled else 'MISMATCH'}**",
           f"- Current regime: **{regime_label or 'n/a'}**", "", "## Tables", "",
           "| Table | Rows |", "|---|---|"]
    for t in sorted(table_counts):
        out.append(f"| `{t}` | {table_counts[t]:,} |")
    out.append("")
    return "\n".join(out)


def build_headlines_report(rows: list[dict], run_date: str, duration_s: float,
                           title: str = "FT Headlines Ingestion") -> str:
    """Run-report for the FT RSS ingest. `rows` are per-feed dicts with keys:
    feed, group, status, http_status, n_items, n_new, error."""
    n = len(rows)
    ok = sum(1 for r in rows if r["status"] == "ok")
    unchanged = sum(1 for r in rows if r["status"] == "not_modified")
    empty = sum(1 for r in rows if r["status"] == "empty")
    err = sum(1 for r in rows if r["status"] == "error")
    total_new = sum(r.get("n_new", 0) for r in rows)
    total_seen = sum(r.get("n_items", 0) for r in rows)
    banner = "PASS" if err == 0 else "COMPLETED WITH ISSUES"

    out = [f"# {title} Run \u2014 {run_date}", "", f"**Result: {banner}**", "",
           f"- Feeds attempted: **{n}**",
           f"- OK: **{ok}** \u00b7 Not-modified: **{unchanged}** \u00b7 "
           f"Empty: **{empty}** \u00b7 Errors: **{err}**",
           f"- Stories seen: **{total_seen:,}** \u00b7 New this run: **{total_new:,}**",
           f"- Duration: {duration_s:.1f}s", ""]

    fails = [r for r in rows if r["status"] == "error"]
    if fails:
        out += ["## Failures / flagged", "", "| Feed | Group | HTTP | Error |", "|---|---|---|---|"]
        for r in fails:
            out.append(f"| `{r['feed']}` | {r.get('group','')} | "
                       f"{r.get('http_status') or ''} | {r.get('error') or ''} |")
        out.append("")

    out += ["## All feeds", "", "| Feed | Group | Status | Seen | New | HTTP |",
            "|---|---|---|---|---|---|"]
    for r in sorted(rows, key=lambda x: (x.get("group", ""), x["feed"])):
        out.append(f"| `{r['feed']}` | {r.get('group','')} | {r['status']} | "
                   f"{r.get('n_items',0)} | {r.get('n_new',0)} | {r.get('http_status') or ''} |")
    out.append("")
    return "\n".join(out)


def build_cot_report(rows, run_date, duration_s, title="CFTC Positioning Ingestion") -> str:
    """Run-report for the COT ingest. rows: per-market dicts with keys
    market_id, label, status, n_rows, n_new, error."""
    n = len(rows)
    ok = sum(1 for r in rows if r["status"] == "ok")
    empty = sum(1 for r in rows if r["status"] == "empty")
    err = sum(1 for r in rows if r["status"] == "error")
    total_new = sum(r.get("n_new", 0) for r in rows)
    banner = "PASS" if err == 0 and empty < n else "COMPLETED WITH ISSUES"
    out = [f"# {title} Run \u2014 {run_date}", "", f"**Result: {banner}**", "",
           f"- Markets: **{n}**  \u00b7  OK: **{ok}**  \u00b7  Empty: **{empty}**  \u00b7  Errors: **{err}**",
           f"- New weekly rows this run: **{total_new:,}**",
           f"- Duration: {duration_s:.1f}s", ""]
    bad = [r for r in rows if r["status"] != "ok"]
    if bad:
        out += ["## Flagged", "", "| Market | Status | Note |", "|---|---|---|"]
        for r in bad:
            out.append(f"| {r.get('label', r['market_id'])} | {r['status']} | "
                       f"{r.get('error') or ('no match - check the pattern' if r['status']=='empty' else '')} |")
        out.append("")
    out += ["## All markets", "", "| Market | Status | Rows | New |", "|---|---|---|---|"]
    for r in sorted(rows, key=lambda x: x.get("label", x["market_id"])):
        out.append(f"| {r.get('label', r['market_id'])} | {r['status']} | "
                   f"{r.get('n_rows',0):,} | {r.get('n_new',0):,} |")
    out.append("")
    return "\n".join(out)


def build_skew_report(rows, run_date, duration_s, title="Options Skew Capture") -> str:
    """Run-report for the skew ingest. rows: per-ticker dicts with keys
    ticker_id, label, status, put_skew, error."""
    n = len(rows)
    ok = sum(1 for r in rows if r["status"] == "ok")
    empty = sum(1 for r in rows if r["status"] == "empty")
    err = sum(1 for r in rows if r["status"] == "error")
    banner = "PASS" if err == 0 and ok > 0 else "COMPLETED WITH ISSUES"
    out = [f"# {title} \u2014 {run_date}", "", f"**Result: {banner}**", "",
           f"- Tickers: **{n}**  \u00b7  OK: **{ok}**  \u00b7  Empty: **{empty}**  \u00b7  Errors: **{err}**",
           f"- Duration: {duration_s:.1f}s",
           "- Snapshot-only source: each run adds one capture per ticker; history accumulates.", ""]
    bad = [r for r in rows if r["status"] != "ok"]
    if bad:
        out += ["## Flagged", "", "| Ticker | Status | Note |", "|---|---|---|"]
        for r in bad:
            out.append(f"| {r.get('label', r['ticker_id'])} | {r['status']} | {r.get('error') or ''} |")
        out.append("")
    out += ["## Captured", "", "| Ticker | Status | Put skew |", "|---|---|---|"]
    for r in sorted(rows, key=lambda x: x.get("label", x["ticker_id"])):
        ps = r.get("put_skew")
        out.append(f"| {r.get('label', r['ticker_id'])} | {r['status']} | "
                   f"{('%.4f' % ps) if ps is not None else '-'} |")
    out.append("")
    return "\n".join(out)


def write_report(md: str, path: str) -> str:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(md, encoding="utf-8")
    return str(p)
