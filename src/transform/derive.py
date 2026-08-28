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
the top factor-screen names) so one row carries both the macro and market view,
and - when FT news has been ingested - a light HEADLINE block (how many stories
that day plus the most recent titles) for the Phase 3 overlay to read. Both the
equity and headline blocks are optional: the snapshot builds without them.
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

# how many recent headline titles to surface per day in the snapshot
TOP_HEADLINES = 5


def _state(x, pos_label, neg_label, mid_label="Neutral"):
    if pd.isna(x):
        return None
    if x > NEUTRAL_BAND:
        return pos_label
    if x < -NEUTRAL_BAND:
        return neg_label
    return mid_label


def compute(analytics_df: pd.DataFrame, vol_term_df: pd.DataFrame | None = None):
    """Given the fct_series_analytics rows (long), return (regime_df, snapshot_df),
    each one row per date. Macro only - equity fields are merged in by `run`.
    If vol_term_df is supplied, a volatility dimension from the term structure
    (contango/backwardation) is appended to the regime label."""
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

    # optional volatility dimension from the term structure (contango/backwardation)
    regime["vol_state"] = None
    if vol_term_df is not None and len(vol_term_df):
        smap = {"contango": "Calm", "flat": "Neutral", "backwardation": "Stressed"}
        vt = vol_term_df.copy()
        vt["_d"] = pd.to_datetime(vt["date"]).dt.normalize()
        vt_state = dict(zip(vt["_d"], vt["ts_state"].map(smap)))
        regime["vol_state"] = pd.to_datetime(regime["date"]).dt.normalize().map(vt_state)

    def _label(r):
        if None in (r["growth_state"], r["inflation_state"], r["conditions_state"]):
            return None
        base = (f"Growth {r['growth_state']} \u00b7 Inflation {r['inflation_state']} "
                f"\u00b7 Conditions {r['conditions_state']}")
        if pd.notna(r.get("vol_state")):
            base += f" \u00b7 Vol {r['vol_state']}"
        return base
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


def headline_summary(hl_df: pd.DataFrame, top_n: int = TOP_HEADLINES) -> pd.DataFrame:
    """Build one row per date from fct_headlines: how many FT stories were
    published that day and the most recent titles. Pure and tolerant - returns an
    empty frame for None/empty input, and ignores stories with no published_date
    (they can't be placed on a calendar day)."""
    cols = ["date", "n_headlines", "top_headlines"]
    if hl_df is None or len(hl_df) == 0:
        return pd.DataFrame(columns=cols)

    df = hl_df.copy()
    df = df[df["published_date"].notna()]
    if len(df) == 0:
        return pd.DataFrame(columns=cols)
    df["date"] = pd.to_datetime(df["published_date"]).dt.date

    # most-recent-first within a day, so the top_n titles are the freshest
    if "published_at" in df.columns:
        df = df.sort_values("published_at", ascending=False, na_position="last")

    rows = []
    for date, g in df.groupby("date"):
        titles = [t for t in g["title"].tolist() if isinstance(t, str) and t.strip()]
        rows.append({"date": date,
                     "n_headlines": int(len(g)),
                     "top_headlines": " | ".join(titles[:top_n]) or None})
    return pd.DataFrame(rows).sort_values("date").reset_index(drop=True)


def vol_summary(vol_df: pd.DataFrame) -> pd.DataFrame:
    """One row per date of the volatility term-structure block: the VIX
    contango/backwardation ratio and its banded state. Pure and tolerant of
    None/empty - returns an empty frame when fct_vol_term is absent."""
    cols = ["date", "vix_ts_ratio", "ts_state"]
    if vol_df is None or len(vol_df) == 0 or "date" not in vol_df.columns:
        return pd.DataFrame(columns=cols)
    df = vol_df.copy()
    for c in ("vix_ts_ratio", "ts_state"):
        if c not in df.columns:
            df[c] = None
    df["date"] = pd.to_datetime(df["date"], errors="coerce").dt.date
    return df[cols].dropna(subset=["date"]).reset_index(drop=True)


POSITIONING_MARKETS = ("vix", "sp500")


def positioning_summary(pos_df: pd.DataFrame) -> pd.DataFrame:
    """Point-in-time positioning block keyed by available_from: the latest
    Leveraged Funds net percentile for the key markets, ready for an as-of merge
    onto the daily snapshot. Pure; tolerant of None/empty."""
    cols = ["available_from", "vix_lev_pctile", "sp500_lev_pctile", "positioning_note"]
    if pos_df is None or len(pos_df) == 0 or "available_from" not in pos_df.columns:
        return pd.DataFrame(columns=cols)
    df = pos_df.copy()
    df["available_from"] = pd.to_datetime(df["available_from"], errors="coerce")
    df = df.dropna(subset=["available_from"])
    keep = df[df["market_id"].isin(POSITIONING_MARKETS)]
    if not len(keep):
        return pd.DataFrame(columns=cols)
    wide = (keep.sort_values("available_from")
                .pivot_table(index="available_from", columns="market_id",
                             values="net_lev_pctile", aggfunc="last"))
    out = pd.DataFrame({"available_from": wide.index})
    out["vix_lev_pctile"] = wide["vix"].values if "vix" in wide.columns else None
    out["sp500_lev_pctile"] = wide["sp500"].values if "sp500" in wide.columns else None

    def _note(r):
        bits = []
        if pd.notna(r["vix_lev_pctile"]):
            bits.append(f"VIX lev {r['vix_lev_pctile'] * 100:.0f}%ile")
        if pd.notna(r["sp500_lev_pctile"]):
            bits.append(f"S&P lev {r['sp500_lev_pctile'] * 100:.0f}%ile")
        return " | ".join(bits)

    out["positioning_note"] = out.apply(_note, axis=1)
    return out[cols].reset_index(drop=True)


def _fold_positioning(snap: pd.DataFrame, pos_sum: pd.DataFrame) -> pd.DataFrame:
    """Point-in-time as-of merge of the positioning block onto the daily snapshot.
    Both date keys are forced to the same datetime resolution first - merge_asof
    requires identical units, and the two columns can arrive as datetime64[s] vs
    [us] depending on how each was built."""
    snap = snap.sort_values("date").reset_index(drop=True)
    snap["_d"] = pd.to_datetime(snap["date"]).astype("datetime64[ns]")
    pos_sum = pos_sum.sort_values("available_from").copy()
    pos_sum["available_from"] = pd.to_datetime(pos_sum["available_from"]).astype("datetime64[ns]")
    merged = pd.merge_asof(snap, pos_sum, left_on="_d", right_on="available_from",
                           direction="backward")
    return merged.drop(columns=["_d", "available_from"])


SKEW_TICKER = "spx"


def skew_summary(skew_df: pd.DataFrame) -> pd.DataFrame:
    """Point-in-time skew block keyed by capture_date: the key ticker's latest
    put_skew and its percentile, ready for an as-of merge onto the daily snapshot.
    Pure; tolerant of None/empty."""
    cols = ["capture_date", "put_skew", "put_skew_pctile", "skew_note"]
    if skew_df is None or len(skew_df) == 0 or "capture_date" not in skew_df.columns:
        return pd.DataFrame(columns=cols)
    df = skew_df[skew_df["ticker_id"] == SKEW_TICKER].copy()
    if not len(df):
        return pd.DataFrame(columns=cols)
    df["capture_date"] = pd.to_datetime(df["capture_date"], errors="coerce")
    df = df.dropna(subset=["capture_date"]).sort_values("capture_date")
    out = df[["capture_date", "put_skew", "put_skew_pctile"]].copy()

    def _note(r):
        if pd.isna(r["put_skew"]):
            return ""
        s = f"SPY put-skew {r['put_skew']:+.3f}"
        if pd.notna(r["put_skew_pctile"]):
            s += f" ({r['put_skew_pctile'] * 100:.0f}%ile)"
        return s

    out["skew_note"] = out.apply(_note, axis=1)
    return out[cols].reset_index(drop=True)


def _fold_skew(snap: pd.DataFrame, skew_sum: pd.DataFrame) -> pd.DataFrame:
    """Point-in-time as-of merge of the skew block onto the daily snapshot (latest
    capture on or before each date). Datetime resolution normalised as above."""
    snap = snap.sort_values("date").reset_index(drop=True)
    snap["_d"] = pd.to_datetime(snap["date"]).astype("datetime64[ns]")
    skew_sum = skew_sum.sort_values("capture_date").copy()
    skew_sum["capture_date"] = pd.to_datetime(skew_sum["capture_date"]).astype("datetime64[ns]")
    merged = pd.merge_asof(snap, skew_sum, left_on="_d", right_on="capture_date",
                           direction="backward")
    return merged.drop(columns=["_d", "capture_date"])


JOURNAL_PORTFOLIO = "main"     # single book folded into the snapshot; other books
                                # (if any) still show up in the Journal section's own table


def journal_summary(pv_df: pd.DataFrame) -> pd.DataFrame:
    """Point-in-time journal block keyed by date: the main book's mark-to-market
    value, unrealised/realised P&L and open-position count, ready for an as-of merge
    onto the daily snapshot. Pure; tolerant of None/empty (no ledger yet)."""
    cols = ["date", "journal_value", "journal_unrealized_pnl", "journal_realized_pnl",
            "journal_open_positions"]
    if pv_df is None or len(pv_df) == 0 or "date" not in pv_df.columns:
        return pd.DataFrame(columns=cols)
    df = pv_df[pv_df.get("portfolio") == JOURNAL_PORTFOLIO].copy()
    if not len(df):
        return pd.DataFrame(columns=cols)
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df = df.dropna(subset=["date"]).sort_values("date")
    out = pd.DataFrame({
        "date": df["date"],
        "journal_value": df.get("total_value"),
        "journal_unrealized_pnl": df.get("unrealized_pnl"),
        "journal_realized_pnl": df.get("realized_pnl_cum"),
        "journal_open_positions": df.get("n_positions_open"),
    })
    return out[cols].reset_index(drop=True)


def _fold_journal(snap: pd.DataFrame, journal_sum: pd.DataFrame) -> pd.DataFrame:
    """Point-in-time as-of merge of the journal block onto the daily snapshot (latest
    valuation on or before each date). Datetime resolution normalised, same fix as
    _fold_skew/_fold_positioning - merge_asof needs identical [ns] units on both sides."""
    snap = snap.sort_values("date").reset_index(drop=True)
    snap["_d"] = pd.to_datetime(snap["date"]).astype("datetime64[ns]")
    journal_sum = journal_sum.sort_values("date").copy()
    journal_sum["date"] = pd.to_datetime(journal_sum["date"]).astype("datetime64[ns]")
    merged = pd.merge_asof(snap, journal_sum, left_on="_d", right_on="date",
                           direction="backward", suffixes=("", "_journal"))
    merged = merged.drop(columns=["_d"])
    if "date_journal" in merged.columns:
        merged = merged.drop(columns=["date_journal"])
    return merged


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
    # read the vol term structure up front so it can feed BOTH the regime label
    # and the snapshot's volatility block
    vt = _read(con, "SELECT date, vix_ts_ratio, ts_state FROM fct_vol_term")
    regime, snap = compute(analytics, vol_term_df=vt)

    eq = _read(con, "SELECT ticker, price_date, adj_close, ret_1d FROM fct_equity_analytics")
    rs = _read(con, 'SELECT ticker, price_date, "group", excess_63d FROM fct_relative_strength')
    fs = _read(con, "SELECT ticker, price_date, composite_z FROM fct_factor_scores")
    if eq is not None or rs is not None or fs is not None:
        eq_sum = equity_summary(eq, rs, fs)
        if len(eq_sum):
            snap = snap.merge(eq_sum, on="date", how="left")

    # optional FT headline block - only if news has been ingested
    hl = _read(con, "SELECT published_date, published_at, title, section FROM fct_headlines")
    if hl is not None:
        hl_sum = headline_summary(hl)
        if len(hl_sum):
            snap = snap.merge(hl_sum, on="date", how="left")

    # optional volatility term-structure block - only if fct_vol_term is built
    if vt is not None:
        vt_sum = vol_summary(vt)
        if len(vt_sum):
            snap = snap.merge(vt_sum, on="date", how="left")

    # optional positioning block - point-in-time as-of merge on available_from
    pos = _read(con, "SELECT market_id, available_from, net_lev_pctile FROM fct_positioning")
    if pos is not None:
        pos_sum = positioning_summary(pos)
        if len(pos_sum):
            snap = _fold_positioning(snap, pos_sum)

    # optional options-skew block - point-in-time as-of merge on capture_date
    sk = _read(con, "SELECT ticker_id, capture_date, put_skew, put_skew_pctile FROM fct_skew")
    if sk is not None:
        sk_sum = skew_summary(sk)
        if len(sk_sum):
            snap = _fold_skew(snap, sk_sum)

    # optional journal block - point-in-time as-of merge on date (main book only)
    pv = _read(con, "SELECT portfolio, date, total_value, unrealized_pnl, "
                    "realized_pnl_cum, n_positions_open FROM fct_portfolio_value")
    if pv is not None:
        j_sum = journal_summary(pv)
        if len(j_sum):
            snap = _fold_journal(snap, j_sum)

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
