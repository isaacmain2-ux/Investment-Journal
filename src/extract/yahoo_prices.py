"""
Batch EOD price client (Yahoo via yfinance).

The key difference from the watchlist equity loader: this downloads MANY tickers per
call with `yf.download([...])`, so a 500-name universe is a handful of chunked
requests, not 500 throttled ones. A browser-like session and retry/backoff give it the
best shot from a cloud IP (the same hardening the skew client uses).

The network sits behind one seam (`_download`); `parse_download` — turning yfinance's
multi-index frame into tidy per-ticker rows — is pure and unit-tested offline.

Prices are auto-adjusted (splits/dividends), so returns and momentum are correct; the
latest close is unaffected. Dotted tickers map to Yahoo's dash form (BRK.B -> BRK-B).
"""
from __future__ import annotations

import time

_SESSION = None
_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36")


def to_yahoo(ticker: str) -> str:
    """AAPL -> AAPL, BRK.B -> BRK-B  (Yahoo's class-share convention)."""
    return ticker.strip().upper().replace(".", "-")


def _session():
    global _SESSION
    if _SESSION is None:
        import requests
        s = requests.Session()
        s.headers.update({"User-Agent": _UA})
        _SESSION = s
    return _SESSION


# ------------------------------------------------------------------ network seam
def _download(symbols, start, session):
    import yfinance as yf
    kw = dict(start=start, auto_adjust=True, group_by="ticker", progress=False, threads=True)
    try:
        return yf.download(symbols, session=session, **kw)
    except TypeError:                          # some yfinance versions reject session=
        return yf.download(symbols, **kw)


def _f(v):
    try:
        import math
        f = float(v)
        return None if math.isnan(f) else f
    except (ValueError, TypeError):
        return None


def parse_download(df, ymap: dict) -> list[dict]:
    """yfinance download frame -> tidy rows. `ymap` maps Yahoo symbol -> our ticker.
    Handles both the multi-ticker (MultiIndex columns) and single-ticker (flat) cases."""
    import pandas as pd
    if df is None or len(df) == 0:
        return []
    multi = isinstance(df.columns, pd.MultiIndex)
    rows = []
    for ysym, ticker in ymap.items():
        if multi:
            if ysym not in set(df.columns.get_level_values(0)):
                continue
            sub = df[ysym]
        else:
            sub = df                            # single-ticker frame: flat columns
        for idx, r in sub.iterrows():
            close = _f(r.get("Close"))
            if close is None:
                continue
            d = idx.date() if hasattr(idx, "date") else idx
            rows.append({"ticker": ticker, "date": d, "open": _f(r.get("Open")),
                         "high": _f(r.get("High")), "low": _f(r.get("Low")),
                         "close": close, "volume": _f(r.get("Volume"))})
    return rows


def fetch_prices_batch(tickers, start="2015-01-01", chunk=80, retries=2, pace=2.0):
    """Download all tickers in chunks. Returns (rows, failed_tickers). Never raises."""
    sess = _session()
    all_rows, failed = [], []
    for i in range(0, len(tickers), chunk):
        group = tickers[i:i + chunk]
        ymap = {to_yahoo(t): t for t in group}
        got = None
        for attempt in range(max(1, retries)):
            try:
                df = _download(list(ymap.keys()), start, sess)
                got = parse_download(df, ymap)
                if got:
                    break
            except Exception:                   # noqa: BLE001 - any yfinance hiccup
                got = None
            time.sleep(pace * (2 ** attempt))
        if got:
            all_rows.extend(got)
            seen = {r["ticker"] for r in got}
            failed.extend(t for t in group if t not in seen)
        else:
            failed.extend(group)
        time.sleep(0.5)                         # gentle pacing between chunks
    return all_rows, failed
