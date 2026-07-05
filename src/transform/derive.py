"""
Derived cross-series objects: the regime tag and the daily market snapshot.

These need cross-series alignment (forward-filling lower-frequency reads onto the
daily calendar), which pandas does cleanly, so this is the one transform step
done in Python rather than SQL. The core logic lives in `compute`, a pure
function of the analytics DataFrame, so it is fully unit-testable without a
database. `run` is the thin wrapper that reads from and writes to DuckDB.

Regime axes (each a mean of the contributing series' primary_zscore):
  * growth     — production/sales/jobs/sentiment (unemployment & claims inverted)
  * inflation  — core inflation rates + market breakevens
  * conditions — financial conditions (NFCI; positive = tight)
A positive axis means "above its own historical norm". Everything is
forward-filled only (past data), so there is no look-ahead.
"""
from __future__ import annotations

import pandas as pd

# --- series that feed each regime axis (by their primary_zscore) ---
GROWTH_POS = ["INDPRO", "RSAFS", "PAYEMS", "UMCSENT", "HOUST", "GDPC1"]
GROWTH_NEG = ["UNRATE", "ICSA"]                 # higher = worse growth -> inverted
INFLATION = ["CPIAUCSL", "CPILFESL", "PCEPILFE", "T10YIE", "T5YIFR"]
CONDITIONS = ["NFCI"]                           # positive = tighter conditions

# --- series shown in the daily snapshot (by their level value) ---
SNAPSHOT_SERIES = ["DGS2", "DGS10", "BAMLC0A0CM", "BAMLH0A0HYM2",
                   "VIXCLS", "DTWEXBGS", "DCOILWTICO"]


def _state(x, pos_label, neg_label):
    if pd.isna(x):
        return None
    return pos_label if x > 0 else neg_label


def compute(analytics_df: pd.DataFrame):
    """Given the fct_series_analytics rows (long), return (regime_df, snapshot_df),
    each one row per date."""
    # wide, forward-filled panels of z-scores and levels
    zwide = (analytics_df.pivot_table(index="obs_date", columns="series_id",
                                      values="primary_zscore", aggfunc="last")
             .sort_index())
    vwide = (analytics_df.pivot_table(index="obs_date", columns="series_id",
                                      values="value", aggfunc="last")
             .sort_index())

    z_needed = GROWTH_POS + GROWTH_NEG + INFLATION + CONDITIONS
    zwide = zwide.reindex(columns=sorted(set(list(zwide.columns) + z_needed))).ffill()
    vwide = vwide.reindex(columns=sorted(set(list(vwide.columns) + SNAPSHOT_SERIES))).ffill()

    # --- regime axes ---
    growth = pd.concat([zwide[GROWTH_POS], -zwide[GROWTH_NEG]], axis=1).mean(axis=1, skipna=True)
    inflation = zwide[INFLATION].mean(axis=1, skipna=True)
    conditions = zwide[CONDITIONS].mean(axis=1, skipna=True)

    regime = pd.DataFrame({
        "date": growth.index,
        "growth_axis": growth.values,
        "inflation_axis": inflation.values,
        "conditions": conditions.values,
    })
    regime["growth_state"] = regime["growth_axis"].map(
        lambda x: _state(x, "Above-trend", "Below-trend"))
    regime["inflation_state"] = regime["inflation_axis"].map(
        lambda x: _state(x, "Above-trend", "Below-trend"))
    regime["conditions_state"] = regime["conditions"].map(
        lambda x: _state(x, "Tight", "Loose"))

    def _label(r):
        if None in (r["growth_state"], r["inflation_state"], r["conditions_state"]):
            return None
        return (f"Growth {r['growth_state']} \u00b7 Inflation {r['inflation_state']} "
                f"\u00b7 {r['conditions_state']}")
    regime["regime_label"] = regime.apply(_label, axis=1)

    # --- daily snapshot ---
    snap = pd.DataFrame({"date": vwide.index})
    snap["dgs2"] = vwide["DGS2"].values
    snap["dgs10"] = vwide["DGS10"].values
    snap["slope_2s10s"] = snap["dgs10"] - snap["dgs2"]
    snap["ig_oas"] = vwide["BAMLC0A0CM"].values
    snap["hy_oas"] = vwide["BAMLH0A0HYM2"].values
    snap["ig_hy_spread"] = snap["hy_oas"] - snap["ig_oas"]
    snap["vix"] = vwide["VIXCLS"].values
    snap["usd_broad"] = vwide["DTWEXBGS"].values
    snap["oil_wti"] = vwide["DCOILWTICO"].values
    snap = snap.merge(
        regime[["date", "growth_axis", "inflation_axis", "conditions", "regime_label"]],
        on="date", how="left")

    # store dates as plain dates (DuckDB DATE)
    regime["date"] = pd.to_datetime(regime["date"]).dt.date
    snap["date"] = pd.to_datetime(snap["date"]).dt.date
    return regime, snap


def run(con) -> tuple[int, int]:
    """Read analytics, compute the two tables, write them back to the warehouse."""
    analytics = con.execute(
        "SELECT series_id, obs_date, value, primary_value, primary_zscore "
        "FROM fct_series_analytics").df()
    regime, snap = compute(analytics)

    con.register("regime_df", regime)
    con.execute("DROP TABLE IF EXISTS fct_regime")
    con.execute("CREATE TABLE fct_regime AS SELECT * FROM regime_df")
    con.unregister("regime_df")

    con.register("snap_df", snap)
    con.execute("DROP TABLE IF EXISTS fct_daily_snapshot")
    con.execute("CREATE TABLE fct_daily_snapshot AS SELECT * FROM snap_df")
    con.unregister("snap_df")

    return len(regime), len(snap)


def latest_regime_label(con) -> str | None:
    row = con.execute(
        "SELECT regime_label FROM fct_regime WHERE regime_label IS NOT NULL "
        "ORDER BY date DESC LIMIT 1").fetchone()
    return row[0] if row else None
