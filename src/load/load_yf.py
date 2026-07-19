"""
Equity storage layer: raw Parquet snapshots and the DuckDB equity tables.
Mirrors load_fred - idempotent delete-then-insert, raw-first landing. Reuses the
same warehouse connection opener so there is one place that opens the database.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from src.load import load_fred

RAW_ROOT = "data/raw/yf"
get_connection = load_fred.get_connection      # reuse the single warehouse opener


def ensure_schema(con) -> None:
    con.execute("""
        CREATE TABLE IF NOT EXISTS dim_security (
            ticker VARCHAR PRIMARY KEY, name VARCHAR, type VARCHAR,
            region VARCHAR, sector VARCHAR, currency VARCHAR, "group" VARCHAR
        )""")
    con.execute("""
        CREATE TABLE IF NOT EXISTS stg_equity_prices (
            ticker VARCHAR, price_date DATE, open DOUBLE, high DOUBLE, low DOUBLE,
            close DOUBLE, adj_close DOUBLE, volume DOUBLE, loaded_at TIMESTAMP
        )""")
    con.execute("""
        CREATE TABLE IF NOT EXISTS equity_status (
            ticker VARCHAR, status VARCHAR, n_obs INTEGER, first_date DATE,
            last_date DATE, error_msg VARCHAR, run_at TIMESTAMP
        )""")


def upsert_dim(con, securities: list[dict]) -> None:
    dim = pd.DataFrame([{
        "ticker": s["ticker"], "name": s["name"], "type": s["type"],
        "region": s["region"], "sector": s.get("sector"),
        "currency": s["currency"], "group": s["group"],
    } for s in securities])
    con.register("dim_sec_df", dim)
    con.execute("DELETE FROM dim_security")
    con.execute('INSERT INTO dim_security '
                'SELECT ticker, name, type, region, sector, currency, "group" FROM dim_sec_df')
    con.unregister("dim_sec_df")


def load_prices(con, ticker: str, df: pd.DataFrame | None) -> int:
    con.execute("DELETE FROM stg_equity_prices WHERE ticker = ?", [ticker])
    if df is None or len(df) == 0:
        return 0
    tmp = df.copy()
    tmp.insert(0, "ticker", ticker)
    tmp["loaded_at"] = datetime.now(timezone.utc)
    con.register("px_df", tmp)
    con.execute("INSERT INTO stg_equity_prices "
                "SELECT ticker, price_date, open, high, low, close, adj_close, volume, loaded_at "
                "FROM px_df")
    con.unregister("px_df")
    return len(tmp)


def record_status(con, ticker, status, n_obs, first_date, last_date, error_msg) -> None:
    con.execute("DELETE FROM equity_status WHERE ticker = ?", [ticker])
    con.execute("INSERT INTO equity_status VALUES (?, ?, ?, ?, ?, ?, ?)",
                [ticker, status, int(n_obs), first_date, last_date, error_msg,
                 datetime.now(timezone.utc)])


def _safe(ticker: str) -> str:
    """Filesystem-safe filename (tickers contain ^, ., etc.)."""
    return re.sub(r"[^A-Za-z0-9._-]", "_", ticker)


def save_raw_parquet(ticker: str, df: pd.DataFrame | None,
                     run_date: str, root: str = RAW_ROOT) -> str | None:
    if df is None or len(df) == 0:
        return None
    out_dir = Path(root) / run_date
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{_safe(ticker)}.parquet"
    df.to_parquet(path, index=False)
    return str(path)
