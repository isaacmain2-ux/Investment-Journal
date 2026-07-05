"""
Transform runner: executes the SQL files in src/transform/sql/ in filename order,
then builds the Python-derived tables (regime + daily snapshot), and writes a
markdown run-report plus a short console summary.

Usage (from the project root):
    python -m src.transform.run_transform
"""
from __future__ import annotations

import sys
import time
from datetime import date
from pathlib import Path

from src.common import reporting
from src.load import load_fred          # reuse the warehouse connection
from src.transform import derive

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

    print("Building regime + daily snapshot ...")
    n_regime, n_snap = derive.run(con)

    # --- validation summary ---
    tables = [r[0] for r in con.execute(
        "SELECT table_name FROM information_schema.tables "
        "WHERE table_name LIKE 'fct_%' ORDER BY table_name").fetchall()]
    counts = {t: con.execute(f"SELECT count(*) FROM {t}").fetchone()[0] for t in tables}

    n_rows = counts.get("fct_series_analytics", 0)
    stg_rows = con.execute("SELECT count(*) FROM stg_fred_observations").fetchone()[0]
    reconciled = (n_rows == stg_rows)
    regime_label = derive.latest_regime_label(con)

    run_date = date.today().isoformat()
    md = reporting.build_transform_report(counts, regime_label, run_date, reconciled)
    report_path = reporting.write_report(md, f"reports/transform_{run_date}.md")

    print(f"\nDone in {time.time() - t0:.1f}s  ->  report: {report_path}")
    for t in sorted(counts):
        print(f"  {t:<24} {counts[t]:>10,} rows")
    print(f"\n  reconciliation (analytics vs staging): "
          f"{n_rows:,} vs {stg_rows:,} -> {'MATCH' if reconciled else 'MISMATCH'}")
    print(f"  current regime: {regime_label or 'n/a'}")

    con.close()
    return 0 if reconciled else 1


def main() -> None:
    sys.exit(run())


if __name__ == "__main__":
    main()
