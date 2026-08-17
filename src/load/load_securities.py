"""
Security-level storage: the universe dimension and the two accumulating staging
tables it feeds.

    dim_security               ticker -> name/sector/industry/cik      (reference)
    stg_security_prices        EOD OHLCV per (ticker, date)            (accumulating)
    stg_security_fundamentals  XBRL facts, long/tidy, point-in-time    (accumulating)

All SQL is plain DB-API (execute / executemany / ? placeholders, dialect-neutral), so
the identical code runs on DuckDB in production and on SQLite in tests. Loads are
idempotent so a re-run never duplicates; fundamentals keep the latest-filed value per
period (handling restatements).
"""
from __future__ import annotations

from datetime import date, datetime, timezone

WAREHOUSE = "data/warehouse.duckdb"


def get_connection(path: str = WAREHOUSE):
    import duckdb                              # lazy import
    return duckdb.connect(path)


def _now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


# expected columns per table - a missing one is added by ALTER (handles schema drift
# from an older warehouse without dropping accumulated data)
_SCHEMA = {
    "dim_security": [("ticker", "VARCHAR"), ("name", "VARCHAR"), ("sector", "VARCHAR"),
                     ("industry", "VARCHAR"), ("cik", "VARCHAR"), ("updated_at", "TIMESTAMP")],
    "stg_security_prices": [("ticker", "VARCHAR"), ("date", "DATE"), ("open", "DOUBLE"),
                            ("high", "DOUBLE"), ("low", "DOUBLE"), ("close", "DOUBLE"),
                            ("volume", "DOUBLE"), ("loaded_at", "TIMESTAMP")],
    "stg_security_fundamentals": [("ticker", "VARCHAR"), ("cik", "VARCHAR"), ("metric", "VARCHAR"),
                                  ("xbrl_tag", "VARCHAR"), ("period_end", "DATE"),
                                  ("fiscal_year", "INTEGER"), ("fiscal_period", "VARCHAR"),
                                  ("form", "VARCHAR"), ("filed_date", "DATE"), ("unit", "VARCHAR"),
                                  ("value", "DOUBLE"), ("loaded_at", "TIMESTAMP")],
}


def _ensure_column(con, table, col, coltype) -> None:
    try:
        con.execute(f"SELECT {col} FROM {table} LIMIT 0")     # column already present?
    except Exception:
        try:
            con.execute(f"ALTER TABLE {table} ADD COLUMN {col} {coltype}")
        except Exception:
            pass


def _migrate(con) -> None:
    for table, cols in _SCHEMA.items():
        for col, coltype in cols:
            _ensure_column(con, table, col, coltype)


def ensure_schema(con) -> None:
    con.execute("""
        CREATE TABLE IF NOT EXISTS dim_security (
            ticker VARCHAR PRIMARY KEY,
            name VARCHAR, sector VARCHAR, industry VARCHAR,
            cik VARCHAR, updated_at TIMESTAMP
        )""")
    con.execute("""
        CREATE TABLE IF NOT EXISTS stg_security_prices (
            ticker VARCHAR, date DATE,
            open DOUBLE, high DOUBLE, low DOUBLE, close DOUBLE, volume DOUBLE,
            loaded_at TIMESTAMP,
            PRIMARY KEY (ticker, date)
        )""")
    con.execute("""
        CREATE TABLE IF NOT EXISTS stg_security_fundamentals (
            ticker VARCHAR, cik VARCHAR, metric VARCHAR, xbrl_tag VARCHAR,
            period_end DATE, fiscal_year INTEGER, fiscal_period VARCHAR,
            form VARCHAR, filed_date DATE, unit VARCHAR, value DOUBLE,
            loaded_at TIMESTAMP,
            PRIMARY KEY (ticker, metric, period_end, fiscal_period)
        )""")
    _migrate(con)


# --------------------------------------------------------------- dim_security
def upsert_securities(con, rows) -> int:
    """Replace the universe rows (one per ticker). Returns count loaded."""
    clean = [r for r in rows if r and r.get("ticker")]
    if not clean:
        return 0
    now = _now()
    for r in clean:
        con.execute("DELETE FROM dim_security WHERE ticker = ?", [r["ticker"]])
    con.executemany(
        "INSERT INTO dim_security (ticker, name, sector, industry, cik, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        [(r["ticker"], r.get("name"), r.get("sector"), r.get("industry"),
          _cik(r.get("cik")), now) for r in clean])
    return len(clean)


def _cik(v):
    return str(v).zfill(10) if v not in (None, "") else None


# --------------------------------------------------------------- prices
def load_prices(con, rows) -> tuple[int, int]:
    """Idempotent per (ticker, date). Returns (n_seen, n_new)."""
    clean = _dedupe(rows, ("ticker", "date"))
    if not clean:
        return (0, 0)
    n_new = sum(1 for r in clean if not _exists(con, "stg_security_prices",
                ["ticker", "date"], [r["ticker"], r["date"]]))
    for r in clean:
        con.execute("DELETE FROM stg_security_prices WHERE ticker = ? AND date = ?",
                    [r["ticker"], r["date"]])
    now = _now()
    con.executemany(
        "INSERT INTO stg_security_prices (ticker, date, open, high, low, close, volume, loaded_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        [(r["ticker"], r["date"], r.get("open"), r.get("high"), r.get("low"),
          r.get("close"), r.get("volume"), now) for r in clean])
    return (len(clean), n_new)


# --------------------------------------------------------------- fundamentals
def load_fundamentals(con, rows) -> tuple[int, int]:
    """Idempotent per (ticker, metric, period_end, fiscal_period); keeps the
    latest-filed value (restatements win). Returns (n_seen, n_new)."""
    best = {}
    for r in rows:
        if not r or r.get("value") is None or not r.get("period_end"):
            continue
        fp = r.get("fiscal_period") or ""
        key = (r["ticker"], r["metric"], r["period_end"], fp)
        prev = best.get(key)
        if prev is None or _later(r.get("filed_date"), prev.get("filed_date")):
            best[key] = r
    clean = list(best.values())
    if not clean:
        return (0, 0)
    n_new = sum(1 for r in clean if not _exists(con, "stg_security_fundamentals",
                ["ticker", "metric", "period_end", "fiscal_period"],
                [r["ticker"], r["metric"], r["period_end"], r.get("fiscal_period") or ""]))
    for r in clean:
        con.execute("DELETE FROM stg_security_fundamentals WHERE ticker = ? AND metric = ? "
                    "AND period_end = ? AND fiscal_period = ?",
                    [r["ticker"], r["metric"], r["period_end"], r.get("fiscal_period") or ""])
    now = _now()
    con.executemany(
        "INSERT INTO stg_security_fundamentals (ticker, cik, metric, xbrl_tag, period_end, "
        "fiscal_year, fiscal_period, form, filed_date, unit, value, loaded_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [(r["ticker"], _cik(r.get("cik")), r["metric"], r.get("xbrl_tag"), r["period_end"],
          r.get("fiscal_year"), r.get("fiscal_period") or "", r.get("form"), r.get("filed_date"),
          r.get("unit"), r.get("value"), now) for r in clean])
    return (len(clean), n_new)


# --------------------------------------------------------------- helpers
def _dedupe(rows, keys):
    best = {}
    for r in rows:
        if not r or any(r.get(k) is None for k in keys):
            continue
        best[tuple(r[k] for k in keys)] = r
    return list(best.values())


def _exists(con, table, keys, vals) -> bool:
    where = " AND ".join(f"{k} = ?" for k in keys)
    return con.execute(f"SELECT 1 FROM {table} WHERE {where}", vals).fetchone() is not None


def _later(a, b) -> bool:
    if a is None:
        return False
    if b is None:
        return True
    return a >= b