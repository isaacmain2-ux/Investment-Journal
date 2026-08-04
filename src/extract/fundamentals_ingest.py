"""
Phase 1b-2 orchestrator: fetch company fundamentals for the WATCHLIST only
(indices and ETFs have no financial statements), land raw Parquet, load into the
warehouse, and write a run-report.

Usage (from the project root):
    python -m src.extract.fundamentals_ingest                # whole watchlist
    python -m src.extract.fundamentals_ingest --only AAPL,SHEL.L   # smoke run
"""
from __future__ import annotations

import argparse
import sys
import time
from datetime import date

from src.common.cli import clean_argv
from src.common.config import load_securities, iter_securities
from src.common.reporting import build_report, write_report
from src.extract.yf_fundamentals import fetch_fundamentals, fetch_meta, FundamentalsResult
from src.load import load_fred, load_fundamentals


def run(only: list[str] | None = None,
        config_path: str = "config/securities.yaml",
        pace: float = 2.0) -> int:
    cfg = load_securities(config_path)
    # fundamentals only make sense for individual companies
    secs = [s for s in iter_securities(cfg) if s["type"] == "stock"]
    if only:
        wanted = set(only)
        secs = [s for s in secs if s["ticker"] in wanted]
    if not secs:
        print("No matching watchlist stocks in the config.")
        return 1

    run_date = date.today().isoformat()
    con = load_fred.get_connection()
    load_fundamentals.ensure_schema(con)
    load_fundamentals.ensure_meta_schema(con)

    tickers = [s["ticker"] for s in secs]
    print(f"Fetching fundamentals for {len(tickers)} stocks "
          f"(paced {pace}s apart - this is the slow one) ...")
    t0 = time.time()
    results = fetch_fundamentals(tickers, pace=pace)

    rows = []
    for s in secs:
        tk = s["ticker"]
        res = results.get(tk) or FundamentalsResult(tk, status="error", error="no result")
        load_fundamentals.save_raw_parquet(tk, res.df, run_date)
        load_fundamentals.load_fundamentals(con, tk, res.df if res.status == "ok" else None)

        has = res.status == "ok" and len(res.df) > 0
        first = res.df["period_end"].min() if has else None
        last = res.df["period_end"].max() if has else None
        load_fundamentals.record_status(con, tk, res.status, res.n_obs, first, last, res.error)

        rows.append({"series_id": tk, "name": s["name"], "category": s.get("sector") or "n/a",
                     "verify": False, "status": res.status, "n_obs": res.n_obs,
                     "first_obs": first, "last_obs": last, "error": res.error})
        flag = "" if res.status == "ok" else f"   <- {res.status}: {res.error or ''}"
        print(f"  {tk:<12} {res.status:<6} {res.n_obs:>6} rows{flag}")

    dur = time.time() - t0

    # reporting currency + share metadata (needed for safe valuation ratios later)
    print("Fetching reporting currency / share metadata ...")
    meta = fetch_meta(tickers, pace=min(pace, 1.0))
    n_meta = load_fundamentals.upsert_meta(con, meta)
    n_ccy = sum(1 for v in meta.values() if v.get("financial_currency"))
    print(f"  meta stored for {n_meta} tickers ({n_ccy} with a reporting currency)")

    con.close()

    md = build_report(rows, run_date, dur, "n/a", title="Fundamentals Ingestion")
    report_path = write_report(md, f"reports/fundamentals_{run_date}.md")

    ok = sum(1 for r in rows if r["status"] == "ok")
    empty = sum(1 for r in rows if r["status"] == "empty")
    err = sum(1 for r in rows if r["status"] == "error")
    print(f"\nDone in {dur:.1f}s  ->  report: {report_path}")
    print(f"OK={ok}  Empty={empty}  Errors={err}")
    return 0


def main() -> None:
    ap = argparse.ArgumentParser(description="Ingest watchlist fundamentals.")
    ap.add_argument("--only", help="comma-separated tickers for a subset (smoke run)")
    ap.add_argument("--pace", type=float, default=2.0,
                    help="seconds between tickers (raise if rate-limited)")
    args = ap.parse_args(clean_argv())
    only = [x.strip() for x in args.only.split(",")] if args.only else None
    sys.exit(run(only=only, pace=args.pace))


if __name__ == "__main__":
    main()