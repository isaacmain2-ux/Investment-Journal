"""
Phase 2 pre-flight: fetch every configured FT feed once and report how many
items each returns. A green pre-flight confirms the feed URLs are live and the
network path works before a full ingest. No warehouse writes, no API key.

Usage (from the project root):
    python -m src.extract.ft_preflight
"""
from __future__ import annotations

import sys

from src.common.config import load_feeds, iter_feeds
from src.extract.rss_client import fetch_feed, DEFAULT_UA


def main(config_path: str = "config/news_feeds.yaml") -> int:
    cfg = load_feeds(config_path)
    feeds = iter_feeds(cfg)
    user_agent = cfg["meta"].get("user_agent") or DEFAULT_UA

    print(f"Checking {len(feeds)} FT feeds ...")
    reachable = 0
    for fd in feeds:
        res = fetch_feed(fd["name"], fd["url"], user_agent=user_agent)
        good = res.status in ("ok", "empty", "not_modified")
        reachable += good
        mark = "ok " if good else "!! "
        print(f"  {mark}{fd['name']:<16} {res.status:<10} "
              f"http={res.http_status} items={res.n_items} {res.error or ''}")

    print(f"\n{reachable}/{len(feeds)} feeds reachable.")
    return 0 if reachable == len(feeds) else 1


if __name__ == "__main__":
    sys.exit(main())
