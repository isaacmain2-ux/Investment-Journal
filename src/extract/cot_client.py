"""
CFTC Commitments of Traders (Traders in Financial Futures) client.

Reads the free CFTC Socrata SODA API (no key required). All network access is
isolated behind one function (`_get`), so the parsing, schema probe, and error
handling test offline. Numeric fields arrive as strings and are coerced here;
each row is reduced to the handful of positions we actually use.

The exact Socrata column names are pinned by `probe_schema` (a $limit=1 request):
if the dataset ever renames a field, the probe raises a clear error rather than
letting a silent rename produce wrong numbers.
"""
from __future__ import annotations

import time
from datetime import date, datetime

import requests

BASE = "https://publicreporting.cftc.gov/resource"
DEFAULT_DATASET = "yw9f-hn96"          # TFF Combined

# Socrata column -> tidy key. These are the fields the warehouse consumes.
# NB: the live yw9f-hn96 dataset is inconsistent - dealer fields keep the _all
# suffix, but lev_money / asset_mgr / other_rept drop it. Confirmed via the probe.
FIELDS = {
    "open_interest":  "open_interest_all",
    "lev_long":       "lev_money_positions_long",
    "lev_short":      "lev_money_positions_short",
    "lev_spread":     "lev_money_positions_spread",
    "am_long":        "asset_mgr_positions_long",
    "am_short":       "asset_mgr_positions_short",
    "dealer_long":    "dealer_positions_long_all",
    "dealer_short":   "dealer_positions_short_all",
}
_NAME = "market_and_exchange_names"
_DATE = "report_date_as_yyyy_mm_dd"
_FUTCOMB = "futonly_or_combined"
# every field we map must exist, so any future rename fails loudly at the probe
REQUIRED_COLS = {_NAME, _DATE, *FIELDS.values()}


class CotResult:
    def __init__(self, market_id, match, rows=None, status="ok", error=None,
                 http_status=None, raw=None, chosen_market=None, dropped_markets=None):
        self.market_id = market_id
        self.match = match
        self.rows = rows if rows is not None else []
        self.status = status            # ok | empty | error
        self.error = error
        self.http_status = http_status
        self.raw = raw                  # exact response bytes (for landing)
        self.chosen_market = chosen_market       # the contract kept when a pattern matched several
        self.dropped_markets = dropped_markets or []

    @property
    def n_rows(self):
        return len(self.rows)


# ------------------------------------------------------------------ network seam
def _get(url, params, headers=None, timeout=45):
    """The single network call - a thin wrapper over requests.get so tests can
    replace it with a fake. Every Socrata request flows through here."""
    return requests.get(url, params=params, headers=headers or {}, timeout=timeout)


# ------------------------------------------------------------------ helpers
def _to_int(v):
    if v is None or v == "":
        return None
    try:
        return int(float(v))
    except (ValueError, TypeError):
        return None


def _to_date(v):
    if not v:
        return None
    try:
        return datetime.fromisoformat(str(v).replace("Z", "")).date()
    except ValueError:
        try:
            return datetime.strptime(str(v)[:10], "%Y-%m-%d").date()
        except ValueError:
            return None


def _tidy(raw_row: dict, market_id: str) -> dict:
    out = {"market_id": market_id,
           "market": raw_row.get(_NAME),
           "report_date": _to_date(raw_row.get(_DATE))}
    for key, col in FIELDS.items():
        out[key] = _to_int(raw_row.get(col))
    return out


def _pick_primary(rows):
    """A LIKE pattern can match several contracts - e.g. 'EURO FX' also matches the
    cross-rates 'EURO FX/BRITISH POUND XRATE' etc. Keep only the primary contract,
    the one with the largest open interest, so a market_id maps to a single
    consistent series. Returns (kept_rows, chosen_name, dropped_names)."""
    names = {r["market"] for r in rows if r.get("market")}
    if len(names) <= 1:
        return rows, (next(iter(names)) if names else None), []
    max_oi = {}
    for r in rows:
        m, oi = r.get("market"), (r.get("open_interest") or 0)
        if m is not None and oi > max_oi.get(m, -1):
            max_oi[m] = oi
    primary = max(max_oi, key=max_oi.get)
    kept = [r for r in rows if r.get("market") == primary]
    return kept, primary, sorted(names - {primary})


def _like_clause(match: str) -> str:
    safe = match.replace("'", "''")
    return f"upper({_NAME}) like upper('%{safe}%')"


# ------------------------------------------------------------------ public API
def probe_schema(dataset=DEFAULT_DATASET, base=BASE, app_token=None) -> set:
    """Fetch one row and assert the columns we rely on are present. Returns the
    full column set; raises ValueError listing what's available if any are missing."""
    url = f"{base}/{dataset}.json"
    headers = {"X-App-Token": app_token} if app_token else {}
    resp = _get(url, {"$limit": 1}, headers)
    resp.raise_for_status()
    data = resp.json()
    cols = set(data[0].keys()) if data else set()
    missing = REQUIRED_COLS - cols
    if missing:
        raise ValueError(f"CFTC dataset {dataset} missing expected columns {sorted(missing)}; "
                         f"available: {sorted(cols)}")
    return cols


def list_markets(keyword, dataset=DEFAULT_DATASET, base=BASE, app_token=None, limit=50000) -> list[str]:
    """Distinct market names matching a keyword - used by the preflight so a user
    can confirm/correct the manifest `match` patterns against the real names."""
    url = f"{base}/{dataset}.json"
    headers = {"X-App-Token": app_token} if app_token else {}
    params = {"$select": f"distinct {_NAME}", "$where": _like_clause(keyword), "$limit": limit}
    resp = _get(url, params, headers)
    resp.raise_for_status()
    return sorted(r.get(_NAME) for r in resp.json() if r.get(_NAME))


def fetch_market(market_id, match, dataset=DEFAULT_DATASET, base=BASE,
                 since=None, app_token=None, retries=3, pace=0.3, limit=50000,
                 combined_only=True) -> CotResult:
    """All weekly rows for a market (by LIKE pattern), optionally since a date.
    When combined_only is set, restrict to the combined futures+options rows -
    the yw9f-hn96 dataset carries both cuts, and without this each week would
    appear twice (futures-only and combined) and collide on load.
    Never raises; the outcome is always in the returned CotResult."""
    url = f"{base}/{dataset}.json"
    headers = {"X-App-Token": app_token} if app_token else {}
    where = _like_clause(match)
    if combined_only:
        where += f" AND upper({_FUTCOMB}) like upper('%comb%')"
    if since:
        where += f" AND {_DATE} > '{since}T00:00:00'"
    params = {"$where": where, "$order": _DATE, "$limit": limit}

    last_err = None
    for attempt in range(retries):
        try:
            resp = _get(url, params, headers)
            if resp.status_code == 200:
                data = resp.json()
                rows = [_tidy(r, market_id) for r in data if r.get(_DATE)]
                rows, chosen, dropped = _pick_primary(rows)
                status = "ok" if rows else "empty"
                return CotResult(market_id, match, rows=rows, status=status,
                                 http_status=200, raw=resp.content,
                                 chosen_market=chosen, dropped_markets=dropped)
            if resp.status_code in (429, 500, 502, 503):
                last_err = f"http {resp.status_code}"
                time.sleep(pace * (2 ** attempt))
                continue
            return CotResult(market_id, match, status="error", http_status=resp.status_code,
                             error=f"http {resp.status_code}")
        except requests.RequestException as e:      # network hiccup
            last_err = str(e)
            time.sleep(pace * (2 ** attempt))
    return CotResult(market_id, match, status="error", error=f"{last_err} after {retries} attempts")
