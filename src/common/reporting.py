"""
Builds the markdown run-report that documents each ingestion run — the
human-readable proof of what loaded, what didn't, and why.
"""
from __future__ import annotations

from pathlib import Path


def build_report(rows: list[dict], run_date: str, duration_s: float,
                 history_start: str) -> str:
    """`rows` is one dict per series with keys:
    series_id, name, category, verify, status, n_obs, first_obs, last_obs, error."""
    n = len(rows)
    ok = sum(1 for r in rows if r["status"] == "ok")
    empty = sum(1 for r in rows if r["status"] == "empty")
    err = sum(1 for r in rows if r["status"] == "error")
    total_obs = sum(r["n_obs"] for r in rows)
    banner = "PASS" if err == 0 else "COMPLETED WITH ISSUES"

    out = []
    out.append(f"# FRED Ingestion Run — {run_date}")
    out.append("")
    out.append(f"**Result: {banner}**")
    out.append("")
    out.append(f"- Series attempted: **{n}**")
    out.append(f"- OK: **{ok}** · Empty: **{empty}** · Errors: **{err}**")
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
            out.append(
                f"| `{r['series_id']}` | {r['category']} | "
                f"{'yes' if r.get('verify') else ''} | {r.get('error') or ''} |"
            )
        out.append("")

    out.append("## All series")
    out.append("")
    out.append("| Series | Name | Category | Status | Obs | First | Last |")
    out.append("|---|---|---|---|---|---|---|")
    for r in sorted(rows, key=lambda x: (x["category"], x["series_id"])):
        out.append(
            f"| `{r['series_id']}` | {r['name']} | {r['category']} | {r['status']} | "
            f"{r['n_obs']} | {r.get('first_obs') or ''} | {r.get('last_obs') or ''} |"
        )
    out.append("")
    return "\n".join(out)


def build_transform_report(table_counts: dict, regime_label, run_date: str,
                           reconciled: bool) -> str:
    """Markdown report for a transform run: tables built, reconciliation, regime."""
    banner = "PASS" if reconciled else "COMPLETED WITH ISSUES"
    out = []
    out.append(f"# Transform Run — {run_date}")
    out.append("")
    out.append(f"**Result: {banner}**")
    out.append("")
    out.append(f"- Gold tables built: **{len(table_counts)}**")
    out.append(f"- Reconciliation (analytics vs staging): "
               f"**{'MATCH' if reconciled else 'MISMATCH'}**")
    out.append(f"- Current regime: **{regime_label or 'n/a'}**")
    out.append("")
    out.append("## Tables")
    out.append("")
    out.append("| Table | Rows |")
    out.append("|---|---|")
    for t in sorted(table_counts):
        out.append(f"| `{t}` | {table_counts[t]:,} |")
    out.append("")
    return "\n".join(out)


def write_report(md: str, path: str) -> str:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(md, encoding="utf-8")
    return str(p)
