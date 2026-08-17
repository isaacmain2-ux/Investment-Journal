"""
Stooq client — free end-of-day price history, no key.

Stooq serves a plain CSV per symbol; US tickers are lower-cased with a `.us` suffix
(AAPL -> aapl.us). One network seam (`_get`) then pure CSV parsing, so it tests
offline. Global symbols work too (different suffixes), which is the seam we'd reuse
if the universe goes international later.
"""
from __future__ import annotations

import csv
import io
import time
from datetime import datetime

import requests

CSV_URL = "https://stooq.com/q/d/l/?s={symbol}&i=d"
_MIN_INTERVAL = 0.2


class PriceResult:
    def __init__(self, ticker, rows=None, status="ok", error=None):
        self.ticker = ticker
        self.rows = rows if rows is not None else []
        self.status = status                 # ok | empty | error
        self.error = error


def to_symbol(ticker: str, suffix: str = "us") -> str:
    """AAPL -> aapl.us  (Stooq's US convention)."""
    return f"{ticker.strip().lower()}.{suffix}"


# ------------------------------------------------------------------ network seam
def _get(url, timeout=30):
    return requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=timeout)


def _num(v):
    try:
        return float(v)
    except (ValueError, TypeError):
        return None


def parse_csv(text: str, ticker: str) -> list[dict]:
    """Stooq daily CSV -> tidy rows. Pure. Empty/'N/D' responses yield []."""
    if not text or "Date" not in text.splitlines()[0]:
        return []
    out = []
    for row in csv.DictReader(io.StringIO(text)):
        try:
            d = datetime.strptime(row["Date"], "%Y-%m-%d").date()
        except (ValueError, KeyError, TypeError):
            continue
        close = _num(row.get("Close"))
        if close is None:
            continue
        out.append({
            "ticker": ticker, "date": d,
            "open": _num(row.get("Open")), "high": _num(row.get("High")),
            "low": _num(row.get("Low")), "close": close,
            "volume": _num(row.get("Volume")),
        })
    return out


def fetch_prices(ticker, suffix="us", retries=3, pace=1.0) -> PriceResult:
    """Fetch one symbol's daily history. Never raises."""
    url = CSV_URL.format(symbol=to_symbol(ticker, suffix))
    last = None
    for attempt in range(retries):
        try:
            resp = _get(url)
            if resp.status_code == 200:
                rows = parse_csv(resp.text, ticker)
                time.sleep(_MIN_INTERVAL)
                return PriceResult(ticker, rows=rows, status="ok" if rows else "empty",
                                   error=None if rows else "no rows (delisted or throttled)")
            last = f"http {resp.status_code}"
        except requests.RequestException as e:
            last = str(e)
        time.sleep(pace * (2 ** attempt))
    return PriceResult(ticker, status="error", error=f"{last} after {retries} attempts")
