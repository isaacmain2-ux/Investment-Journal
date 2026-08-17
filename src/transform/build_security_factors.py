"""
P3 - fct_security_factors: the cross-sectional ranking engine.

This is the piece that makes it stock *selection*. Each raw metric from
fct_security_metrics is turned into a rank *across the universe*:

  1. winsorise (clip to the 1st/99th percentile) so one outlier can't dominate,
  2. z-score across all names that day (optionally *within sector* - sector-neutral),
  3. orient it so higher = better (cheap, strong, high-quality, growing),
  4. average the metrics of each factor into Value / Momentum / Quality / Growth,
  5. standardise those and blend into a weighted composite.

The result is one row per (ticker, asof_date) carrying each factor's z-score and
percentile plus the composite - which the screens (cheapest-EPS, momentum leaders,
value+quality, most over/under-valued) simply sort and filter.

Because it consumes the point-in-time metrics, the same engine ranks today's universe
now and any historical date for a backtest.
"""
from __future__ import annotations

from datetime import date

import pandas as pd

from src.load import load_securities

get_connection = load_securities.get_connection

# factor -> [(metric, direction)]  (+1 = higher is better, -1 = lower is better)
FACTOR_METRICS = {
    "value":    [("earnings_yield", +1), ("fcf_yield", +1), ("pb", -1), ("ps", -1)],
    "momentum": [("ret_12_1m", +1), ("ret_6m", +1), ("dist_52w_high", +1)],
    "quality":  [("roe", +1), ("gross_margin", +1), ("op_margin", +1),
                 ("net_margin", +1), ("debt_to_equity", -1)],
    "growth":   [("rev_growth_yoy", +1), ("eps_growth_yoy", +1)],
}
DEFAULT_WEIGHTS = {"value": 0.25, "momentum": 0.25, "quality": 0.25, "growth": 0.25}

_COLS = ["ticker", "asof_date", "sector",
         "value_z", "momentum_z", "quality_z", "growth_z",
         "value_pct", "momentum_pct", "quality_pct", "growth_pct",
         "composite_z", "composite_pct"]


def ensure_schema(con) -> None:
    con.execute("""
        CREATE TABLE IF NOT EXISTS fct_security_factors (
            ticker VARCHAR, asof_date DATE, sector VARCHAR,
            value_z DOUBLE, momentum_z DOUBLE, quality_z DOUBLE, growth_z DOUBLE,
            value_pct DOUBLE, momentum_pct DOUBLE, quality_pct DOUBLE, growth_pct DOUBLE,
            composite_z DOUBLE, composite_pct DOUBLE, built_at TIMESTAMP,
            PRIMARY KEY (ticker, asof_date)
        )""")


# ------------------------------------------------------------------ stats
def _winsor(s: pd.Series, lo=0.01, hi=0.99) -> pd.Series:
    s = pd.to_numeric(s, errors="coerce")
    if s.notna().sum() < 3:
        return s
    return s.clip(s.quantile(lo), s.quantile(hi))


def _z(s: pd.Series) -> pd.Series:
    s = pd.to_numeric(s, errors="coerce")
    sd = s.std(ddof=0)
    if not sd or pd.isna(sd) or sd == 0:
        return s * 0.0
    return (s - s.mean()) / sd


def _cross_z(df: pd.DataFrame, metric: str, sector_neutral: bool) -> pd.Series:
    """Winsorised z-score of one metric, across the universe or within sector."""
    if metric not in df.columns:
        return pd.Series([float("nan")] * len(df), index=df.index)
    if sector_neutral and "sector" in df.columns:
        return df.groupby("sector")[metric].transform(lambda x: _z(_winsor(x)))
    return _z(_winsor(df[metric]))


# ------------------------------------------------------------------ engine
def compute_factors(metrics: pd.DataFrame, sector_neutral=False, weights=None) -> pd.DataFrame:
    """The cross-sectional ranking. `metrics` is fct_security_metrics for one date."""
    weights = weights or DEFAULT_WEIGHTS
    df = metrics.reset_index(drop=True)
    out = pd.DataFrame({"ticker": df["ticker"], "asof_date": df.get("asof_date"),
                        "sector": df.get("sector")})

    comp_num = pd.Series(0.0, index=df.index)
    comp_den = pd.Series(0.0, index=df.index)
    for factor, specs in FACTOR_METRICS.items():
        signed = []
        for metric, direction in specs:
            signed.append(_cross_z(df, metric, sector_neutral) * direction)
        raw = pd.concat(signed, axis=1).mean(axis=1, skipna=True) if signed \
            else pd.Series([float("nan")] * len(df), index=df.index)
        fz = _z(raw)                                    # standardise the factor score
        fz = fz.where(raw.notna())                      # keep NaN where the factor was absent
        out[f"{factor}_z"] = fz
        out[f"{factor}_pct"] = fz.rank(pct=True)
        w = weights.get(factor, 0.0)
        comp_num = comp_num.add(fz.fillna(0.0) * w, fill_value=0.0)
        comp_den = comp_den.add(fz.notna().astype(float) * w, fill_value=0.0)

    out["composite_z"] = comp_num / comp_den.replace(0.0, float("nan"))
    out["composite_pct"] = out["composite_z"].rank(pct=True)
    return out


# ------------------------------------------------------------------ run
def _read(con, sql) -> pd.DataFrame:
    cur = con.execute(sql)
    return pd.DataFrame(cur.fetchall(), columns=[d[0] for d in cur.description])


def run(con=None, asof: date | None = None, sector_neutral=False, weights=None) -> int:
    own = con is None
    con = con or get_connection()
    try:
        ensure_schema(con)
        metrics = _read(con, "SELECT * FROM fct_security_metrics")
        if len(metrics) == 0:
            print("No fct_security_metrics - run build_security_metrics first.")
            return 1
        if asof is None:
            asof = max(metrics["asof_date"])
        metrics = metrics[metrics["asof_date"] == asof]
        factors = compute_factors(metrics, sector_neutral=sector_neutral, weights=weights)

        con.execute("DELETE FROM fct_security_factors WHERE asof_date = ?", [asof])
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        con.executemany(
            f"INSERT INTO fct_security_factors ({', '.join(_COLS)}, built_at) "
            f"VALUES ({', '.join(['?'] * len(_COLS))}, ?)",
            [tuple(_val(r.get(c)) for c in _COLS) + (now,) for _, r in factors.iterrows()])
        scored = factors["composite_z"].notna().sum()
        mode = "sector-neutral" if sector_neutral else "whole-universe"
        print(f"fct_security_factors: {len(factors)} names ranked ({mode}) as of {asof}; "
              f"{scored} with a composite score")
        return 0
    finally:
        if own:
            con.close()


def _val(x):
    """None/NaN -> None for the DB driver."""
    if x is None:
        return None
    try:
        if isinstance(x, float) and pd.isna(x):
            return None
    except (TypeError, ValueError):
        pass
    return x


def main():
    import argparse
    import sys
    ap = argparse.ArgumentParser(description="Rank the universe into factor scores.")
    ap.add_argument("--sector-neutral", action="store_true", help="rank within sector")
    args = ap.parse_args()
    sys.exit(run(sector_neutral=args.sector_neutral))


if __name__ == "__main__":
    main()
