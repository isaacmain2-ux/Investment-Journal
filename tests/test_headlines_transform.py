"""Test for 09_headlines.sql - runs the real SQL in in-memory DuckDB and checks
de-duplication (keeping the earliest sighting), HTML stripping, the derived
published_date, and the feed section/region join. Skips if duckdb absent."""
from datetime import date, datetime
from pathlib import Path

import pytest

duckdb = pytest.importorskip("duckdb")

SQL = Path("src/transform/sql/09_headlines.sql").read_text(encoding="utf-8")


def _statements(text):
    no_comments = "\n".join(line.split("--", 1)[0] for line in text.splitlines())
    return [s.strip() for s in no_comments.split(";") if s.strip()]


def _con():
    con = duckdb.connect(":memory:")
    # minimal input tables (no PK, so we can insert a duplicate to test de-dupe)
    con.execute("""CREATE TABLE stg_headlines
                   (item_id VARCHAR, title VARCHAR, summary VARCHAR, link VARCHAR,
                    published_at TIMESTAMP, first_feed VARCHAR, first_seen_at TIMESTAMP)""")
    con.execute("""CREATE TABLE dim_news_feed
                   (feed VARCHAR, feed_group VARCHAR, region VARCHAR)""")
    con.execute("INSERT INTO dim_news_feed VALUES ('markets','core','global'),('home','core','global')")

    # s-1 appears TWICE (different first_seen_at & title) -> must collapse to the earliest
    con.execute("INSERT INTO stg_headlines VALUES "
                "('s-1','First',  '<p>Markets <b>rose</b></p>','https://ft/1',"
                " TIMESTAMP '2026-01-07 08:30:00','markets', TIMESTAMP '2026-01-07 09:00:00')")
    con.execute("INSERT INTO stg_headlines VALUES "
                "('s-1','Second', '<p>ignored</p>','https://ft/1',"
                " TIMESTAMP '2026-01-07 08:30:00','markets', TIMESTAMP '2026-01-07 10:00:00')")
    # s-2: null summary, null published_at
    con.execute("INSERT INTO stg_headlines VALUES "
                "('s-2','No date', NULL,'https://ft/2', NULL,'home', TIMESTAMP '2026-01-07 09:05:00')")
    # s-3: feed not in dim_news_feed -> region/section should be NULL (LEFT JOIN)
    con.execute("INSERT INTO stg_headlines VALUES "
                "('s-3','Orphan','plain text','https://ft/3',"
                " TIMESTAMP '2026-01-06 12:00:00','mystery', TIMESTAMP '2026-01-06 13:00:00')")
    return con


def _build(con):
    for stmt in _statements(SQL):
        con.execute(stmt)


def test_row_count_after_dedupe():
    con = _con(); _build(con)
    assert con.execute("SELECT count(*) FROM fct_headlines").fetchone()[0] == 3   # s-1 collapsed


def test_dedupe_keeps_earliest_sighting():
    con = _con(); _build(con)
    title = con.execute("SELECT title FROM fct_headlines WHERE item_id='s-1'").fetchone()[0]
    assert title == "First"                        # the 09:00 row, not the 10:00 one


def test_html_stripped():
    con = _con(); _build(con)
    summary = con.execute("SELECT summary FROM fct_headlines WHERE item_id='s-1'").fetchone()[0]
    assert summary == "Markets rose"               # tags removed, text preserved


def test_published_date_derived():
    con = _con(); _build(con)
    d = con.execute("SELECT published_date FROM fct_headlines WHERE item_id='s-1'").fetchone()[0]
    assert d == date(2026, 1, 7)


def test_null_published_and_summary():
    con = _con(); _build(con)
    row = con.execute("SELECT published_date, summary FROM fct_headlines "
                      "WHERE item_id='s-2'").fetchone()
    assert row == (None, None)


def test_section_and_region_joined():
    con = _con(); _build(con)
    section, region = con.execute(
        "SELECT section, region FROM fct_headlines WHERE item_id='s-1'").fetchone()
    assert (section, region) == ("core", "global")


def test_unknown_feed_gets_null_region():
    con = _con(); _build(con)
    section, region = con.execute(
        "SELECT section, region FROM fct_headlines WHERE item_id='s-3'").fetchone()
    assert section is None and region is None       # LEFT JOIN, feed not in dim


def test_link_and_published_at_preserved():
    con = _con(); _build(con)
    link, pub = con.execute(
        "SELECT link, published_at FROM fct_headlines WHERE item_id='s-1'").fetchone()
    assert link == "https://ft/1"
    assert pub == datetime(2026, 1, 7, 8, 30)
