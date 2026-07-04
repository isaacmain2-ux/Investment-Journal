"""
Minimal FRED API client: fetch one series as a tidy DataFrame.

Design notes
------------
* The single network call lives in `_http_get`, so tests can mock it and run
  offline. Nothing else in the codebase talks to the network.
* Handles the FRED rate limit (throttle), transient-error retries with
  backoff, missing values (FRED encodes these as "."), and invalid series ids
  (returns an empty result WITH a reason instead of raising — so one bad id
  never crashes a 60-series run).
"""
from __future__ import annotations

import logging
import time

import pandas as pd
import requests

FRED_URL = "https://api.stlouisfed.org/fred/series/observations"
_MIN_INTERVAL = 60.0 / 110.0     # stay under FRED's ~120 requests/minute limit
_last_call = [0.0]               # module-level throttle timestamp

log = logging.getLogger(__name__)


class FetchResult:
    """The outcome of one series fetch."""

    def __init__(self, series_id: str, df: pd.DataFrame | None = None,
                 status: str = "ok", error: str | None = None):
        self.series_id = series_id
        self.df = df if df is not None else pd.DataFrame(columns=["obs_date", "value"])
        self.status = status          # "ok" | "empty" | "error"
        self.error = error

    @property
    def n_obs(self) -> int:
        return len(self.df)

    def __repr__(self) -> str:
        return f"FetchResult({self.series_id}, status={self.status}, n_obs={self.n_obs})"


def _throttle() -> None:
    """Sleep just enough to stay under the rate limit."""
    wait = _MIN_INTERVAL - (time.monotonic() - _last_call[0])
    if wait > 0:
        time.sleep(wait)
    _last_call[0] = time.monotonic()


def _http_get(params: dict) -> requests.Response:
    """The ONLY network call in the project. Mock this in tests."""
    return requests.get(FRED_URL, params=params, timeout=30)


def fetch_series(series_id: str, api_key: str,
                 start: str = "2005-01-01", retries: int = 3) -> FetchResult:
    """Fetch one FRED series from `start` to today. Never raises for a bad id
    or a network hiccup — returns a FetchResult whose `status`/`error` say what
    happened, so the caller can log and carry on."""
    params = {
        "series_id": series_id,
        "api_key": api_key,
        "file_type": "json",
        "observation_start": start,
    }
    for attempt in range(1, retries + 1):
        _throttle()
        try:
            resp = _http_get(params)
        except requests.RequestException as e:
            if attempt == retries:
                return FetchResult(series_id, status="error", error=f"network: {e}")
            time.sleep(2 * attempt)
            continue

        code = resp.status_code
        if code == 200:
            return _parse(series_id, resp.json())
        if code == 400:
            # FRED returns 400 for an unknown/invalid series id — not retryable.
            return FetchResult(series_id, status="error",
                               error=f"bad id (400): {_error_message(resp)}")
        if code == 429 or 500 <= code < 600:
            if attempt == retries:
                return FetchResult(series_id, status="error",
                                   error=f"http {code} after {retries} attempts")
            time.sleep(2 * attempt)
            continue
        return FetchResult(series_id, status="error", error=f"http {code}")

    return FetchResult(series_id, status="error", error="exhausted retries")


def _error_message(resp: requests.Response) -> str:
    try:
        return resp.json().get("error_message", resp.text[:120])
    except Exception:
        return resp.text[:120]


def _parse(series_id: str, payload: dict) -> FetchResult:
    rows = []
    for o in payload.get("observations", []):
        v = o.get("value", ".")
        if v in (".", "", None):        # FRED uses "." for missing values
            continue
        try:
            rows.append((o["date"], float(v)))
        except (ValueError, KeyError):
            continue
    if not rows:
        return FetchResult(series_id, status="empty")
    df = pd.DataFrame(rows, columns=["obs_date", "value"])
    df["obs_date"] = pd.to_datetime(df["obs_date"]).dt.date
    return FetchResult(series_id, df=df, status="ok")
