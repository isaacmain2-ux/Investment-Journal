"""
Cloud persistence — the small "cloud mode" glue.

On GitHub Actions the warehouse is rebuilt from scratch every run, so the layers
whose sources DON'T keep history would lose theirs. Three staging tables accumulate
and must survive between runs:

    stg_cot            CFTC positioning   (kept so the daily fetch stays incremental)
    stg_headlines      FT news headlines  (RSS only shows the current feed)
    stg_options_skew   options skew       (Yahoo only serves today's chain)

`restore()` seeds these tables from committed CSVs at the start of a run; `dump()`
writes them back out at the end for the workflow to commit. Everything else
(FRED, equities, fundamentals) is re-fetched fresh from its API each run.

CSV is deliberate: it's tiny, text (so git stays clean and diffs are readable), and
the daily commit that updates it also keeps the repository active — which stops
GitHub from auto-disabling the schedule.
"""
from __future__ import annotations

from pathlib import Path

from src.load import load_fred, load_cot, load_headlines, load_skew

STATE_DIR = Path("data/state")

# (table name, ensure_schema function) — the accumulating staging tables
TABLES = [
    ("stg_cot", load_cot.ensure_schema),
    ("stg_headlines", load_headlines.ensure_schema),
    ("stg_options_skew", load_skew.ensure_schema),
]


def restore(con=None) -> dict:
    """Create the accumulating tables and load any committed CSV history into them.
    Returns {table: row_count}. Safe on the first run (no CSVs yet)."""
    own = con is None
    con = con or load_fred.get_connection()
    counts = {}
    try:
        for table, ensure in TABLES:
            ensure(con)
            csv = STATE_DIR / f"{table}.csv"
            if csv.exists():
                con.execute(
                    f"INSERT INTO {table} SELECT * FROM read_csv_auto('{csv.as_posix()}', header=true)")
            counts[table] = con.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
    finally:
        if own:
            con.close()
    return counts


def dump(con=None) -> dict:
    """Export the accumulating tables to CSV for the workflow to commit.
    Returns {table: row_count}."""
    own = con is None
    con = con or load_fred.get_connection()
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    counts = {}
    try:
        for table, ensure in TABLES:
            ensure(con)                      # tolerate a table that never got built this run
            csv = STATE_DIR / f"{table}.csv"
            con.execute(
                f"COPY (SELECT * FROM {table}) TO '{csv.as_posix()}' (HEADER, FORMAT CSV)")
            counts[table] = con.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
    finally:
        if own:
            con.close()
    return counts
