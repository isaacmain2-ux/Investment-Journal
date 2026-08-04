"""
Options-skew client (Addition #3).

Turns a Yahoo Finance option chain into a handful of implied-volatility skew
measures. Yahoo is unofficial and gives only the *current* chain, so this layer
is snapshot-only: each run captures today's skew and the warehouse accumulates a
history over time.

All network access is isolated behind three seam functions (`_expiries`,
`_chain`, `_spot`), each of which imports yfinance lazily - so this module
imports (and the pure maths tests) without yfinance installed, and the tests
replace the seams with fakes.

The maths (`compute_skew`) is a pure function of (spot, calls, puts) and is fully
unit-tested: it builds an IV-vs-moneyness curve from the out-of-the-money wings
and interpolates IV at fixed moneyness levels.
"""
from __future__ import annotations

import time
from datetime import date, datetime

# default interpolation levels (overridable from the manifest meta)
M_PUT, M_ATM, M_CALL = 0.90, 1.00, 1.10


class SkewResult:
    def __init__(self, ticker_id, ticker, capture_date=None, expiry=None, dte=None,
                 spot=None, measures=None, status="ok", error=None):
        self.ticker_id = ticker_id
        self.ticker = ticker
        self.capture_date = capture_date
        self.expiry = expiry
        self.dte = dte
        self.spot = spot
        self.measures = measures or {}
        self.status = status              # ok | empty | error
        self.error = error

    def row(self):
        """Flat dict for the loader, or None if there's nothing usable."""
        if self.status != "ok":
            return None
        return {"ticker_id": self.ticker_id, "ticker": self.ticker,
                "capture_date": self.capture_date, "expiry": self.expiry,
                "dte": self.dte, "spot": self.spot, **self.measures}


# ------------------------------------------------------------ network seams
_SESSION = None
_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36")


def _session():
    """A reused requests session with a realistic browser User-Agent. Yahoo throttles
    datacenter IPs and default UAs more aggressively, so this improves the odds of a
    clean pull from a cloud runner."""
    global _SESSION
    if _SESSION is None:
        import requests
        s = requests.Session()
        s.headers.update({"User-Agent": _UA, "Accept": "application/json, text/plain, */*"})
        _SESSION = s
    return _SESSION


def _yf(ticker):
    import yfinance as yf
    try:
        return yf.Ticker(ticker, session=_session())
    except TypeError:                       # some yfinance versions don't accept session=
        return yf.Ticker(ticker)


def _expiries(ticker):
    return list(_yf(ticker).options or [])


def _chain(ticker, expiry):
    oc = _yf(ticker).option_chain(expiry)
    return oc.calls, oc.puts


def _spot(ticker):
    t = _yf(ticker)
    fi = getattr(t, "fast_info", None)
    if fi is not None:
        for k in ("last_price", "lastPrice"):
            try:
                v = fi[k] if not hasattr(fi, "get") else fi.get(k)
            except (KeyError, TypeError):
                v = None
            if v:
                return float(v)
    hist = t.history(period="1d")
    if hist is not None and len(hist):
        return float(hist["Close"].iloc[-1])
    return None


# ------------------------------------------------------------ pure maths
def _pairs(df, lo, hi):
    """(moneyness, iv) pairs from an option DataFrame, restricted to a moneyness
    band and to positive, present IVs. Tolerant of missing columns."""
    if df is None or not len(df) or "strike" not in df or "impliedVolatility" not in df:
        return []
    out = []
    for strike, iv in zip(df["strike"], df["impliedVolatility"]):
        try:
            s = float(strike); v = float(iv)
        except (TypeError, ValueError):
            continue
        if s <= 0 or v is None or v <= 0 or v != v:      # v!=v catches NaN
            continue
        out.append((s, v))
    return out


def _interp(points, target, spot):
    """Linear-interpolate IV at a target moneyness. points are (strike, iv).
    Requires the target to be bracketed by available strikes (no wild
    extrapolation); returns None otherwise."""
    curve = sorted((s / spot, v) for s, v in points)
    if len(curve) < 2:
        return None
    xs = [m for m, _ in curve]
    if target < xs[0] or target > xs[-1]:
        return None
    ys = [v for _, v in curve]
    # manual linear interpolation (no numpy dependency)
    for i in range(1, len(xs)):
        if xs[i] >= target:
            x0, y0, x1, y1 = xs[i - 1], ys[i - 1], xs[i], ys[i]
            if x1 == x0:
                return y1
            return y0 + (y1 - y0) * (target - x0) / (x1 - x0)
    return ys[-1]


def compute_skew(spot, calls, puts, m_put=M_PUT, m_atm=M_ATM, m_call=M_CALL):
    """From spot and the calls/puts frames, interpolate IV at the put, ATM and
    call moneyness levels and derive the skew measures. Uses OTM wings: puts below
    spot for the downside, calls above spot for the upside, both near spot for ATM.
    Any measure that can't be computed is None; never raises."""
    empty = {"atm_iv": None, "put_iv": None, "call_iv": None,
             "put_skew": None, "risk_reversal": None}
    if not spot or spot <= 0:
        return empty

    put_pts = _pairs(puts, None, None)
    call_pts = _pairs(calls, None, None)
    # OTM wings by moneyness (a little overlap around ATM is fine)
    put_side = [(s, v) for s, v in put_pts if s <= spot * 1.02]
    call_side = [(s, v) for s, v in call_pts if s >= spot * 0.98]
    atm_side = [(s, v) for s, v in (put_pts + call_pts)
                if spot * 0.95 <= s <= spot * 1.05]

    put_iv = _interp(put_side, m_put, spot)
    call_iv = _interp(call_side, m_call, spot)
    atm_iv = _interp(atm_side, m_atm, spot)

    put_skew = (put_iv - atm_iv) if (put_iv is not None and atm_iv is not None) else None
    risk_reversal = (put_iv - call_iv) if (put_iv is not None and call_iv is not None) else None
    return {"atm_iv": atm_iv, "put_iv": put_iv, "call_iv": call_iv,
            "put_skew": put_skew, "risk_reversal": risk_reversal}


# ------------------------------------------------------------ orchestration seam
def _pick_expiry(expiries, target_dte, today):
    """Choose the listed expiry whose days-to-expiry is closest to target."""
    best, best_gap, best_dte = None, None, None
    for e in expiries:
        try:
            ed = datetime.strptime(e, "%Y-%m-%d").date()
        except (TypeError, ValueError):
            continue
        dte = (ed - today).days
        if dte < 1:                       # skip expired / same-day
            continue
        gap = abs(dte - target_dte)
        if best_gap is None or gap < best_gap:
            best, best_gap, best_dte = e, gap, dte
    return best, best_dte


def fetch_skew(ticker_id, ticker, target_dte=30, capture_date=None,
               m_put=M_PUT, m_atm=M_ATM, m_call=M_CALL, retries=3, pace=2.0) -> SkewResult:
    """Capture one ticker's current skew, retrying with backoff. Never raises; the
    outcome is always in the returned SkewResult. Empty expiries/spot are treated as
    retryable because from a cloud IP they're usually a silent Yahoo rate-limit."""
    capture_date = capture_date or date.today()
    last = None
    for attempt in range(max(1, retries)):
        try:
            expiries = _expiries(ticker)
            if not expiries:
                last = SkewResult(ticker_id, ticker, capture_date, status="empty",
                                  error="no expiries listed (possible rate-limit)")
                time.sleep(pace * (2 ** attempt)); continue
            expiry, dte = _pick_expiry(expiries, target_dte, capture_date)
            if expiry is None:
                return SkewResult(ticker_id, ticker, capture_date, status="empty",
                                  error="no future expiry")
            spot = _spot(ticker)
            if not spot:
                last = SkewResult(ticker_id, ticker, capture_date, expiry=expiry, dte=dte,
                                  status="empty", error="no spot price (possible rate-limit)")
                time.sleep(pace * (2 ** attempt)); continue
            calls, puts = _chain(ticker, expiry)
            measures = compute_skew(spot, calls, puts, m_put, m_atm, m_call)
            status = "ok" if (measures.get("put_skew") is not None
                              or measures.get("atm_iv") is not None) else "empty"
            return SkewResult(ticker_id, ticker, capture_date, expiry, dte, spot,
                              measures=measures, status=status,
                              error=None if status == "ok" else "insufficient strikes")
        except Exception as e:                # noqa: BLE001 - any yfinance hiccup
            last = SkewResult(ticker_id, ticker, capture_date, status="error", error=str(e))
            time.sleep(pace * (2 ** attempt))
    return last or SkewResult(ticker_id, ticker, capture_date, status="error", error="unknown")
