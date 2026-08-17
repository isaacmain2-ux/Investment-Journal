"""
SEC EDGAR client — free, official US company fundamentals from XBRL.

Two public endpoints, no key:
  * company_tickers.json  -> ticker -> CIK map (resolve symbols to filers)
  * companyfacts/CIK{10}.json -> every XBRL fact a company has ever filed

All network access sits behind one seam (`_get`); the parsing (`extract_facts`) is a
pure function, so the hard part — turning SEC's deeply-nested, tag-heterogeneous XBRL
into tidy per-period rows — is fully unit-tested offline.

Two SEC rules the client honours: a descriptive **User-Agent with a contact** (else
you're blocked), and a ~10 requests/second cap (a small pace between calls).

Point-in-time is preserved: every row keeps the SEC `filed` date, so a metric is only
"known" from the day its filing hit EDGAR — the same available-from discipline the
CFTC layer uses.
"""
from __future__ import annotations

import time
from datetime import datetime

import requests

TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
FACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json"
_MIN_INTERVAL = 0.12                       # stay under SEC's 10 req/s

# metric -> (ordered list of (taxonomy, tag) candidates, unit). First candidate present
# wins. Shares deliberately prefers the dei cover-page count - the reliable one for
# market cap - over the us-gaap tags, which are inconsistent (weighted-average, class
# shares, thousands) and were producing broken share counts.
CONCEPTS = {
    "revenue":          ([("us-gaap", "Revenues"),
                          ("us-gaap", "RevenueFromContractWithCustomerExcludingAssessedTax"),
                          ("us-gaap", "SalesRevenueNet")], "USD"),
    "net_income":       ([("us-gaap", "NetIncomeLoss")], "USD"),
    "gross_profit":     ([("us-gaap", "GrossProfit")], "USD"),
    "operating_income": ([("us-gaap", "OperatingIncomeLoss")], "USD"),
    "eps_diluted":      ([("us-gaap", "EarningsPerShareDiluted")], "USD/shares"),
    "eps_basic":        ([("us-gaap", "EarningsPerShareBasic")], "USD/shares"),
    "assets":           ([("us-gaap", "Assets")], "USD"),
    "equity":           ([("us-gaap", "StockholdersEquity")], "USD"),
    "shares":           ([("dei", "EntityCommonStockSharesOutstanding"),
                          ("us-gaap", "CommonStockSharesOutstanding"),
                          ("us-gaap", "WeightedAverageNumberOfDilutedSharesOutstanding")], "shares"),
    "op_cash_flow":     ([("us-gaap", "NetCashProvidedByUsedInOperatingActivities")], "USD"),
    "capex":            ([("us-gaap", "PaymentsToAcquirePropertyPlantAndEquipment")], "USD"),
    "long_term_debt":   ([("us-gaap", "LongTermDebtNoncurrent"),
                          ("us-gaap", "LongTermDebt")], "USD"),
}

_FORMS = {"10-K", "10-Q", "10-K/A", "10-Q/A", "20-F"}


class SecResult:
    def __init__(self, ticker, cik=None, rows=None, status="ok", error=None):
        self.ticker = ticker
        self.cik = cik
        self.rows = rows if rows is not None else []
        self.status = status                # ok | empty | error
        self.error = error


# ------------------------------------------------------------------ network seam
def _get(url, user_agent, timeout=30):
    return requests.get(url, headers={"User-Agent": user_agent,
                                      "Accept-Encoding": "gzip, deflate"}, timeout=timeout)


def _to_date(v):
    try:
        return datetime.strptime(str(v)[:10], "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return None


# ------------------------------------------------------------------ public API
def load_cik_map(user_agent) -> dict:
    """ticker (upper) -> 10-digit zero-padded CIK string."""
    resp = _get(TICKERS_URL, user_agent)
    resp.raise_for_status()
    data = resp.json()
    out = {}
    for row in data.values():
        t = str(row.get("ticker", "")).upper()
        cik = str(row.get("cik_str", "")).zfill(10)
        if t:
            out[t] = cik
    return out


def extract_facts(companyfacts: dict, ticker=None, concepts=CONCEPTS) -> list[dict]:
    """Turn a companyfacts JSON into tidy rows, one per (metric, reporting period).
    Pure function - the heart of the client, fully testable without a network."""
    facts = (companyfacts or {}).get("facts", {})
    cik = companyfacts.get("cik")
    out = []
    for metric, (candidates, unit) in concepts.items():
        node = tag = None
        for taxonomy, cand in candidates:               # first candidate present wins
            block = facts.get(taxonomy, {})
            if cand in block:
                node, tag = block[cand], cand
                break
        if node is None:
            continue
        for f in node.get("units", {}).get(unit, []):
            if f.get("form") not in _FORMS:
                continue
            end = _to_date(f.get("end"))
            if end is None:
                continue
            out.append({
                "ticker": ticker, "cik": cik, "metric": metric, "xbrl_tag": tag,
                "period_end": end, "fiscal_year": f.get("fy"), "fiscal_period": f.get("fp"),
                "form": f.get("form"), "filed_date": _to_date(f.get("filed")),
                "unit": unit, "value": f.get("val"),
            })
    return out


def fetch_fundamentals(ticker, cik, user_agent, retries=3, pace=0.6) -> SecResult:
    """Fetch + parse one company's fundamentals. Never raises."""
    url = FACTS_URL.format(cik=str(cik).zfill(10))
    last = None
    for attempt in range(retries):
        try:
            resp = _get(url, user_agent)
            if resp.status_code == 200:
                rows = extract_facts(resp.json(), ticker=ticker)
                time.sleep(_MIN_INTERVAL)
                return SecResult(ticker, cik, rows=rows, status="ok" if rows else "empty",
                                 error=None if rows else "no facts extracted")
            if resp.status_code == 404:
                return SecResult(ticker, cik, status="empty", error="no companyfacts (404)")
            last = f"http {resp.status_code}"
        except requests.RequestException as e:
            last = str(e)
        time.sleep(pace * (2 ** attempt))
    return SecResult(ticker, cik, status="error", error=f"{last} after {retries} attempts")
