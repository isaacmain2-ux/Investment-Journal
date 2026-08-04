"""
Addition #3 orchestrator: read the skew ticker manifest, capture each ticker's
current implied-volatility skew from Yahoo option chains, and append it to
stg_options_skew. Snapshot-only - each run adds one row per ticker and the table
accumulates a history over time. No API key.

Usage (from the project root):
    python -m src.extract.skew_ingest
    python -m src.extract.skew_ingest --only spx
"""
from __future__ import annotations

import argparse
import sys
import time
from datetime import date, datetime, timezone

from src.common.cli import clean_argv
from src.common.config import load_skew_tickers, iter_skew_tickers
from src.common.reporting import build_skew_report, write_report
from src.extract.skew_client import fetch_skew
from src.load import load_skew

get_connection = load_skew.get_connection


def run(only: list[str] | None = None, config_path: str = "config/skew_tickers.yaml") -> int:
    cfg = load_skew_tickers(config_path)
    tickers = iter_skew_tickers(cfg)
    if only:
        wanted = set(only)
        tickers = [t for t in tickers if t["id"] in wanted]
        if not tickers:
            print("None of the requested ticker ids are in the config.")
            return 1

    meta = cfg["meta"]
    target_dte = int(meta.get("target_dte", 30))
    m = meta.get("moneyness", {}) or {}
    m_put, m_atm, m_call = float(m.get("put", 0.90)), float(m.get("atm", 1.00)), float(m.get("call", 1.10))
    capture = date.today()

    con = get_connection()
    load_skew.ensure_schema(con)

    rows_report = []
    t0 = time.time()
    print(f"Capturing skew for {len(tickers)} tickers (target ~{target_dte}d expiry) ...")
    for i, t in enumerate(tickers, 1):
        tid, tk, label = t["id"], t["ticker"], t["label"]
        res = fetch_skew(tid, tk, target_dte=target_dte, capture_date=capture,
                         m_put=m_put, m_atm=m_atm, m_call=m_call)
        row = res.row()
        if row:
            load_skew.load_skew(con, [row])
        ps = res.measures.get("put_skew")
        load_skew.record_status(con, tid, label, res.status, ps, res.error)
        rows_report.append({"ticker_id": tid, "label": label, "status": res.status,
                            "put_skew": ps, "error": res.error})

        note = "" if res.status == "ok" else f"   <- {res.status}: {res.error or ''}"
        ps_str = f"put_skew={ps:+.4f}" if ps is not None else "put_skew=-"
        print(f"  [{i}/{len(tickers)}] {label:<20} {res.status:<6} {ps_str}{note}")

    dur = time.time() - t0
    con.close()
    md = build_skew_report(rows_report, capture.isoformat(), dur)
    path = write_report(md, f"reports/skew_ingest_{capture.isoformat()}.md")
    print(f"\nDone in {dur:.1f}s - report: {path}")
    return 0


def main() -> None:
    ap = argparse.ArgumentParser(description="Capture options-skew snapshots from Yahoo option chains.")
    ap.add_argument("--only", help="comma-separated ticker ids")
    args = ap.parse_args(clean_argv())
    only = [x.strip() for x in args.only.split(",")] if args.only else None
    sys.exit(run(only=only))


if __name__ == "__main__":
    main()
