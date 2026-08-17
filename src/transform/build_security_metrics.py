"""
P2 - fct_security_metrics: comparable, per-stock measures, point-in-time.

One row per (ticker, asof_date) combining:
  * Momentum / price   from stg_security_prices  (12-1m, 6m, distance from 52w high)
  * Value              earnings/FCF/sales yields, P/E, P/B
  * Quality            ROE, gross/operating/net margin, debt-to-equity
  * Growth             revenue & EPS year-on-year

Fundamentals are taken **point-in-time**: only facts filed on or before `asof_date`
are used, and flow metrics use the latest full fiscal year (unambiguous with just the
period end + fiscal period we store; trailing-twelve-months is a later refinement that
needs period start dates). Balance-sheet items use the most recent period. Because the
computation is parameterised by `asof_date`, the same code produces today's snapshot
now and a historical panel for backtesting later.

These are the raw comparable numbers; the cross-sectional ranking into factor scores
is P3.
"""
from __future__ import annotations

from datetime import date

import pandas as pd

from src.load import load_securities

get_connection = load_securities.get_connection

FLOW = ["revenue", "net_income", "gross_profit", "operating_income",
        "op_cash_flow", "capex", "eps_diluted"]
STOCK = ["assets", "equity", "shares", "long_term_debt"]

_COLS = ["ticker", "asof_date", "sector", "last_close", "market_cap",
         "earnings_yield", "pe", "pb", "ps", "fcf_yield",
         "roe", "gross_margin", "op_margin", "net_margin", "debt_to_equity",
         "rev_growth_yoy", "eps_growth_yoy",
         "ret_1m", "ret_6m", "ret_12_1m", "dist_52w_high"]


def ensure_schema(con) -> None:
    con.execute("""
        CREATE TABLE IF NOT EXISTS fct_security_metrics (
            ticker VARCHAR, asof_date DATE, sector VARCHAR,
            last_close DOUBLE, market_cap DOUBLE,
            earnings_yield DOUBLE, pe DOUBLE, pb DOUBLE, ps DOUBLE, fcf_yield DOUBLE,
            roe DOUBLE, gross_margin DOUBLE, op_margin DOUBLE, net_margin DOUBLE,
            debt_to_equity DOUBLE, rev_growth_yoy DOUBLE, eps_growth_yoy DOUBLE,
            ret_1m DOUBLE, ret_6m DOUBLE, ret_12_1m DOUBLE, dist_52w_high DOUBLE,
            built_at TIMESTAMP,
            PRIMARY KEY (ticker, asof_date)
        )""")


# ------------------------------------------------------------------ helpers
MARKET_CAP_FLOOR = 5e7          # $50M - below this for an S&P 500 name is a data error


def _div(a, b):
    if a is None or b in (None, 0) or (isinstance(b, float) and b == 0.0):
        return None
    try:
        return a / b
    except (TypeError, ZeroDivisionError):
        return None


def _sane(x, lo, hi):
    """Return x only if it's within a plausible range - else None. A guard against one
    bad input (a broken share count, a negative-equity book ratio) producing an
    impossible number that would then poison the cross-sectional ranking in P3."""
    return x if (x is not None and lo <= x <= hi) else None


# ------------------------------------------------------------------ momentum
def _mom(closes: pd.Series) -> dict:
    """Price-based measures from a date-sorted close series (trading-day offsets)."""
    n = len(closes)
    if n == 0:
        return {}
    last = float(closes.iloc[-1])

    def ago(k):
        return float(closes.iloc[-1 - k]) if n > k else None

    c21, c126, c252 = ago(21), ago(126), ago(252)
    hi = float(closes.iloc[-252:].max())
    return {
        "last_close": last,
        "ret_1m": _div(last - c21, c21) if c21 else None,
        "ret_6m": _div(last - c126, c126) if c126 else None,
        "ret_12_1m": _div(c21 - c252, c252) if (c21 and c252) else None,   # 12m skip last month
        "dist_52w_high": _div(last - hi, hi) if hi else None,
    }


def price_metrics(prices: pd.DataFrame, asof: date) -> dict:
    """Per-ticker momentum/price metrics as of `asof`."""
    if prices is None or len(prices) == 0:
        return {}
    p = prices[prices["date"] <= asof]
    out = {}
    for ticker, sub in p.groupby("ticker"):
        closes = sub.sort_values("date")["close"].astype(float)
        out[ticker] = _mom(closes)
    return out


# ------------------------------------------------------------------ fundamentals
def _latest_val(sub: pd.DataFrame, metric: str, annual: bool):
    m = sub[sub["metric"] == metric]
    if annual:
        m = m[m["fiscal_period"] == "FY"]
    if len(m) == 0:
        return None
    m = m.sort_values(["period_end", "filed_date"])
    return m.iloc[-1]["value"]


def _prior_fy_val(sub: pd.DataFrame, metric: str):
    m = sub[(sub["metric"] == metric) & (sub["fiscal_period"] == "FY")]
    ends = sorted(m["period_end"].unique())
    if len(ends) < 2:
        return None
    prev = m[m["period_end"] == ends[-2]].sort_values("filed_date")
    return prev.iloc[-1]["value"]


def latest_fundamentals(fund: pd.DataFrame, asof: date) -> dict:
    """Per-ticker point-in-time fundamentals: latest full-year flows, latest-period
    balance-sheet items, and prior-year values for growth. Only facts filed <= asof."""
    if fund is None or len(fund) == 0:
        return {}
    f = fund[fund["filed_date"] <= asof]
    out = {}
    for ticker, sub in f.groupby("ticker"):
        d = {m: _latest_val(sub, m, annual=True) for m in FLOW}
        d.update({m: _latest_val(sub, m, annual=False) for m in STOCK})
        d["revenue_prev"] = _prior_fy_val(sub, "revenue")
        d["eps_prev"] = _prior_fy_val(sub, "eps_diluted")
        out[ticker] = d
    return out


# ------------------------------------------------------------------ ratios
def compute_row(ticker, sector, pm: dict, fm: dict) -> dict:
    last_close = pm.get("last_close")
    shares = fm.get("shares")
    revenue, net_income = fm.get("revenue"), fm.get("net_income")
    equity, eps = fm.get("equity"), fm.get("eps_diluted")
    ocf, capex = fm.get("op_cash_flow"), fm.get("capex")
    rev_prev, eps_prev = fm.get("revenue_prev"), fm.get("eps_prev")

    market_cap = last_close * shares if (last_close is not None and shares and shares > 0) else None
    if market_cap is not None and market_cap < MARKET_CAP_FLOOR:
        market_cap = None                       # implausible -> emit no cap-based ratios
    equity_pos = equity if (equity is not None and equity > 0) else None   # book ratios need +ve equity
    fcf = (ocf - capex) if (ocf is not None and capex is not None) else None
    profit = net_income if (net_income is not None and net_income > 0) else None  # PE only for profits

    return {
        "ticker": ticker, "sector": sector, "last_close": last_close, "market_cap": market_cap,
        "earnings_yield": _sane(_div(net_income, market_cap), -0.5, 0.5),
        "pe": _sane(_div(market_cap, profit), 0, 2000),
        "pb": _sane(_div(market_cap, equity_pos), 0, 200),
        "ps": _sane(_div(market_cap, revenue), 0, 200),
        "fcf_yield": _sane(_div(fcf, market_cap), -0.5, 0.5),
        "roe": _sane(_div(net_income, equity_pos), -5, 5),
        "gross_margin": _sane(_div(fm.get("gross_profit"), revenue), -1, 1),
        "op_margin": _sane(_div(fm.get("operating_income"), revenue), -2, 1),
        "net_margin": _sane(_div(net_income, revenue), -2, 1),
        "debt_to_equity": _sane(_div(fm.get("long_term_debt"), equity_pos), 0, 100),
        "rev_growth_yoy": _sane(_div((revenue - rev_prev) if (revenue is not None and rev_prev is not None) else None, rev_prev), -1, 10),
        "eps_growth_yoy": _sane(_div((eps - eps_prev) if (eps is not None and eps_prev is not None) else None,
                                     abs(eps_prev) if eps_prev else None), -10, 10),
        "ret_1m": pm.get("ret_1m"), "ret_6m": pm.get("ret_6m"),
        "ret_12_1m": pm.get("ret_12_1m"), "dist_52w_high": pm.get("dist_52w_high"),
    }


def build(prices, fund, dim, asof: date) -> list[dict]:
    pm = price_metrics(prices, asof)
    fm = latest_fundamentals(fund, asof)
    sectors = {}
    if dim is not None and len(dim):
        sectors = dict(zip(dim["ticker"], dim["sector"]))
    tickers = sorted(set(pm) | set(fm))
    rows = []
    for t in tickers:
        row = compute_row(t, sectors.get(t), pm.get(t, {}), fm.get(t, {}))
        row["asof_date"] = asof
        rows.append(row)
    return rows


# ------------------------------------------------------------------ run
def _read(con, sql) -> pd.DataFrame:
    cur = con.execute(sql)
    return pd.DataFrame(cur.fetchall(), columns=[d[0] for d in cur.description])


def run(con=None, asof: date | None = None) -> int:
    own = con is None
    con = con or get_connection()
    try:
        ensure_schema(con)
        prices = _read(con, "SELECT ticker, date, close FROM stg_security_prices")
        fund = _read(con, "SELECT ticker, metric, period_end, fiscal_period, filed_date, value "
                          "FROM stg_security_fundamentals")
        dim = _read(con, "SELECT ticker, sector FROM dim_security")
        if len(prices) == 0:
            print("No prices in the warehouse - run universe_ingest first.")
            return 1
        if asof is None:
            asof = max(prices["date"])
        rows = [r for r in build(prices, fund, dim, asof) if r.get("last_close") is not None]
        con.execute("DELETE FROM fct_security_metrics WHERE asof_date = ?", [asof])
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        con.executemany(
            f"INSERT INTO fct_security_metrics ({', '.join(_COLS)}, built_at) "
            f"VALUES ({', '.join(['?'] * len(_COLS))}, ?)",
            [tuple(r.get(c) for c in _COLS) + (now,) for r in rows])
        flagged = sum(1 for r in rows if r.get("market_cap") is None)
        valid_ey = sum(1 for r in rows if r.get("earnings_yield") is not None)
        print(f"fct_security_metrics: {len(rows)} names as of {asof} "
              f"({len(rows) - flagged} with a valid market cap, {flagged} flagged; "
              f"{valid_ey} with a usable earnings yield)")
        return 0
    finally:
        if own:
            con.close()


def main():
    import sys
    sys.exit(run())


if __name__ == "__main__":
    main()
