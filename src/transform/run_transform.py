"""
Transform runner: executes the SQL files in src/transform/sql/ in filename order
against the warehouse, rebuilding the modelled (gold) tables, then prints a short
validation summary.

Usage (from the project root):
    python -m src.transform.run_transform
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

from src.load import load_fred   # reuse the warehouse connection

SQL_DIR = Path("src/transform/sql")


def _statements(sql_text: str):
    """Split a .sql file into individual statements. Line comments (-- to end of
    line) are stripped first, so a semicolon inside a comment can't split a
    statement. Safe for our SQL (no '--' inside string literals)."""
    no_comments = "\n".join(line.split("--", 1)[0] for line in sql_text.splitlines())
    return [s.strip() for s in no_comments.split(";") if s.strip()]


def run(sql_dir: Path = SQL_DIR) -> int:
    files = sorted(Path(sql_dir).glob("*.sql"))
    if not files:
        print(f"No SQL files found in {sql_dir}.")
        return 1

    con = load_fred.get_connection()
    t0 = time.time()
    for f in files:
        print(f"Running {f.name} ...")
        for stmt in _statements(f.read_text(encoding="utf-8")):
            con.execute(stmt)

    # --- validation summary ---
    print(f"\nDone in {time.time() - t0:.1f}s")

    tables = [r[0] for r in con.execute(
        "SELECT table_name FROM information_schema.tables "
        "WHERE table_name LIKE 'fct_%' ORDER BY table_name").fetchall()]
    for t in tables:
        cnt = con.execute(f"SELECT count(*) FROM {t}").fetchone()[0]
        print(f"  {t:<24} {cnt:>10,} rows")

    # reconciliation: fct_series_analytics has exactly one row per staging observation
    n_rows = con.execute("SELECT count(*) FROM fct_series_analytics").fetchone()[0]
    stg_rows = con.execute("SELECT count(*) FROM stg_fred_observations").fetchone()[0]
    reconciled = "MATCH" if n_rows == stg_rows else "MISMATCH"
    print(f"\n  reconciliation (analytics vs staging): {n_rows:,} vs {stg_rows:,} -> {reconciled}")

    con.close()
    return 0 if reconciled == "MATCH" else 1


def main() -> None:
    sys.exit(run())


if __name__ == "__main__":
    main()
