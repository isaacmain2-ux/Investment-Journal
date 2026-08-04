"""Tests for src/load/load_headlines.py against an in-memory DuckDB.
Skips if duckdb is absent. Proves the append-and-de-dupe behaviour that makes
the headline store accumulate history without ever duplicating a story."""
from datetime import datetime, timezone

import pytest

duckdb = pytest.importorskip("duckdb")

from src.load import load_headlines


def _con():
    con = duckdb.connect(":memory:")
    load_headlines.ensure_schema(con)
    load_headlines.ensure_cache_schema(con)
    return con


def _item(i, **kw):
    d = {"item_id": f"story-{i:04d}", "title": f"Headline {i}",
         "summary": f"Summary {i}", "link": f"https://ft.com/{i}",
         "published_at": datetime(2026, 1, 7, 8, 0, tzinfo=timezone.utc)}
    d.update(kw)
    return d


def _count(con, table):
    return con.execute(f"SELECT count(*) FROM {table}").fetchone()[0]


# --------------------------------------------------------- append + idempotency
def test_first_load_inserts_all():
    con = _con()
    n_seen, n_new = load_headlines.load_headlines(con, "markets", [_item(1), _item(2)])
    assert (n_seen, n_new) == (2, 2)
    assert _count(con, "stg_headlines") == 2
    assert _count(con, "stg_headline_feeds") == 2


def test_reingest_same_batch_adds_nothing():
    con = _con()
    load_headlines.load_headlines(con, "markets", [_item(1), _item(2)])
    n_seen, n_new = load_headlines.load_headlines(con, "markets", [_item(1), _item(2)])
    assert (n_seen, n_new) == (2, 0)                 # seen 2, none new
    assert _count(con, "stg_headlines") == 2         # no duplication
    assert _count(con, "stg_headline_feeds") == 2


def test_append_new_stories_does_not_replace():
    con = _con()
    load_headlines.load_headlines(con, "markets", [_item(1), _item(2)])
    # next poll: one old story rolls forward, two brand-new ones appear
    n_seen, n_new = load_headlines.load_headlines(con, "markets", [_item(2), _item(3), _item(4)])
    assert (n_seen, n_new) == (3, 2)
    assert _count(con, "stg_headlines") == 4         # accumulates, never shrinks


def test_dedupe_within_a_batch():
    con = _con()
    n_seen, n_new = load_headlines.load_headlines(con, "markets", [_item(1), _item(1), _item(2)])
    assert (n_seen, n_new) == (2, 2)                 # the in-batch duplicate is collapsed
    assert _count(con, "stg_headlines") == 2


def test_items_without_id_are_skipped():
    con = _con()
    n_seen, n_new = load_headlines.load_headlines(
        con, "markets", [_item(1), {"item_id": None, "title": "no id"}])
    assert (n_seen, n_new) == (1, 1)


# --------------------------------------------------------- cross-feed de-dupe
def test_same_story_across_feeds_is_one_row_two_bridges():
    con = _con()
    load_headlines.load_headlines(con, "markets", [_item(1)])
    load_headlines.load_headlines(con, "home", [_item(1)])       # same story, different feed
    assert _count(con, "stg_headlines") == 1                      # still one story
    assert _count(con, "stg_headline_feeds") == 2                 # bridged to both feeds
    # first_feed records where we FIRST saw it
    assert con.execute("SELECT first_feed FROM stg_headlines").fetchone()[0] == "markets"
    feeds = {r[0] for r in con.execute(
        "SELECT feed FROM stg_headline_feeds WHERE item_id='story-0001'").fetchall()}
    assert feeds == {"markets", "home"}


def test_reingest_same_story_same_feed_no_extra_bridge():
    con = _con()
    load_headlines.load_headlines(con, "home", [_item(1)])
    load_headlines.load_headlines(con, "home", [_item(1)])
    assert _count(con, "stg_headline_feeds") == 1                 # (story,feed) not duplicated


# --------------------------------------------------------- data fidelity
def test_null_published_at_is_stored():
    con = _con()
    load_headlines.load_headlines(con, "markets", [_item(1, published_at=None)])
    assert con.execute("SELECT published_at FROM stg_headlines").fetchone()[0] is None


def test_published_at_normalised_to_utc():
    con = _con()
    load_headlines.load_headlines(con, "markets", [_item(1)])
    got = con.execute("SELECT published_at FROM stg_headlines").fetchone()[0]
    assert got == datetime(2026, 1, 7, 8, 0)         # tz-aware UTC -> naive UTC


def test_empty_batch():
    con = _con()
    assert load_headlines.load_headlines(con, "markets", []) == (0, 0)


# --------------------------------------------------------- status & cache
def test_record_status():
    con = _con()
    load_headlines.record_status(con, "markets", "ok", 200, 30, 5, None)
    load_headlines.record_status(con, "markets", "not_modified", 304, 0, 0, None)  # latest wins
    row = con.execute("SELECT status, http_status, n_new FROM ft_feed_status "
                      "WHERE feed='markets'").fetchone()
    assert row == ("not_modified", 304, 0)
    assert _count(con, "ft_feed_status") == 1        # one row per feed


def test_feed_cache_roundtrip():
    con = _con()
    assert load_headlines.get_feed_cache(con, "markets") == {}    # nothing yet
    load_headlines.set_feed_cache(con, "markets", "etag-1", "Wed, 07 Jan 2026 00:00:00 GMT")
    assert load_headlines.get_feed_cache(con, "markets") == {
        "etag": "etag-1", "last_modified": "Wed, 07 Jan 2026 00:00:00 GMT"}
    load_headlines.set_feed_cache(con, "markets", "etag-2", None)  # update
    assert load_headlines.get_feed_cache(con, "markets")["etag"] == "etag-2"


def test_set_cache_noop_when_empty():
    con = _con()
    load_headlines.set_feed_cache(con, "markets", None, None)
    assert load_headlines.get_feed_cache(con, "markets") == {}


# --------------------------------------------------------- raw snapshot
def test_save_raw_xml(tmp_path):
    p = load_headlines.save_raw_xml("us-home", b"<rss/>", "2026-01-07T0900", root=str(tmp_path))
    assert p is not None and p.endswith("us-home.xml")
    with open(p, "rb") as f:
        assert f.read() == b"<rss/>"


def test_save_raw_xml_skips_empty(tmp_path):
    assert load_headlines.save_raw_xml("markets", b"", "2026-01-07T0900", root=str(tmp_path)) is None
