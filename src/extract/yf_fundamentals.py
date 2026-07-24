"""
Company fundamentals via yfinance (watchlist only).

Differs from the price client in two important ways:
  * Fundamentals CANNOT be batched - each ticker needs its own set of calls
    (income statement, balance sheet, cash flow x annual/quarterly). That is real
    rate-limit exposure, so tickers are fetched one at a time with pacing and
    backoff.
  * Free fundamentals are PATCHY and Yahoo's line-item labels change. So we store
    every line item returned, in LONG format, rather than a hard-coded whitelist -
    missing metrics simply mean missing rows, not broken columns. The transform
    layer picks out the metrics it wants.

Point-in-time integrity
-----------------------
Yahoo gives the period END date, not the date the figures were published. Using a
quarter's numbers on its period-end date would be look-ahead bias (companies report
weeks later). Every row therefore carries `available_from = period_end + REPORTING_LAG_DAYS`,
and any point-in-time use should join on that, never on period_end.
"""
from __future__ import annotations

import time
from datetime import timedelta

import pandas as pd

# Conservative assumption for how long after period end the figures are public.
# 90 days comfortably covers most quarterly filing deadlines.
REPORTING_LAG_DAYS = 90

COLS = ["statement", "freq", "metric", "period_end", "available_from", "value"]


class FundamentalsResult:
    """Outcome of fetching one ticker's fundamentals."""

    def __init__(self, ticker: str, df: pd.DataFrame | None = None,
                 status: str = "ok", error: str | None = None):
        self.ticker = ticker
        self.df = df if df is not None else pd.DataFrame(columns=COLS)
        self.status = status              # "ok" | "empty" | "error"
        self.error = error

    @property
    def n_obs(self) -> int:
        return len(self.df)

    def __repr__(self) -> str:
        return f"FundamentalsResult({self.ticker}, status={self.status}, n_obs={self.n_obs})"


def _fetch_statements(ticker: str) -> dict:
    """The ONLY network call. Mock this in tests. Returns {(statement, freq): DataFrame}
    where each frame has metrics as the index and period-end dates as columns."""
    import yfinance as yf
    t = yf.Ticker(ticker)
    return {
        ("income", "annual"):     t.income_stmt,
        ("income", "quarterly"):  t.quarterly_income_stmt,
        ("balance", "annual"):    t.balance_sheet,
        ("balance", "quarterly"): t.quarterly_balance_sheet,
        ("cashflow", "annual"):   t.cashflow,
        ("cashflow", "quarterly"): t.quarterly_cashflow,
    }


def _is_rate_limit(err) -> bool:
    m = str(err).lower()
    return "rate" in m or "429" in m or "too many" in m


def _tidy(frames: dict) -> pd.DataFrame:
    """Melt Yahoo's wide statement frames into long rows, dropping missing values
    and stamping each with its point-in-time availability date."""
    rows = []
    for (statement, freq), df in (frames or {}).items():
        if df is None or getattr(df, "empty", True):
            continue
        for period_end in df.columns:
            try:
                pe = pd.to_datetime(period_end).date()
            except Exception:                       # noqa: BLE001 - skip odd columns
                continue
            avail = pe + timedelta(days=REPORTING_LAG_DAYS)
            for metric in df.index:
                val = df.loc[metric, period_end]
                if pd.isna(val):
                    continue
                try:
                    val = float(val)
                except (TypeError, ValueError):
                    continue
                rows.append({"statement": statement, "freq": freq,
                             "metric": str(metric), "period_end": pe,
                             "available_from": avail, "value": val})
    if not rows:
        return pd.DataFrame(columns=COLS)
    return pd.DataFrame(rows)[COLS]


def fetch_one(ticker: str, retries: int = 3, pace: float = 2.0) -> FundamentalsResult:
    """Fetch and tidy one ticker's fundamentals. Never raises - the outcome is in
    the returned object, so one bad ticker can't sink a run."""
    for attempt in range(1, retries + 1):
        try:
            frames = _fetch_statements(ticker)
        except Exception as e:                      # noqa: BLE001
            if _is_rate_limit(e) and attempt < retries:
                time.sleep(pace * (2 ** attempt))   # exponential backoff
                continue
            return FundamentalsResult(ticker, status="error", error=str(e)[:200])
        df = _tidy(frames)
        if df.empty:
            return FundamentalsResult(ticker, status="empty")
        return FundamentalsResult(ticker, df=df, status="ok")
    return FundamentalsResult(ticker, status="error", error="exhausted retries")


def fetch_fundamentals(tickers, retries: int = 3,
                       pace: float = 2.0) -> dict[str, FundamentalsResult]:
    """Fetch fundamentals for many tickers, one at a time, paced apart."""
    results: dict[str, FundamentalsResult] = {}
    for i, tk in enumerate(tickers):
        results[tk] = fetch_one(tk, retries=retries, pace=pace)
        if pace and i < len(tickers) - 1:
            time.sleep(pace)                        # pace between tickers
    return results


# ---------------------------------------------------------------- company meta
# Yahoo reports each company's statements in its OWN reporting currency, which is
# often NOT the currency the shares trade in (Shell reports USD but trades in
# pence; Unilever reports EUR but trades in pence). Capturing `financialCurrency`
# is what makes price/earnings-style ratios safe to compute later.

def _fetch_info(ticker: str) -> dict:
    """The other network seam. Mock in tests."""
    import yfinance as yf
    return yf.Ticker(ticker).info or {}


def fetch_meta(tickers, pace: float = 1.0) -> dict[str, dict]:
    """Reporting currency + share/market-cap metadata per ticker.
    Failures yield Nones rather than raising."""
    out: dict[str, dict] = {}
    for i, tk in enumerate(tickers):
        try:
            info = _fetch_info(tk)
            out[tk] = {
                "financial_currency": info.get("financialCurrency"),
                "shares_outstanding": info.get("sharesOutstanding"),
                "market_cap": info.get("marketCap"),
            }
        except Exception:                          # noqa: BLE001
            out[tk] = {"financial_currency": None, "shares_outstanding": None,
                       "market_cap": None}
        if pace and i < len(tickers) - 1:
            time.sleep(pace)
    return out
