"""
Derived cross-series objects: the regime tag and the daily market snapshot.

These need cross-series alignment (forward-filling lower-frequency reads onto the
daily calendar), which pandas does cleanly, so this is the one transform step
done in Python rather than SQL. The core logic lives in pure functions
(`compute`, `equity_summary`), so it is fully unit-testable without a database.

Regime axes (each a mean of the contributing series' primary_zscore):
  * growth     - production/sales/jobs/sentiment (unemployment & claims inverted)
  * inflation  - core inflation rates + market breakevens
  * conditions - financial conditions (NFCI; positive = tight)
A positive axis means "above its own historical norm". Everything is
forward-filled only (past data), so there is no look-ahead.

The snapshot then folds in the EQUITY picture (index moves, sector leadership,
the top factor-screen names) so one row carries both the macro and market view.
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

# --- equity tickers surfaced in the snapshot ---
SNAPSHOT_INDICES = {"^GSPC": "spx", "^FTSE": "ftse", "^STOXX50E": "estoxx"}

# axis magnitude below which a reading is treated as "at trend" rather than
# above/below - avoids over-reading a near-zero axis as a directional call.
NEUTRAL_BAND = 0.25

# how many names/sectors to list in the snapshot's summary strings
TOP_N = 3


def _state(x, pos_label, neg_label, mid_label="Neutral"):
    if pd.isna(x):
        return None
    if x > NEUTRAL_BAND:
        return pos_label
    if x < -NEUTRAL_BAND:
        return neg_label
    return mid_label


def compute(analytics_df: pd.DataFrame):
    """Given the fct_series_analytics rows (long), return (regime_df, snapshot_df),
    each one row per date. Macro only - equity fields are merged in by `run`."""
    zwide = (analytics_df.pivot_table(index="obs_date", columns="series_id",
                                      values="primary_zscore", aggfunc="last")
             .sort_index())
    vwide = (analytics_df.pivot_table(index="obs_date", columns="series_id",
                                      values="value", aggfunc="last")
             .sort_index())

    z_needed = GROWTH_POS + GROWTH_NEG + INFLATION + CONDITIONS
    zwide = zwide.reindex(columns=sorted(set(list(zwide.columns) + z_needed))).ffill()
    vwide = vwide.reindex(columns=sorted(set(list(vwide.columns) + SNAPSHOT_SERIES))).ffill()

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
                f"\u00b7 Conditions {r['conditions_state']}")
    regime["regime_label"] = regime.apply(_label, axis=1)

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

    regime["date"] = pd.to_datetime(regime["date"]).dt.date
    snap["date"] = pd.to_datetime(snap["date"]).dt.date
    return regime, snap


def _top_names(df, score_col, n=TOP_N, ascending=False):
    """Comma-joined ticker list of the n best (or worst) rows by `score_col`."""
    d = df.dropna(subset=[score_col]).sort_values(score_col, ascending=ascending)
    return ", ".join(d["ticker"].head(n).tolist()) or None


def equity_summary(eq_df: pd.DataFrame, rs_df: pd.DataFrame,
                   fs_df: pd.DataFrame) -> pd.DataFrame:
    """Build one row per date of equity signals: index levels/returns, sector
    leadership, and the strongest/weakest factor-screen names."""
    rows = []
    if eq_df is not None and len(eq_df):
        idx = eq_df[eq_df["ticker"].isin(SNAPSHOT_INDICES)]
        for date, g in idx.groupby("price_date"):
            row = {"date": date}
            for tk, alias in SNAPSHOT_INDICES.items():
                m = g[g["ticker"] == tk]
                if len(m):
                    row[alias] = float(m["adj_close"].iloc[0])
                    r = m["ret_1d"].iloc[0]
                    row[f"{alias}_ret_1d"] = None if pd.isna(r) else float(r)
            rows.append(row)
    eq_wide = pd.DataFrame(rows) if rows else pd.DataFrame(columns=["date"])

    lead = []
    if rs_df is not None and len(rs_df):
        sec = rs_df[rs_df["group"] == "sector_etfs"]
        for date, g in sec.groupby("price_date"):
            lead.append({"date": date,
                         "sectors_leading": _top_names(g, "excess_63d"),
                         "sectors_lagging": _top_names(g, "excess_63d", ascending=True)})
    lead_df = pd.DataFrame(lead) if lead else pd.DataFrame(columns=["date"])

    fac = []
    if fs_df is not None and len(fs_df):
        for date, g in fs_df.groupby("price_date"):
            fac.append({"date": date,
                        "top_factor_names": _top_names(g, "composite_z"),
                        "weak_factor_names": _top_names(g, "composite_z", ascending=True)})
    fac_df = pd.DataFrame(fac) if fac else pd.DataFrame(columns=["date"])

    out = eq_wide
    for extra in (lead_df, fac_df):
        out = out.merge(extra, on="date", how="outer") if len(extra) else out
    if len(out):
        out["date"] = pd.to_datetime(out["date"]).dt.date
        out = out.sort_values("date").reset_index(drop=True)
    return out


def _read(con, sql):
    """Query helper that tolerates a table not existing yet (returns None)."""
    try:
        return con.execute(sql).df()
    except Exception:      # noqa: BLE001 - equity tables are optional
        return None


def run(con) -> tuple[int, int]:
    """Read analytics, compute the two tables, write them back to the warehouse."""
    analytics = con.execute(
        "SELECT series_id, obs_date, value, primary_value, primary_zscore "
        "FROM fct_series_analytics").df()
    regime, snap = compute(analytics)

    eq = _read(con, "SELECT ticker, price_date, adj_close, ret_1d FROM fct_equity_analytics")
    rs = _read(con, 'SELECT ticker, price_date, "group", excess_63d FROM fct_relative_strength')
    fs = _read(con, "SELECT ticker, price_date, composite_z FROM fct_factor_scores")
    if eq is not None or rs is not None or fs is not None:
        eq_sum = equity_summary(eq, rs, fs)
        if len(eq_sum):
            snap = snap.merge(eq_sum, on="date", how="left")

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
