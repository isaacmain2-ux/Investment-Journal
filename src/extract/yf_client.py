"""
Yahoo Finance price client via yfinance.

Design mirrors fred_client:
  * The single network call lives in `_download`, so tests mock it and run offline.
  * Tickers are fetched in BATCHES (one request per batch, not per ticker) to stay
    well under Yahoo's informal rate limit; batches are paced apart and retried
    with backoff on rate-limit errors.
  * Each ticker yields a PriceResult (ok / empty / error) - one bad or delisted
    ticker never crashes the run.

yfinance is imported lazily inside `_download`, so this module imports (and its
non-network logic tests) even where yfinance isn't installed.
"""
from __future__ import annotations

import time

import pandas as pd

COLS = ["price_date", "open", "high", "low", "close", "adj_close", "volume"]
_FIELD_MAP = {"Open": "open", "High": "high", "Low": "low",
              "Close": "close", "Adj Close": "adj_close", "Volume": "volume"}


class PriceResult:
    """Outcome of fetching one ticker's price history."""

    def __init__(self, ticker: str, df: pd.DataFrame | None = None,
                 status: str = "ok", error: str | None = None):
        self.ticker = ticker
        self.df = df if df is not None else pd.DataFrame(columns=COLS)
        self.status = status            # "ok" | "empty" | "error"
        self.error = error

    @property
    def n_obs(self) -> int:
        return len(self.df)

    def __repr__(self) -> str:
        return f"PriceResult({self.ticker}, status={self.status}, n_obs={self.n_obs})"


def _download(tickers, start, end):
    """The ONLY network call. Mock this in tests. Returns a yfinance DataFrame
    (MultiIndex columns [ticker, field] for many tickers; single-level for one)."""
    import yfinance as yf
    return yf.download(tickers, start=start, end=end, group_by="ticker",
                       auto_adjust=False, threads=False, progress=False)


def _is_rate_limit(err) -> bool:
    m = str(err).lower()
    return "rate" in m or "429" in m or "too many" in m


def _batches(items, size):
    for i in range(0, len(items), size):
        yield items[i:i + size]


def _extract(raw, ticker: str) -> PriceResult:
    """Pull one ticker's tidy OHLCV frame out of a (possibly batched) download."""
    try:
        if raw is None or len(raw) == 0:
            return PriceResult(ticker, status="empty")
        if isinstance(raw.columns, pd.MultiIndex):
            if ticker not in raw.columns.get_level_values(0):
                return PriceResult(ticker, status="empty")
            sub = raw[ticker]
        else:
            sub = raw                                   # single-ticker download
        sub = sub.dropna(how="all")
        if sub.empty:
            return PriceResult(ticker, status="empty")

        idx = pd.to_datetime(sub.index)
        out = pd.DataFrame({"price_date": idx.date})
        for src, dst in _FIELD_MAP.items():
            out[dst] = sub[src].values if src in sub.columns else pd.NA
        out = out[COLS].dropna(subset=["close"]).reset_index(drop=True)
        if out.empty:
            return PriceResult(ticker, status="empty")
        return PriceResult(ticker, df=out, status="ok")
    except Exception as e:                              # noqa: BLE001 - never crash a run
        return PriceResult(ticker, status="error", error=f"parse: {e}")


def _fetch_batch(batch, start, end, retries, pace):
    """Download one batch, retrying with backoff on rate-limit errors.
    Returns the raw DataFrame, or None if the batch ultimately failed."""
    for attempt in range(1, retries + 1):
        try:
            return _download(batch, start, end)
        except Exception as e:                          # noqa: BLE001
            if _is_rate_limit(e) and attempt < retries:
                time.sleep(pace * (2 ** attempt))       # exponential backoff
                continue
            return None
    return None


def fetch_prices(tickers, start: str = "2010-01-01", end=None,
                 batch_size: int = 30, retries: int = 3,
                 pace: float = 1.0) -> dict[str, PriceResult]:
    """Fetch daily OHLCV for many tickers in batches. Returns {ticker: PriceResult}.
    Never raises for a bad ticker or a rate-limit - outcomes are in the results."""
    results: dict[str, PriceResult] = {}
    for batch in _batches(list(tickers), batch_size):
        raw = _fetch_batch(batch, start, end, retries, pace)
        for t in batch:
            results[t] = (_extract(raw, t) if raw is not None
                          else PriceResult(t, status="error", error="batch download failed"))
        if pace:
            time.sleep(pace)                            # pace between batches
    return results
