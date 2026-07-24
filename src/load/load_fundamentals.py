"""
Fundamentals storage: raw Parquet snapshots and the DuckDB fundamentals tables.
Same patterns as the other loaders - idempotent delete-then-insert, raw-first.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from src.load import load_fred

RAW_ROOT = "data/raw/fundamentals"
get_connection = load_fred.get_connection      # one place opens the warehouse


def ensure_schema(con) -> None:
    con.execute("""
        CREATE TABLE IF NOT EXISTS stg_fundamentals (
            ticker         VARCHAR,
            statement      VARCHAR,      -- income | balance | cashflow
            freq           VARCHAR,      -- annual | quarterly
            metric         VARCHAR,      -- Yahoo's line-item label
            period_end     DATE,         -- end of the reporting period
            available_from DATE,         -- period_end + reporting lag (point-in-time)
            value          DOUBLE,
            loaded_at      TIMESTAMP
        )""")
    con.execute("""
        CREATE TABLE IF NOT EXISTS fundamentals_status (
            ticker VARCHAR, status VARCHAR, n_obs INTEGER,
            first_period DATE, last_period DATE, error_msg VARCHAR, run_at TIMESTAMP
        )""")


def load_fundamentals(con, ticker: str, df: pd.DataFrame | None) -> int:
    """Idempotent load: clear this ticker's rows, then insert the new ones."""
    con.execute("DELETE FROM stg_fundamentals WHERE ticker = ?", [ticker])
    if df is None or len(df) == 0:
        return 0
    tmp = df.copy()
    tmp.insert(0, "ticker", ticker)
    tmp["loaded_at"] = datetime.now(timezone.utc)
    con.register("fund_df", tmp)
    con.execute("INSERT INTO stg_fundamentals "
                "SELECT ticker, statement, freq, metric, period_end, available_from, "
                "value, loaded_at FROM fund_df")
    con.unregister("fund_df")
    return len(tmp)


def record_status(con, ticker, status, n_obs, first_period, last_period, error_msg) -> None:
    con.execute("DELETE FROM fundamentals_status WHERE ticker = ?", [ticker])
    con.execute("INSERT INTO fundamentals_status VALUES (?, ?, ?, ?, ?, ?, ?)",
                [ticker, status, int(n_obs), first_period, last_period, error_msg,
                 datetime.now(timezone.utc)])


def _safe(ticker: str) -> str:
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


def ensure_meta_schema(con) -> None:
    con.execute("""
        CREATE TABLE IF NOT EXISTS dim_company_meta (
            ticker             VARCHAR PRIMARY KEY,
            financial_currency VARCHAR,   -- currency the STATEMENTS are reported in
            shares_outstanding DOUBLE,
            market_cap         DOUBLE,
            updated_at         TIMESTAMP
        )""")


def upsert_meta(con, meta: dict) -> int:
    """Idempotent per-ticker replace of company metadata."""
    if not meta:
        return 0
    rows = [{"ticker": tk,
             "financial_currency": v.get("financial_currency"),
             "shares_outstanding": v.get("shares_outstanding"),
             "market_cap": v.get("market_cap"),
             "updated_at": datetime.now(timezone.utc)} for tk, v in meta.items()]
    df = pd.DataFrame(rows)
    con.register("meta_df", df)
    con.execute("DELETE FROM dim_company_meta WHERE ticker IN "
                "(SELECT ticker FROM meta_df)")
    con.execute("INSERT INTO dim_company_meta "
                "SELECT ticker, financial_currency, shares_outstanding, market_cap, "
                "updated_at FROM meta_df")
    con.unregister("meta_df")
    return len(df)
