"""
Positioning storage: raw JSON snapshots and the stg_cot staging table.

Like the FRED/price loaders this is idempotent (delete-then-insert per
market+week), so re-running never duplicates and picks up CFTC revisions. The
one addition is point-in-time: COT data is dated each Tuesday but not released
until the following Friday, so every row carries `available_from = report_date +
release_lag_days`, and any point-in-time use joins on that, never report_date.

All SQL is plain DB-API (execute / executemany / fetchall with ? placeholders),
so the identical code runs on DuckDB in production and on an in-memory database
in tests.
"""
from __future__ import annotations

import re
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from src.load import load_fred

RAW_ROOT = "data/raw/cot"
get_connection = load_fred.get_connection

_COLS = ["open_interest", "lev_long", "lev_short", "lev_spread",
         "am_long", "am_short", "dealer_long", "dealer_short"]


def ensure_schema(con) -> None:
    con.execute("""
        CREATE TABLE IF NOT EXISTS stg_cot (
            market_id      VARCHAR,
            market         VARCHAR,
            report_date    DATE,
            available_from DATE,
            open_interest  BIGINT,
            lev_long       BIGINT,
            lev_short      BIGINT,
            lev_spread     BIGINT,
            am_long        BIGINT,
            am_short       BIGINT,
            dealer_long    BIGINT,
            dealer_short   BIGINT,
            loaded_at      TIMESTAMP,
            PRIMARY KEY (market_id, report_date)
        )""")
    con.execute("""
        CREATE TABLE IF NOT EXISTS cot_status (
            market_id VARCHAR, market VARCHAR, status VARCHAR,
            n_rows INTEGER, n_new INTEGER, error_msg VARCHAR, run_at TIMESTAMP
        )""")


def load_cot(con, market_id, rows, lag_days: int = 3) -> tuple[int, int]:
    """Idempotently load one market's weekly rows. Returns (n_seen, n_new)."""
    clean = [r for r in rows if r.get("report_date") is not None]
    clean = _dedupe_by_date(clean)
    if not clean:
        return (0, 0)
    dates = [r["report_date"] for r in clean]
    existing = _existing_dates(con, market_id, dates)
    n_new = sum(1 for d in dates if d not in existing)

    # delete-then-insert for the incoming dates (handles revisions + re-runs)
    _delete_dates(con, market_id, dates)
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    con.executemany(
        "INSERT INTO stg_cot (market_id, market, report_date, available_from, "
        "open_interest, lev_long, lev_short, lev_spread, am_long, am_short, "
        "dealer_long, dealer_short, loaded_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [(market_id, r.get("market"), r["report_date"],
          r["report_date"] + timedelta(days=lag_days),
          *[r.get(c) for c in _COLS], now) for r in clean])
    return (len(clean), n_new)


def _existing_dates(con, market_id, dates) -> set:
    found = set()
    for chunk in _chunks(dates, 500):
        q = ",".join("?" * len(chunk))
        rows = con.execute(
            f"SELECT report_date FROM stg_cot WHERE market_id = ? AND report_date IN ({q})",
            [market_id, *chunk]).fetchall()
        found.update(r[0] for r in rows)
    return found


def _delete_dates(con, market_id, dates) -> None:
    for chunk in _chunks(dates, 500):
        q = ",".join("?" * len(chunk))
        con.execute(f"DELETE FROM stg_cot WHERE market_id = ? AND report_date IN ({q})",
                    [market_id, *chunk])


def _chunks(seq, n):
    for i in range(0, len(seq), n):
        yield seq[i:i + n]


def _dedupe_by_date(rows):
    """Keep one row per report_date - the one with the largest open interest -
    so a batch that somehow carries duplicate weeks can never violate the primary
    key. Belt-and-braces alongside the client's primary-contract selection."""
    best = {}
    for r in rows:
        d = r["report_date"]
        oi = r.get("open_interest") or 0
        cur = best.get(d)
        if cur is None or oi > (cur.get("open_interest") or 0):
            best[d] = r
    return [best[d] for d in sorted(best)]


def get_max_report_date(con, market_id):
    """Latest report_date already loaded for a market (for incremental fetch)."""
    try:
        row = con.execute("SELECT max(report_date) FROM stg_cot WHERE market_id = ?",
                          [market_id]).fetchone()
    except Exception:      # table not created yet
        return None
    v = row[0] if row and row[0] is not None else None
    return _coerce_date(v)


def _coerce_date(v):
    if v is None or isinstance(v, date) and not isinstance(v, datetime):
        return v
    if isinstance(v, datetime):
        return v.date()
    try:
        return date.fromisoformat(str(v)[:10])
    except ValueError:
        return None


def record_status(con, market_id, market, status, n_rows, n_new, error_msg) -> None:
    con.execute("DELETE FROM cot_status WHERE market_id = ?", [market_id])
    con.execute(
        "INSERT INTO cot_status (market_id, market, status, n_rows, n_new, error_msg, run_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        [market_id, market, status, int(n_rows), int(n_new), error_msg,
         datetime.now(timezone.utc).replace(tzinfo=None)])


def save_raw_json(market_id, content, run_stamp, root=RAW_ROOT):
    if not content:
        return None
    out_dir = Path(root) / run_stamp
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{_safe(market_id)}.json"
    mode = "wb" if isinstance(content, (bytes, bytearray)) else "w"
    with open(path, mode) as f:
        f.write(content)
    return str(path)


def _safe(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]", "_", name)
