"""
Addition #2 orchestrator: read the COT market manifest, fetch each market's
weekly positioning from the CFTC Socrata API (incrementally, from the last date
already stored), land the raw JSON, load it idempotently into stg_cot with a
point-in-time available_from, record status, and write a markdown report.

No API key required.

Usage (from the project root):
    python -m src.extract.cot_ingest                 # all markets, incremental
    python -m src.extract.cot_ingest --only sp500,vix
    python -m src.extract.cot_ingest --full          # ignore stored state, refetch from history_start
"""
from __future__ import annotations

import argparse
import sys
import time
from datetime import datetime, timezone

from src.common.cli import clean_argv
from src.common.config import load_cot_markets, iter_cot_markets
from src.common.reporting import build_cot_report, write_report
from src.extract.cot_client import fetch_market, probe_schema
from src.load import load_cot

get_connection = load_cot.get_connection


def run(only: list[str] | None = None, full: bool = False,
        config_path: str = "config/cot_markets.yaml") -> int:
    cfg = load_cot_markets(config_path)
    markets = iter_cot_markets(cfg)
    if only:
        wanted = set(only)
        markets = [m for m in markets if m["id"] in wanted]
        if not markets:
            print("None of the requested market ids are in the config.")
            return 1

    meta = cfg["meta"]
    dataset, base = meta["dataset"], meta.get("base")
    lag = int(meta.get("release_lag_days", 3))
    history_start = meta.get("history_start", "2010-01-01")
    combined_only = bool(meta.get("combined_only", True))
    run_stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H%M%SZ")
    run_date = run_stamp[:10]

    # fail loudly if the dataset schema has drifted
    try:
        probe_schema(dataset, base)
    except Exception as e:      # noqa: BLE001
        print(f"Schema probe failed: {e}")
        return 1

    con = get_connection()
    load_cot.ensure_schema(con)

    rows_report = []
    t0 = time.time()
    print(f"Fetching {len(markets)} COT markets ...")
    for i, m in enumerate(markets, 1):
        mid, match, label = m["id"], m["match"], m["label"]
        since = None if full else load_cot.get_max_report_date(con, mid)
        since_str = since.isoformat() if since else history_start
        res = fetch_market(mid, match, dataset=dataset, base=base, since=since_str,
                           combined_only=combined_only)

        n_seen = n_new = 0
        if res.status in ("ok", "empty"):
            load_cot.save_raw_json(mid, res.raw, run_stamp)
            n_seen, n_new = load_cot.load_cot(con, mid, res.rows, lag_days=lag)
        load_cot.record_status(con, mid, label, res.status, n_seen, n_new, res.error)
        rows_report.append({"market_id": mid, "label": label, "status": res.status,
                            "n_rows": n_seen, "n_new": n_new, "error": res.error})

        flag = "" if res.status in ("ok", "empty") else f"   <- {res.status}: {res.error or ''}"
        if res.dropped_markets:
            flag += f"   (pattern matched {len(res.dropped_markets)+1}; kept '{res.chosen_market}')"
        print(f"  [{i}/{len(markets)}] {label:<18} {res.status:<6} rows={n_seen:>4} new={n_new:>3}{flag}")

    dur = time.time() - t0
    con.close()
    md = build_cot_report(rows_report, run_date, dur)
    path = write_report(md, f"reports/cot_ingest_{run_date}.md")
    total_new = sum(r["n_new"] for r in rows_report)
    print(f"\nDone in {dur:.1f}s - report: {path}  (new rows: {total_new})")
    return 0


def main() -> None:
    ap = argparse.ArgumentParser(description="Ingest CFTC Commitments of Traders positioning.")
    ap.add_argument("--only", help="comma-separated market ids")
    ap.add_argument("--full", action="store_true", help="refetch full history, ignore stored state")
    args = ap.parse_args(clean_argv())
    only = [x.strip() for x in args.only.split(",")] if args.only else None
    sys.exit(run(only=only, full=args.full))


if __name__ == "__main__":
    main()
