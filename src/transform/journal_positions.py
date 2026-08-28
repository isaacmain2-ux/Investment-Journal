"""
Journal P4/P5 - fct_positions and fct_portfolio_value.

**Design note - why this is Python, not SQL** (a deliberate deviation from the
original build plan's `13_positions.sql` / `14_portfolio.sql`): average-cost
lot tracking is inherently *sequential* - a SELL's realised P&L, and the average
cost left over for the next trade, depend multiplicatively on the running state
built up by every prior trade for that (portfolio, ticker). That's not expressible
as a plain SQL window-function cumulative sum; it needs either `WITH RECURSIVE` or a
row-by-row fold. `derive.py` already established the precedent for exactly this
situation in this codebase ("this needs cross-series alignment ... which pandas does
cleanly, so this is the one transform step done in Python rather than SQL") - the
same reasoning applies here, so positions/portfolio-value follow that precedent
instead of forcing a recursive CTE.

The core logic is three pure functions, fully unit-testable without a database:

    _walk_trades(trades_df)        one row per trade, with the running state AFTER
                                    that trade (quantity_open, avg_cost, realised P&L)
    compute_positions(trades_df)   one row per (portfolio, ticker): current state
    compute_portfolio_value(...)   one row per (portfolio, date): daily mark-to-market

`run(con)` wires them to the warehouse: reads stg_journal_trades + stg_security_prices,
writes fct_positions + fct_portfolio_value. Called from run_transform.py after the SQL
layer (it needs stg_security_prices, which universe_ingest populates independently)
and before derive.py (whose journal_summary() folds the result into the daily snapshot).
"""
from __future__ import annotations

from datetime import datetime, timezone

import pandas as pd

EPS = 1e-9


# ------------------------------------------------------------------ pure core
def _walk_trades(trades_df: pd.DataFrame) -> pd.DataFrame:
    """Sequentially fold BUY/SELL rows per (portfolio, ticker) using average-cost.
    Returns one row per trade carrying the state AFTER that trade. Tolerant of
    None/empty input and of rows with an unrecognised action (skipped, not fatal)."""
    cols = ["portfolio", "ticker", "trade_date", "action", "quantity", "price", "fees",
            "quantity_open", "avg_cost", "realized_pnl_trade", "realized_pnl_cum",
            "conviction", "timeframe", "catalyst", "thesis", "tags", "trade_id"]
    if trades_df is None or len(trades_df) == 0:
        return pd.DataFrame(columns=cols)

    df = trades_df.copy()
    df["trade_date"] = pd.to_datetime(df.get("trade_date"), errors="coerce").dt.date
    df["ticker"] = df.get("ticker", "").astype(str).str.upper()
    df["action"] = df.get("action", "").astype(str).str.upper()
    df["portfolio"] = df.get("portfolio")
    df["portfolio"] = df["portfolio"].where(df["portfolio"].notna() & (df["portfolio"] != ""), "main")
    df["quantity"] = pd.to_numeric(df.get("quantity"), errors="coerce")
    df["price"] = pd.to_numeric(df.get("price"), errors="coerce")
    df["fees"] = pd.to_numeric(df.get("fees"), errors="coerce").fillna(0.0)
    df = df.dropna(subset=["trade_date", "ticker", "quantity", "price"])
    df = df[df["ticker"] != ""]
    if not len(df):
        return pd.DataFrame(columns=cols)

    sort_cols = [c for c in ["trade_date", "entered_at"] if c in df.columns]
    df = df.sort_values(sort_cols, kind="stable").reset_index(drop=True)

    state: dict[tuple[str, str], dict] = {}
    rows = []
    for _, r in df.iterrows():
        key = (r["portfolio"], r["ticker"])
        s = state.setdefault(key, {"qty": 0.0, "avg_cost": 0.0, "realized": 0.0})
        qty, price, fees = float(r["quantity"]), float(r["price"]), float(r["fees"])
        realized_trade = 0.0
        if r["action"] == "BUY":
            new_qty = s["qty"] + qty
            if new_qty > EPS:
                s["avg_cost"] = (s["avg_cost"] * s["qty"] + price * qty + fees) / new_qty
            s["qty"] = new_qty
        elif r["action"] == "SELL":
            sell_qty = min(qty, s["qty"]) if s["qty"] > 0 else 0.0
            realized_trade = (price - s["avg_cost"]) * sell_qty - fees
            s["qty"] -= sell_qty
            s["realized"] += realized_trade
            if s["qty"] <= EPS:
                s["qty"] = 0.0
                s["avg_cost"] = 0.0
        else:
            continue     # unrecognised action - defensive skip, never fatal
        rows.append({
            "portfolio": key[0], "ticker": key[1], "trade_date": r["trade_date"],
            "action": r["action"], "quantity": qty, "price": price, "fees": fees,
            "quantity_open": s["qty"], "avg_cost": s["avg_cost"],
            "realized_pnl_trade": realized_trade, "realized_pnl_cum": s["realized"],
            "conviction": r.get("conviction"), "timeframe": r.get("timeframe"),
            "catalyst": r.get("catalyst"), "thesis": r.get("thesis"), "tags": r.get("tags"),
            "trade_id": r.get("trade_id"),
        })
    return pd.DataFrame(rows, columns=cols) if rows else pd.DataFrame(columns=cols)


def compute_positions(trades_df: pd.DataFrame) -> pd.DataFrame:
    """One row per (portfolio, ticker): the current state as of the latest trade.
    status is OPEN while quantity_open > 0, else CLOSED (kept for the record, not
    dropped - a closed position's realised P&L still matters to the journal)."""
    cols = ["portfolio", "ticker", "status", "quantity_open", "avg_cost", "realized_pnl_cum",
            "first_entry_date", "last_trade_date", "conviction", "timeframe", "catalyst",
            "thesis", "tags"]
    events = _walk_trades(trades_df)
    if not len(events):
        return pd.DataFrame(columns=cols)

    events = events.sort_values(["portfolio", "ticker", "trade_date"])
    first = (events.groupby(["portfolio", "ticker"])["trade_date"].min()
             .rename("first_entry_date"))
    last = events.groupby(["portfolio", "ticker"]).tail(1).set_index(["portfolio", "ticker"])
    out = last.join(first).reset_index()
    out = out.rename(columns={"trade_date": "last_trade_date"})
    out["status"] = out["quantity_open"].apply(lambda q: "OPEN" if q > EPS else "CLOSED")
    return out[cols].reset_index(drop=True)


def compute_portfolio_value(trades_df: pd.DataFrame, prices_df: pd.DataFrame) -> pd.DataFrame:
    """One row per (portfolio, date): mark-to-market of open positions using the
    daily close, plus cumulative realised P&L. Built by an as-of merge (per ticker,
    direction='backward') of each ticker's post-trade state onto its own price
    history - the same merge_asof pattern derive.py uses for the skew/positioning
    snapshot fold-ins - then summed across tickers for each portfolio/date.

    total_value = market_value (of currently open positions) + realized_pnl_cum -
    a simple book-value index; not a cash-tracked P&L (this is a paper journal, not
    a brokerage ledger - see the build plan's "hypothetical" framing)."""
    cols = ["portfolio", "date", "market_value", "cost_basis_open", "unrealized_pnl",
            "realized_pnl_cum", "n_positions_open", "total_value"]
    events = _walk_trades(trades_df)
    if not len(events) or prices_df is None or len(prices_df) == 0:
        return pd.DataFrame(columns=cols)

    # merge_asof requires identical datetime *resolution* on both sides - not just
    # both being datetime64 - or it raises MergeError; force both to [ns] up front.
    # (Same fix derive.py's _fold_skew/_fold_positioning already apply.)
    prices = prices_df.copy()
    prices["ticker"] = prices.get("ticker", "").astype(str).str.upper()
    prices["date"] = pd.to_datetime(prices.get("date"), errors="coerce").astype("datetime64[ns]")
    prices["close"] = pd.to_numeric(prices.get("close"), errors="coerce")
    prices = prices.dropna(subset=["date", "ticker", "close"])

    events = events.copy()
    events["trade_date"] = pd.to_datetime(events["trade_date"]).astype("datetime64[ns]")

    long_rows = []
    for (portfolio, ticker), g in events.groupby(["portfolio", "ticker"]):
        px = prices[prices["ticker"] == ticker].sort_values("date")
        if not len(px):
            continue     # no price history for this ticker - can't mark it, skip
        g2 = g.sort_values("trade_date")[
            ["trade_date", "quantity_open", "avg_cost", "realized_pnl_cum"]]
        merged = pd.merge_asof(px, g2, left_on="date", right_on="trade_date",
                               direction="backward")
        merged = merged.dropna(subset=["quantity_open", "trade_date"])
        merged = merged[merged["date"] >= merged["trade_date"]]
        if not len(merged):
            continue
        merged["portfolio"] = portfolio
        merged["market_value"] = merged["quantity_open"] * merged["close"]
        merged["cost_basis_open"] = merged["quantity_open"] * merged["avg_cost"]
        merged["unrealized_pnl"] = merged["market_value"] - merged["cost_basis_open"]
        long_rows.append(merged[["portfolio", "date", "market_value", "cost_basis_open",
                                 "unrealized_pnl", "realized_pnl_cum", "quantity_open"]])
    if not long_rows:
        return pd.DataFrame(columns=cols)

    long = pd.concat(long_rows, ignore_index=True)
    agg = long.groupby(["portfolio", "date"]).agg(
        market_value=("market_value", "sum"),
        cost_basis_open=("cost_basis_open", "sum"),
        unrealized_pnl=("unrealized_pnl", "sum"),
        realized_pnl_cum=("realized_pnl_cum", "sum"),
        n_positions_open=("quantity_open", lambda s: int((s > EPS).sum())),
    ).reset_index()
    agg["total_value"] = agg["market_value"] + agg["realized_pnl_cum"]
    agg["date"] = pd.to_datetime(agg["date"]).dt.date
    return agg.sort_values(["portfolio", "date"])[cols].reset_index(drop=True)


# ------------------------------------------------------------------ warehouse wiring
def ensure_schema(con) -> None:
    con.execute("""
        CREATE TABLE IF NOT EXISTS fct_positions (
            portfolio VARCHAR, ticker VARCHAR, status VARCHAR,
            quantity_open DOUBLE, avg_cost DOUBLE, realized_pnl_cum DOUBLE,
            first_entry_date DATE, last_trade_date DATE,
            conviction VARCHAR, timeframe VARCHAR, catalyst VARCHAR, thesis VARCHAR,
            tags VARCHAR, built_at TIMESTAMP,
            PRIMARY KEY (portfolio, ticker)
        )""")
    con.execute("""
        CREATE TABLE IF NOT EXISTS fct_portfolio_value (
            portfolio VARCHAR, date DATE, market_value DOUBLE, cost_basis_open DOUBLE,
            unrealized_pnl DOUBLE, realized_pnl_cum DOUBLE, n_positions_open INTEGER,
            total_value DOUBLE, built_at TIMESTAMP,
            PRIMARY KEY (portfolio, date)
        )""")


def _read(con, sql) -> pd.DataFrame | None:
    try:
        return con.execute(sql).df()
    except Exception:      # noqa: BLE001 - table may not exist yet
        return None


def run(con) -> tuple[int, int]:
    """Read stg_journal_trades + stg_security_prices, write fct_positions and
    fct_portfolio_value. Both tolerate an empty/missing ledger - they just come back
    empty, same as every other optional layer in this project."""
    ensure_schema(con)
    trades = _read(con, "SELECT * FROM stg_journal_trades")
    prices = _read(con, "SELECT ticker, date, close FROM stg_security_prices")

    positions = compute_positions(trades)
    value = compute_portfolio_value(trades, prices)

    now = datetime.now(timezone.utc).replace(tzinfo=None)
    con.execute("DELETE FROM fct_positions")
    if len(positions):
        p = positions.copy()
        p["built_at"] = now
        con.register("positions_df", p)
        con.execute("INSERT INTO fct_positions SELECT * FROM positions_df")
        con.unregister("positions_df")

    con.execute("DELETE FROM fct_portfolio_value")
    if len(value):
        v = value.copy()
        v["built_at"] = now
        con.register("portfolio_value_df", v)
        con.execute("INSERT INTO fct_portfolio_value SELECT * FROM portfolio_value_df")
        con.unregister("portfolio_value_df")

    print(f"fct_positions: {len(positions)} row(s); fct_portfolio_value: {len(value)} row(s)")
    return len(positions), len(value)
