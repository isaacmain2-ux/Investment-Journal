"""
Options-skew storage: the snapshot-accumulating stg_options_skew table.

Unlike the other layers there is no history to backfill - Yahoo serves only the
current chain - so each run captures one row per ticker and the table accumulates
over time. Loading is idempotent per (ticker_id, capture_date): re-running on the
same day replaces that day's capture rather than duplicating it.

All SQL is plain DB-API (execute / executemany / ? placeholders), so the identical
code runs on DuckDB in production and on an in-memory database in tests.
"""
from __future__ import annotations

from datetime import date, datetime, timezone

from src.load import load_fred

get_connection = load_fred.get_connection

_COLS = ["ticker", "expiry", "dte", "spot", "atm_iv", "put_iv", "call_iv",
         "put_skew", "risk_reversal"]


def ensure_schema(con) -> None:
    con.execute("""
        CREATE TABLE IF NOT EXISTS stg_options_skew (
            ticker_id     VARCHAR,
            ticker        VARCHAR,
            capture_date  DATE,
            expiry        VARCHAR,
            dte           INTEGER,
            spot          DOUBLE,
            atm_iv        DOUBLE,
            put_iv        DOUBLE,
            call_iv       DOUBLE,
            put_skew      DOUBLE,
            risk_reversal DOUBLE,
            loaded_at     TIMESTAMP,
            PRIMARY KEY (ticker_id, capture_date)
        )""")
    con.execute("""
        CREATE TABLE IF NOT EXISTS skew_status (
            ticker_id VARCHAR, label VARCHAR, status VARCHAR,
            put_skew DOUBLE, error_msg VARCHAR, run_at TIMESTAMP
        )""")


def load_skew(con, rows) -> tuple[int, int]:
    """Idempotently load skew snapshot rows (one per ticker). Returns (n_seen, n_new)."""
    clean = _dedupe([r for r in rows if r and r.get("ticker_id") and r.get("capture_date")])
    if not clean:
        return (0, 0)
    n_new = sum(1 for r in clean if not _exists(con, r["ticker_id"], r["capture_date"]))
    for r in clean:
        _delete(con, r["ticker_id"], r["capture_date"])
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    con.executemany(
        "INSERT INTO stg_options_skew (ticker_id, ticker, capture_date, expiry, dte, spot, "
        "atm_iv, put_iv, call_iv, put_skew, risk_reversal, loaded_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [(r["ticker_id"], r.get("ticker"), r["capture_date"], *[r.get(c) for c in
          ["expiry", "dte", "spot", "atm_iv", "put_iv", "call_iv", "put_skew", "risk_reversal"]],
          now) for r in clean])
    return (len(clean), n_new)


def _dedupe(rows):
    """One row per (ticker_id, capture_date); last wins."""
    best = {}
    for r in rows:
        best[(r["ticker_id"], r["capture_date"])] = r
    return list(best.values())


def _exists(con, ticker_id, capture_date) -> bool:
    row = con.execute("SELECT 1 FROM stg_options_skew WHERE ticker_id = ? AND capture_date = ?",
                      [ticker_id, capture_date]).fetchone()
    return row is not None


def _delete(con, ticker_id, capture_date) -> None:
    con.execute("DELETE FROM stg_options_skew WHERE ticker_id = ? AND capture_date = ?",
                [ticker_id, capture_date])


def get_max_capture_date(con, ticker_id):
    try:
        row = con.execute("SELECT max(capture_date) FROM stg_options_skew WHERE ticker_id = ?",
                          [ticker_id]).fetchone()
    except Exception:
        return None
    return _coerce_date(row[0]) if row and row[0] is not None else None


def _coerce_date(v):
    if v is None or (isinstance(v, date) and not isinstance(v, datetime)):
        return v
    if isinstance(v, datetime):
        return v.date()
    try:
        return date.fromisoformat(str(v)[:10])
    except ValueError:
        return None


def record_status(con, ticker_id, label, status, put_skew, error_msg) -> None:
    con.execute("DELETE FROM skew_status WHERE ticker_id = ?", [ticker_id])
    con.execute(
        "INSERT INTO skew_status (ticker_id, label, status, put_skew, error_msg, run_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        [ticker_id, label, status, put_skew, error_msg,
         datetime.now(timezone.utc).replace(tzinfo=None)])
