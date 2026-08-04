"""
Phase 1b orchestrator: read securities.yaml, fetch daily prices in batches,
land raw Parquet, load into the warehouse, record status, write a run-report.

Usage (from the project root):
    python -m src.extract.yf_ingest                     # full universe
    python -m src.extract.yf_ingest --only ^GSPC,AAPL,SHEL.L   # smoke run
"""
from __future__ import annotations

import argparse
import sys
import time
from datetime import date

from src.common.config import load_securities, iter_securities
from src.common.reporting import build_report, write_report
from src.extract.yf_client import fetch_prices, PriceResult
from src.common.cli import clean_argv
from src.load import load_fred, load_yf


def run(only: list[str] | None = None,
        config_path: str = "config/securities.yaml") -> int:
    cfg = load_securities(config_path)
    all_secs = iter_securities(cfg)
    secs = all_secs
    if only:
        wanted = set(only)
        secs = [s for s in all_secs if s["ticker"] in wanted]
        if not secs:
            print("None of the requested tickers are in the config.")
            return 1

    start = cfg["meta"].get("history_start", "2010-01-01")
    batch_size = cfg["meta"].get("batch_size", 30)
    run_date = date.today().isoformat()

    con = load_fred.get_connection()
    load_yf.ensure_schema(con)
    load_yf.upsert_dim(con, all_secs)          # dimension always reflects the full config

    tickers = [s["ticker"] for s in secs]
    print(f"Fetching {len(tickers)} tickers from {start} (batch {batch_size}) ...")
    t0 = time.time()
    results = fetch_prices(tickers, start=start, batch_size=batch_size)

    rows = []
    for s in secs:
        tk = s["ticker"]
        res = results.get(tk) or PriceResult(tk, status="error", error="no result")
        load_yf.save_raw_parquet(tk, res.df, run_date)
        load_yf.load_prices(con, tk, res.df if res.status == "ok" else None)

        has = res.status == "ok" and len(res.df) > 0
        first = res.df["price_date"].min() if has else None
        last = res.df["price_date"].max() if has else None
        load_yf.record_status(con, tk, res.status, res.n_obs, first, last, res.error)

        rows.append({"series_id": tk, "name": s["name"], "category": s["group"],
                     "verify": False, "status": res.status, "n_obs": res.n_obs,
                     "first_obs": first, "last_obs": last, "error": res.error})
        flag = "" if res.status == "ok" else f"   <- {res.status}: {res.error or ''}"
        print(f"  {tk:<12} {res.status:<6} {res.n_obs:>6} obs{flag}")

    dur = time.time() - t0
    con.close()

    md = build_report(rows, run_date, dur, start, title="Equity Ingestion")
    report_path = write_report(md, f"reports/yf_ingest_{run_date}.md")

    ok = sum(1 for r in rows if r["status"] == "ok")
    empty = sum(1 for r in rows if r["status"] == "empty")
    err = sum(1 for r in rows if r["status"] == "error")
    print(f"\nDone in {dur:.1f}s  ->  report: {report_path}")
    print(f"OK={ok}  Empty={empty}  Errors={err}")
    return 0


def main() -> None:
    ap = argparse.ArgumentParser(description="Ingest equity/ETF prices into the warehouse.")
    ap.add_argument("--only", help="comma-separated tickers for a subset (smoke run)")
    args = ap.parse_args(clean_argv())
    only = [x.strip() for x in args.only.split(",")] if args.only else None
    sys.exit(run(only=only))


if __name__ == "__main__":
    main()
