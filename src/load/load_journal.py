"""
Journal P1 - warehouse storage for the ledger: stg_journal_trades.

Unlike the other loaders this is a *full refresh*, not a delete-then-insert per key:
`data/journal/trades.csv` (owned entirely by src/journal/ledger.py - see that module's
docstring) is small, append-only, and is always read back in full, so the simplest
correct load is "clear the table, insert every row from the current CSV" - the same
approach load_fred.py's `upsert_dim` uses for its (also small, config-driven) dimension
table. trade_id is the natural primary key; a re-run after a new trade was appended
just picks it up, and a re-run with no new trades is a no-op in effect.

All SQL is plain DB-API (execute / executemany / ? placeholders), so the identical
code runs on DuckDB in production and on an in-memory database in tests.
"""
from __future__ import annotations

from datetime import date, datetime, timezone

from src.journal import ledger
from src.load import load_fred

get_connection = load_fred.get_connection

_COLS = ["trade_id", "trade_date", "portfolio", "ticker", "action", "quantity", "price",
         "currency", "fees", "conviction", "timeframe", "catalyst", "thesis", "tags",
         "entered_at"]


def ensure_schema(con) -> None:
    con.execute("""
        CREATE TABLE IF NOT EXISTS stg_journal_trades (
            trade_id    VARCHAR PRIMARY KEY,
            trade_date  DATE,
            portfolio   VARCHAR,
            ticker      VARCHAR,
            action      VARCHAR,
            quantity    DOUBLE,
            price       DOUBLE,
            currency    VARCHAR,
            fees        DOUBLE,
            conviction  VARCHAR,
            timeframe   VARCHAR,
            catalyst    VARCHAR,
            thesis      VARCHAR,
            tags        VARCHAR,
            entered_at  VARCHAR,
            loaded_at   TIMESTAMP
        )""")


def load_trades(con, rows: list[dict]) -> int:
    """Full refresh from the ledger's current rows. Returns the row count loaded.
    Rows missing a trade_id/ticker/action or with a non-positive quantity/price are
    dropped defensively rather than poisoning the warehouse - `ledger.read_trades()`
    should already guarantee well-formed rows since it's the only writer, but this
    loader doesn't assume that."""
    clean = [_normalize(r) for r in (rows or []) if _valid(r)]
    con.execute("DELETE FROM stg_journal_trades")
    if not clean:
        return 0
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    con.executemany(
        f"INSERT INTO stg_journal_trades ({', '.join(_COLS)}, loaded_at) "
        f"VALUES ({', '.join(['?'] * len(_COLS))}, ?)",
        [tuple(r.get(c) for c in _COLS) + (now,) for r in clean])
    return len(clean)


def _normalize(r: dict) -> dict:
    """trade_date arrives from ledger.read_trades() as an ISO string ('2026-08-23') -
    coerce to a real date so it lands in the DATE column as one, not as text."""
    row = dict(r)
    td = row.get("trade_date")
    if isinstance(td, str):
        try:
            row["trade_date"] = date.fromisoformat(td[:10])
        except ValueError:
            row["trade_date"] = None
    return row


def _valid(r: dict) -> bool:
    if not r or not r.get("trade_id") or not r.get("ticker") or not r.get("trade_date"):
        return False
    if r.get("action") not in ledger.VALID_ACTIONS:
        return False
    q, p = r.get("quantity"), r.get("price")
    if q is None or p is None or q <= 0 or p <= 0:
        return False
    return True


def run(con=None, path: str | None = None) -> int:
    """Read the ledger CSV and load it into the warehouse. Standalone entry point
    (also called from run_transform.py before the SQL layer)."""
    own = con is None
    con = con or get_connection()
    try:
        ensure_schema(con)
        rows = ledger.read_trades(path)
        n = load_trades(con, rows)
        print(f"stg_journal_trades: {n} trade(s) loaded from {path or ledger.PATH}")
        return n
    finally:
        if own:
            con.close()


if __name__ == "__main__":
    run()
