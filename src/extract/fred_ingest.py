"""
Phase 1a orchestrator: read the config, fetch each FRED series, land a raw
Parquet snapshot, load it into the DuckDB warehouse, record status, and write
a markdown run-report.

Usage (from the project root):
    python -m src.extract.fred_ingest                       # full run (all series)
    python -m src.extract.fred_ingest --only DGS10,CPIAUCSL,BAMLC0A0CM   # smoke run
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from datetime import date

from dotenv import load_dotenv

from src.common.config import load_config, iter_series
from src.common.reporting import build_report, write_report
from src.extract.fred_client import fetch_series
from src.load import load_fred


def run(only: list[str] | None = None,
        config_path: str = "config/macro_series.yaml") -> int:
    load_dotenv()
    key = os.environ.get("FRED_API_KEY")
    if not key:
        print("FRED_API_KEY not found in .env — add it and retry.")
        return 1

    cfg = load_config(config_path)
    all_series = iter_series(cfg)
    series = all_series
    if only:
        wanted = set(only)
        series = [s for s in all_series if s["id"] in wanted]
        if not series:
            print("None of the requested series ids are in the config.")
            return 1

    start = cfg["meta"].get("history_start", "2005-01-01")
    run_date = date.today().isoformat()

    con = load_fred.get_connection()
    load_fred.ensure_schema(con)
    load_fred.upsert_dim(con, all_series)   # dimension always reflects the full config

    rows = []
    t0 = time.time()
    print(f"Ingesting {len(series)} series from {start} ...")
    for i, s in enumerate(series, 1):
        sid = s["id"]
        res = fetch_series(sid, key, start=start)
        load_fred.save_raw_parquet(sid, res.df, run_date)
        load_fred.load_observations(con, sid, res.df if res.status == "ok" else None)

        has_data = res.status == "ok" and len(res.df) > 0
        first = res.df["obs_date"].min() if has_data else None
        last = res.df["obs_date"].max() if has_data else None
        load_fred.record_status(con, sid, res.status, res.n_obs, first, last, res.error)

        rows.append({
            "series_id": sid, "name": s["name"], "category": s["category"],
            "verify": s.get("verify", False), "status": res.status,
            "n_obs": res.n_obs, "first_obs": first, "last_obs": last, "error": res.error,
        })
        flag = "" if res.status == "ok" else f"   <- {res.status}: {res.error or ''}"
        print(f"  [{i:>2}/{len(series)}] {sid:<16} {res.status:<6} {res.n_obs:>6} obs{flag}")

    dur = time.time() - t0
    con.close()

    md = build_report(rows, run_date, dur, start)
    report_path = write_report(md, f"reports/fred_ingest_{run_date}.md")

    ok = sum(1 for r in rows if r["status"] == "ok")
    empty = sum(1 for r in rows if r["status"] == "empty")
    errs = sum(1 for r in rows if r["status"] == "error")
    print(f"\nDone in {dur:.1f}s — report: {report_path}")
    print(f"OK={ok}  Empty={empty}  Errors={errs}")
    return 0


def main() -> None:
    ap = argparse.ArgumentParser(description="Ingest FRED series into the warehouse.")
    ap.add_argument("--only", help="comma-separated series ids to run a subset (smoke test)")
    args = ap.parse_args()
    only = [x.strip() for x in args.only.split(",")] if args.only else None
    sys.exit(run(only=only))


if __name__ == "__main__":
    main()
