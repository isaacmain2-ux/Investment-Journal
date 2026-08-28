"""
Journal P2 - the scan step: read-only ranking of the S&P 500 universe by its
existing composite factor score, so a trade idea always starts from the platform's
own screen rather than a hunch.

Reuses `fct_security_factors` exactly as-is (the same table `build_security_dashboard`'s
"Best overall" tab already sorts) - no new ranking engine, no new weights. The only
new logic here is: take the latest `asof_date`, drop names already held (so it
doesn't keep re-suggesting a position that's already in the book), and print the
top N with enough context (sector, factor breakdown, last close) to make an
informed call.

`top_candidates()` is a pure function of two DataFrames - fully testable without a
database. `run()`/`main()` are the CLI: they open the warehouse, pull the two
tables, and either print the table or (with --log) hand off into add_trade's
interactive confirm flow.

Usage (from the project root):
    python -m src.journal.scan_candidates
    python -m src.journal.scan_candidates --n 10
    python -m src.journal.scan_candidates --log
"""
from __future__ import annotations

import argparse
import sys
from datetime import date, datetime, timedelta

import pandas as pd

DEFAULT_N = 5
STALE_WARN_DAYS = 4        # more than this many calendar days since asof_date -> warn

_FACTOR_COLS = ["value_pct", "momentum_pct", "quality_pct", "growth_pct"]


def top_candidates(factors: pd.DataFrame, n: int = DEFAULT_N,
                    exclude: set | None = None) -> pd.DataFrame:
    """The top-n names by composite_z as of factors' own latest asof_date, excluding
    any ticker already open in the book. Pure; tolerant of None/empty/missing cols."""
    cols = ["ticker", "asof_date", "sector", "composite_z", "composite_pct"] + _FACTOR_COLS
    if factors is None or len(factors) == 0 or "composite_z" not in factors.columns:
        return pd.DataFrame(columns=cols + ["last_close"])
    f = factors.copy()
    f["asof_date"] = pd.to_datetime(f["asof_date"], errors="coerce")
    f = f.dropna(subset=["asof_date", "composite_z"])
    if not len(f):
        return pd.DataFrame(columns=cols + ["last_close"])
    latest = f[f["asof_date"] == f["asof_date"].max()].copy()
    exclude = {t.upper() for t in (exclude or set())}
    if exclude:
        latest = latest[~latest["ticker"].str.upper().isin(exclude)]
    latest = latest.sort_values("composite_z", ascending=False).head(n)
    for c in cols:
        if c not in latest.columns:
            latest[c] = None
    if "last_close" not in latest.columns:
        latest["last_close"] = None
    return latest[cols + ["last_close"]].reset_index(drop=True)


def merge_last_close(candidates: pd.DataFrame, metrics: pd.DataFrame) -> pd.DataFrame:
    """Fold fct_security_metrics.last_close onto the candidates (same ticker+asof_date).
    Pure; a missing metrics frame just leaves last_close as None."""
    if candidates is None or len(candidates) == 0:
        return candidates
    out = candidates.copy()
    if metrics is None or len(metrics) == 0 or "last_close" not in metrics.columns:
        return out
    m = metrics[["ticker", "asof_date", "last_close"]].copy()
    m["asof_date"] = pd.to_datetime(m["asof_date"], errors="coerce")
    out = out.drop(columns=["last_close"]).merge(m, on=["ticker", "asof_date"], how="left")
    return out


def open_tickers(positions: pd.DataFrame | None) -> set:
    """Tickers currently OPEN in fct_positions, for the exclude set. Tolerant of None/empty."""
    if positions is None or len(positions) == 0 or "status" not in positions.columns:
        return set()
    op = positions[positions["status"] == "OPEN"]
    return {str(t).upper() for t in op.get("ticker", [])}


def format_table(candidates: pd.DataFrame) -> str:
    """The terminal table shown by the CLI - one line per candidate."""
    if candidates is None or len(candidates) == 0:
        return "(no candidates - fct_security_factors is empty or has no composite scores yet)"
    lines = []
    for i, (_, r) in enumerate(candidates.iterrows(), 1):
        sector = (r.get("sector") or "—")[:16].ljust(16)
        close = r.get("last_close")
        close_s = f"${close:,.2f}" if close is not None and pd.notna(close) else "—"
        pcts = " ".join(
            f"{label} {r.get(col) * 100:>3.0f}%" if pd.notna(r.get(col)) else f"{label}  — "
            for label, col in [("value", "value_pct"), ("mom", "momentum_pct"),
                               ("qual", "quality_pct"), ("grow", "growth_pct")])
        cz = r.get("composite_z")
        cz_s = f"{cz:+.2f}" if pd.notna(cz) else "—"
        lines.append(f"{i:>3}  {r['ticker']:<6} {sector} composite {cz_s:>6}   {pcts}   {close_s:>10}")
    return "\n".join(lines)


def thesis_snapshot(row: pd.Series | dict, asof_date) -> str:
    """The frozen factor snapshot written into a confirmed trade's thesis field -
    captured at the moment of the scan, per Build Plan #4 (point-in-time)."""
    def pct(col):
        v = row.get(col) if hasattr(row, "get") else row[col]
        return f"{v * 100:.0f}%" if v is not None and pd.notna(v) else "n/a"
    cz = row.get("composite_z") if hasattr(row, "get") else row["composite_z"]
    cpct = row.get("composite_pct") if hasattr(row, "get") else row["composite_pct"]
    cz_s = f"{cz:+.2f}" if cz is not None and pd.notna(cz) else "n/a"
    cpct_s = f" ({cpct * 100:.0f}th pct)" if cpct is not None and pd.notna(cpct) else ""
    d = pd.to_datetime(asof_date).date().isoformat() if asof_date is not None else "?"
    return (f"Top-5 scan {d}: composite {cz_s}{cpct_s} · value {pct('value_pct')} · "
            f"momentum {pct('momentum_pct')} · quality {pct('quality_pct')} · "
            f"growth {pct('growth_pct')}")


# ------------------------------------------------------------------ CLI
def _read(con, sql) -> pd.DataFrame:
    try:
        return con.execute(sql).df()
    except Exception:      # noqa: BLE001 - table may not exist yet
        return pd.DataFrame()


def run(n: int = DEFAULT_N) -> tuple[pd.DataFrame, "date | None"]:
    """Open the warehouse, build the candidate table. Returns (candidates, asof_date)."""
    from src.load import load_fred
    con = load_fred.get_connection()
    try:
        factors = _read(con, "SELECT * FROM fct_security_factors")
        metrics = _read(con, "SELECT ticker, asof_date, last_close FROM fct_security_metrics")
        positions = _read(con, "SELECT ticker, status FROM fct_positions")
        cands = top_candidates(factors, n=n, exclude=open_tickers(positions))
        cands = merge_last_close(cands, metrics)
        asof = None
        if len(cands) and pd.notna(cands["asof_date"].iloc[0]):
            asof = pd.to_datetime(cands["asof_date"].iloc[0]).date()
        return cands, asof
    finally:
        con.close()


def _staleness_note(asof) -> str | None:
    if asof is None:
        return None
    age = (date.today() - asof).days
    if age > STALE_WARN_DAYS:
        return (f"!! fct_security_factors is {age}d old (as of {asof.isoformat()}) - "
                f"run `python -m src.transform.run_transform` first for a current scan.")
    return None


def main() -> None:
    ap = argparse.ArgumentParser(description="Scan the S&P 500 factor screen for top candidates.")
    ap.add_argument("--n", type=int, default=DEFAULT_N, help="how many candidates to show")
    ap.add_argument("--log", action="store_true",
                    help="chain into the interactive confirm/log flow (add_trade.py)")
    args = ap.parse_args()

    cands, asof = run(n=args.n)
    universe_note = "S&P 500 universe" if len(cands) else "S&P 500 universe (no data yet)"
    print(f"Top {args.n}, {universe_note}, as of {asof.isoformat() if asof else 'n/a'} "
          f"(composite_z, sector-neutral=off)\n")
    print(format_table(cands))
    stale = _staleness_note(asof)
    if stale:
        print(f"\n{stale}")

    if args.log:
        from src.journal import add_trade
        add_trade.interactive_log(cands, asof)


if __name__ == "__main__":
    main()
