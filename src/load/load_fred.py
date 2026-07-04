"""
Warehouse loader: writes raw Parquet snapshots and loads observations into the
DuckDB staging tables. Loads are idempotent (delete-then-insert per series), so
re-running never duplicates data.

`duckdb` is imported lazily inside get_connection so this module can be imported
(and unit-tested) even in an environment where DuckDB isn't installed.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

WAREHOUSE = "data/warehouse.duckdb"
RAW_ROOT = "data/raw/fred"


def get_connection(path: str = WAREHOUSE):
    import duckdb  # lazy import
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    return duckdb.connect(path)


def ensure_schema(con) -> None:
    con.execute("""
        CREATE TABLE IF NOT EXISTS dim_fred_series (
            series_id  VARCHAR PRIMARY KEY,
            name       VARCHAR,
            region     VARCHAR,
            category   VARCHAR,
            freq       VARCHAR,
            "transform" VARCHAR,
            verify     BOOLEAN
        )""")
    con.execute("""
        CREATE TABLE IF NOT EXISTS stg_fred_observations (
            series_id  VARCHAR,
            obs_date   DATE,
            value      DOUBLE,
            loaded_at  TIMESTAMP
        )""")
    con.execute("""
        CREATE TABLE IF NOT EXISTS fred_series_status (
            series_id  VARCHAR,
            status     VARCHAR,
            n_obs      INTEGER,
            first_obs  DATE,
            last_obs   DATE,
            error_msg  VARCHAR,
            run_at     TIMESTAMP
        )""")


def upsert_dim(con, series_list: list[dict]) -> None:
    """Refresh the series dimension from the (full) config."""
    dim_df = pd.DataFrame([{
        "series_id": s["id"],
        "name": s["name"],
        "region": s["region"],
        "category": s["category"],
        "freq": s["freq"],
        "transform": s["transform"],
        "verify": bool(s.get("verify", False)),
    } for s in series_list])
    con.register("dim_df", dim_df)
    con.execute("DELETE FROM dim_fred_series")
    con.execute('INSERT INTO dim_fred_series '
                'SELECT series_id, name, region, category, freq, "transform", verify FROM dim_df')
    con.unregister("dim_df")


def load_observations(con, series_id: str, df: pd.DataFrame | None) -> int:
    """Idempotent load: clear this series' rows, then insert the new ones."""
    con.execute("DELETE FROM stg_fred_observations WHERE series_id = ?", [series_id])
    if df is None or len(df) == 0:
        return 0
    tmp = df[["obs_date", "value"]].copy()
    tmp.insert(0, "series_id", series_id)
    tmp["loaded_at"] = datetime.now(timezone.utc)
    con.register("obs_df", tmp)
    con.execute("INSERT INTO stg_fred_observations "
                "SELECT series_id, obs_date, value, loaded_at FROM obs_df")
    con.unregister("obs_df")
    return len(tmp)


def record_status(con, series_id, status, n_obs, first_obs, last_obs, error_msg) -> None:
    con.execute("DELETE FROM fred_series_status WHERE series_id = ?", [series_id])
    con.execute(
        "INSERT INTO fred_series_status VALUES (?, ?, ?, ?, ?, ?, ?)",
        [series_id, status, int(n_obs), first_obs, last_obs, error_msg,
         datetime.now(timezone.utc)],
    )


def save_raw_parquet(series_id: str, df: pd.DataFrame | None,
                     run_date: str, root: str = RAW_ROOT) -> str | None:
    """Write the immutable raw snapshot for this series/run. Skips empty frames."""
    if df is None or len(df) == 0:
        return None
    out_dir = Path(root) / run_date
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{series_id}.parquet"
    df.to_parquet(path, index=False)
    return str(path)
