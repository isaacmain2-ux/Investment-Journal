"""
Phase 2 orchestrator: read the news-feed manifest, fetch each FT RSS feed (with
a conditional GET), land the raw XML, append-and-de-dupe the headlines into the
warehouse, update the feed cache, record status, and write a markdown report.

No API key is required.

Usage (from the project root):
    python -m src.extract.ft_ingest                      # all feeds
    python -m src.extract.ft_ingest --only home,markets  # smoke run
"""
from __future__ import annotations

import argparse
import sys
import time
from datetime import datetime, timezone

from src.common.config import load_feeds, iter_feeds
from src.common.reporting import build_headlines_report, write_report
from src.extract.rss_client import fetch_feed, DEFAULT_UA
from src.common.cli import clean_argv
from src.load import load_headlines

get_connection = load_headlines.get_connection


def run(only: list[str] | None = None,
        config_path: str = "config/news_feeds.yaml") -> int:
    cfg = load_feeds(config_path)
    all_feeds = iter_feeds(cfg)
    feeds = all_feeds
    if only:
        wanted = set(only)
        feeds = [f for f in all_feeds if f["name"] in wanted]
        if not feeds:
            print("None of the requested feed names are in the config.")
            return 1

    user_agent = cfg["meta"].get("user_agent") or DEFAULT_UA
    run_stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H%M%SZ")
    run_date = run_stamp[:10]

    con = get_connection()
    load_headlines.ensure_schema(con)
    load_headlines.ensure_cache_schema(con)
    load_headlines.upsert_feeds(con, all_feeds)   # feed dim reflects the full manifest

    rows = []
    t0 = time.time()
    print(f"Fetching {len(feeds)} FT feeds ...")
    for i, fd in enumerate(feeds, 1):
        name, url, group = fd["name"], fd["url"], fd.get("group", "")

        # send the stored validators so an unchanged feed can answer 304
        cache = load_headlines.get_feed_cache(con, name)
        res = fetch_feed(name, url, etag=cache.get("etag"),
                         last_modified=cache.get("last_modified"),
                         user_agent=user_agent)

        n_seen = n_new = 0
        if res.status in ("ok", "empty"):
            load_headlines.save_raw_xml(name, res.raw, run_stamp)   # land immutable raw
            n_seen, n_new = load_headlines.load_headlines(con, name, res.items)
            load_headlines.set_feed_cache(con, name, res.etag, res.last_modified)
        # (not_modified / error: nothing to land or load; cache is left intact)

        load_headlines.record_status(con, name, res.status, res.http_status,
                                     n_seen, n_new, res.error)
        rows.append({"feed": name, "group": group, "status": res.status,
                     "http_status": res.http_status, "n_items": n_seen,
                     "n_new": n_new, "error": res.error})

        flag = "" if res.status in ("ok", "not_modified", "empty") else \
            f"   <- {res.status}: {res.error or ''}"
        print(f"  [{i:>2}/{len(feeds)}] {name:<16} {res.status:<12} "
              f"seen={n_seen:>3} new={n_new:>3}{flag}")

    dur = time.time() - t0
    con.close()

    md = build_headlines_report(rows, run_date, dur)
    report_path = write_report(md, f"reports/ft_ingest_{run_date}.md")

    ok = sum(1 for r in rows if r["status"] == "ok")
    unchanged = sum(1 for r in rows if r["status"] == "not_modified")
    errs = sum(1 for r in rows if r["status"] == "error")
    total_new = sum(r["n_new"] for r in rows)
    print(f"\nDone in {dur:.1f}s - report: {report_path}")
    print(f"OK={ok}  Not-modified={unchanged}  Errors={errs}  New stories={total_new}")
    return 0


def main() -> None:
    ap = argparse.ArgumentParser(description="Ingest FT RSS headlines into the warehouse.")
    ap.add_argument("--only", help="comma-separated feed names to run a subset (smoke test)")
    args = ap.parse_args(clean_argv())
    only = [x.strip() for x in args.only.split(",")] if args.only else None
    sys.exit(run(only=only))


if __name__ == "__main__":
    main()
