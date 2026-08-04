"""
Headlines storage: raw XML snapshots and the DuckDB headline tables.

The key difference from every other loader
------------------------------------------
The FRED and price loaders REPLACE each key every run (delete-then-insert the
whole series). Headlines are different: an RSS feed only carries the most recent
~30 items, so we must ACCUMULATE history across polls. This loader therefore
APPENDS and DE-DUPLICATES instead of replacing:

  * a story is identified by `item_id` (its guid, else a hash of its link);
  * re-ingesting a story we've already stored inserts nothing (idempotent);
  * because the same story appears in several feeds, feed membership is kept in
    a bridge table (`stg_headline_feeds`) - one clean row per story, one bridge
    row per (story, feed).

The warehouse grows monotonically over time; re-running is always safe.

Portability / testability
--------------------------
Every statement here is plain DB-API (`execute` / `executemany` / `fetchall`
with `?` placeholders) and dialect-neutral SQL, so the *identical* code runs
against the DuckDB warehouse in production and against an in-memory database in
tests. The one shared warehouse opener is reused from load_fred.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path

from src.load import load_fred

RAW_ROOT = "data/raw/ft"
get_connection = load_fred.get_connection      # one place opens the warehouse

_ID_CHUNK = 500                                 # keep IN-lists to a sane size


# --------------------------------------------------------------------- schema
def ensure_schema(con) -> None:
    """Create the headline tables if absent (safe to call every run)."""
    con.execute("""
        CREATE TABLE IF NOT EXISTS stg_headlines (
            item_id       VARCHAR PRIMARY KEY,   -- guid, else 'link:'+sha1(link)
            title         VARCHAR,
            summary       VARCHAR,
            link          VARCHAR,
            published_at  TIMESTAMP,             -- UTC, from the feed (may be NULL)
            first_feed    VARCHAR,               -- feed we FIRST saw the story in
            first_seen_at TIMESTAMP,             -- when WE first ingested it (UTC)
            loaded_at     TIMESTAMP
        )""")
    con.execute("""
        CREATE TABLE IF NOT EXISTS stg_headline_feeds (
            item_id  VARCHAR,
            feed     VARCHAR,
            seen_at  TIMESTAMP,
            PRIMARY KEY (item_id, feed)          -- one row per (story, feed)
        )""")
    con.execute("""
        CREATE TABLE IF NOT EXISTS ft_feed_status (
            feed        VARCHAR,
            status      VARCHAR,                 -- ok | not_modified | empty | error
            http_status INTEGER,
            n_items     INTEGER,
            n_new       INTEGER,
            error_msg   VARCHAR,
            run_at      TIMESTAMP
        )""")


def ensure_cache_schema(con) -> None:
    """The conditional-GET cache (ETag / Last-Modified per feed)."""
    con.execute("""
        CREATE TABLE IF NOT EXISTS ft_feed_cache (
            feed          VARCHAR PRIMARY KEY,
            etag          VARCHAR,
            last_modified VARCHAR,
            updated_at    TIMESTAMP
        )""")


# ------------------------------------------------------------------- the load
def _prepare(items) -> list[dict]:
    """Pure helper (no DB): drop items with no item_id, de-duplicate WITHIN the
    batch keeping the first occurrence, and normalise published_at to a naive
    UTC timestamp. Fully testable without a database."""
    seen: set[str] = set()
    out: list[dict] = []
    for it in items:
        iid = it.get("item_id")
        if not iid or iid in seen:
            continue
        seen.add(iid)
        pub = it.get("published_at")
        if isinstance(pub, datetime):
            pub = (pub.astimezone(timezone.utc).replace(tzinfo=None)
                   if pub.tzinfo is not None else pub)
        out.append({"item_id": iid, "title": it.get("title"),
                    "summary": it.get("summary"), "link": it.get("link"),
                    "published_at": pub})
    return out


def load_headlines(con, feed: str, items: list[dict]) -> tuple[int, int]:
    """Append new stories (idempotent, de-duped by item_id) and record feed
    membership. Returns (n_seen, n_new): distinct stories in this batch, and how
    many were new to the warehouse."""
    batch = _prepare(items)
    if not batch:
        return (0, 0)
    now = _utcnow()
    ids = [r["item_id"] for r in batch]

    # 1) insert only stories not already in the warehouse
    existing = _existing_ids(con, ids)
    new_rows = [r for r in batch if r["item_id"] not in existing]
    if new_rows:
        con.executemany(
            "INSERT INTO stg_headlines "
            "(item_id, title, summary, link, published_at, first_feed, first_seen_at, loaded_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            [(r["item_id"], r["title"], r["summary"], r["link"], r["published_at"],
              feed, now, now) for r in new_rows])

    # 2) record (story, feed) membership for any pair not already bridged
    bridged = _bridged_ids(con, feed, ids)
    new_pairs = [iid for iid in ids if iid not in bridged]
    if new_pairs:
        con.executemany(
            "INSERT INTO stg_headline_feeds (item_id, feed, seen_at) VALUES (?, ?, ?)",
            [(iid, feed, now) for iid in new_pairs])

    return (len(batch), len(new_rows))


def _existing_ids(con, ids: list[str]) -> set[str]:
    """Subset of `ids` already present in stg_headlines."""
    found: set[str] = set()
    for chunk in _chunks(ids, _ID_CHUNK):
        placeholders = ",".join("?" * len(chunk))
        rows = con.execute(
            f"SELECT item_id FROM stg_headlines WHERE item_id IN ({placeholders})",
            list(chunk)).fetchall()
        found.update(r[0] for r in rows)
    return found


def _bridged_ids(con, feed: str, ids: list[str]) -> set[str]:
    """Subset of `ids` already bridged to THIS feed."""
    found: set[str] = set()
    for chunk in _chunks(ids, _ID_CHUNK):
        placeholders = ",".join("?" * len(chunk))
        rows = con.execute(
            f"SELECT item_id FROM stg_headline_feeds WHERE feed = ? AND item_id IN ({placeholders})",
            [feed, *chunk]).fetchall()
        found.update(r[0] for r in rows)
    return found


def _chunks(seq, n):
    for i in range(0, len(seq), n):
        yield seq[i:i + n]


# ------------------------------------------------------------- status & cache
def record_status(con, feed, status, http_status, n_items, n_new, error_msg) -> None:
    """One latest-status row per feed (delete-then-insert)."""
    con.execute("DELETE FROM ft_feed_status WHERE feed = ?", [feed])
    con.execute(
        "INSERT INTO ft_feed_status "
        "(feed, status, http_status, n_items, n_new, error_msg, run_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        [feed, status, _int_or_none(http_status), int(n_items), int(n_new),
         error_msg, _utcnow()])


def get_feed_cache(con, feed) -> dict:
    """Return {'etag':…, 'last_modified':…} for a conditional GET, or {}."""
    row = con.execute(
        "SELECT etag, last_modified FROM ft_feed_cache WHERE feed = ?", [feed]).fetchone()
    return {} if not row else {"etag": row[0], "last_modified": row[1]}


def set_feed_cache(con, feed, etag, last_modified) -> None:
    """Store the feed's validators (delete-then-insert). No-op if both are empty."""
    if not etag and not last_modified:
        return
    con.execute("DELETE FROM ft_feed_cache WHERE feed = ?", [feed])
    con.execute(
        "INSERT INTO ft_feed_cache (feed, etag, last_modified, updated_at) "
        "VALUES (?, ?, ?, ?)", [feed, etag, last_modified, _utcnow()])


# ------------------------------------------------------------- feed dimension
def ensure_feed_dim_schema(con) -> None:
    """Descriptive lookup: each feed's group and region, mirrored from the
    manifest. Lets the gold model tag each story with a section/region."""
    con.execute("""
        CREATE TABLE IF NOT EXISTS dim_news_feed (
            feed       VARCHAR PRIMARY KEY,
            feed_group VARCHAR,
            region     VARCHAR,
            updated_at TIMESTAMP
        )""")


def upsert_feeds(con, feeds) -> int:
    """Full-replace the feed dimension from the manifest feed dicts (name, group,
    region) - so it always reflects the declared feed set, like the other dims."""
    ensure_feed_dim_schema(con)
    con.execute("DELETE FROM dim_news_feed")
    now = _utcnow()
    con.executemany(
        "INSERT INTO dim_news_feed (feed, feed_group, region, updated_at) "
        "VALUES (?, ?, ?, ?)",
        [(f["name"], f.get("group"), f.get("region"), now) for f in feeds])
    return len(feeds)


# --------------------------------------------------------------------- raw
def save_raw_xml(feed, content, run_stamp, root=RAW_ROOT):
    """Write the immutable raw feed bytes for this run. Skips empty content."""
    if not content:
        return None
    out_dir = Path(root) / run_stamp
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{_safe(feed)}.xml"
    mode = "wb" if isinstance(content, (bytes, bytearray)) else "w"
    with open(path, mode) as f:
        f.write(content)
    return str(path)


# ------------------------------------------------------------------- helpers
def _utcnow():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _int_or_none(x):
    return int(x) if x is not None else None


def _safe(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]", "_", name)
