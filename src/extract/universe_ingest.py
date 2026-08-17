"""
Security-selection P1 orchestrator: build the universe and populate its two staging
tables from the free sources.

    constituents CSV  -> dim_security
    Yahoo (batched)   -> stg_security_prices        (all names in a few chunked calls)
    SEC EDGAR         -> stg_security_fundamentals   (XBRL facts, point-in-time, per name)

Prices are one batched download for the whole universe (per-ticker calls throttle);
fundamentals are per-name from SEC (which is fine per-name and has no such limit).
Everything loads idempotently, so re-runs extend history without dupes.

Usage (from the project root):
    python -m src.extract.universe_ingest
    python -m src.extract.universe_ingest --only AAPL,MSFT
    python -m src.extract.universe_ingest --no-fundamentals      # prices only (fast)
"""
from __future__ import annotations

import argparse
import sys
import time

from src.common.config import load_securities_universe, read_constituents
from src.extract import sec_client, yahoo_prices
from src.load import load_securities

get_connection = load_securities.get_connection


def run(only=None, config_path="config/securities_universe.yaml",
        prices=True, fundamentals=True) -> int:
    cfg = load_securities_universe(config_path)
    meta = cfg["meta"]
    ua = meta.get("sec_user_agent", "")
    price_start = str(meta.get("price_start", "2015-01-01"))
    names = read_constituents(meta["constituents"])
    if only:
        wanted = {t.upper() for t in only}
        names = [c for c in names if c["ticker"] in wanted]
    if not names:
        print("No constituents to ingest (check the manifest / --only).")
        return 1
    if fundamentals and ("your-email@example.com" in ua or not ua):
        print("!! Set meta.sec_user_agent to your real contact email in the manifest "
              "before fetching SEC data (SEC blocks the default/placeholder UA).")
        return 1

    con = get_connection()
    load_securities.ensure_schema(con)
    load_securities.upsert_securities(con, names)
    tickers = [c["ticker"] for c in names]
    t0 = time.time()

    # -------- prices: one batched download for the whole universe --------
    if prices:
        print(f"Downloading prices for {len(tickers)} names from {price_start} (batched) ...")
        rows, failed = yahoo_prices.fetch_prices_batch(tickers, start=price_start)
        if rows:
            seen, new = load_securities.load_prices(con, rows)
            print(f"  prices: {new} new / {seen} rows for {len(tickers) - len(failed)} names")
        if failed:
            shown = ", ".join(failed[:15]) + (" ..." if len(failed) > 15 else "")
            print(f"  price MISSES ({len(failed)}): {shown}")

    # -------- fundamentals: per name from SEC --------
    if fundamentals:
        cik_map = None
        ok_f = 0
        print(f"Fetching fundamentals for {len(names)} names from SEC ...")
        for i, c in enumerate(names, 1):
            tk, cik = c["ticker"], c.get("cik")
            if not cik:
                if cik_map is None:
                    cik_map = sec_client.load_cik_map(ua)
                cik = cik_map.get(tk)
            if cik:
                fr = sec_client.fetch_fundamentals(tk, cik, ua)
                if fr.rows:
                    load_securities.load_fundamentals(con, fr.rows)
                    ok_f += 1
            if i % 50 == 0:
                print(f"    ...{i}/{len(names)}")
        print(f"  fundamentals ok for {ok_f}/{len(names)}")

    con.close()
    print(f"\nDone in {time.time() - t0:.0f}s.")
    return 0


def main() -> None:
    ap = argparse.ArgumentParser(description="Ingest the security universe (prices + fundamentals).")
    ap.add_argument("--only", help="comma-separated tickers")
    ap.add_argument("--no-prices", action="store_true")
    ap.add_argument("--no-fundamentals", action="store_true")
    args = ap.parse_args()
    only = [x.strip() for x in args.only.split(",")] if args.only else None
    sys.exit(run(only=only, prices=not args.no_prices, fundamentals=not args.no_fundamentals))


if __name__ == "__main__":
    main()
