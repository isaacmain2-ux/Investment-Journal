"""Tests for src/extract/sec_client.py - network mocked, so fully offline."""
import datetime as dt
from src.extract import sec_client


class _Resp:
    def __init__(self, payload, status=200): self._p=payload; self.status_code=status
    def json(self): return self._p
    def raise_for_status(self):
        if self.status_code>=400:
            import requests; raise requests.HTTPError(str(self.status_code))


def _companyfacts():
    return {"cik": 320193, "entityName": "Apple Inc.", "facts": {"us-gaap": {
        "Revenues": {"units": {"USD": [
            {"end":"2023-09-30","val":383285000000,"fy":2023,"fp":"FY","form":"10-K","filed":"2023-11-03"},
            {"end":"2022-09-30","val":394328000000,"fy":2022,"fp":"FY","form":"10-K","filed":"2022-10-28"},
            {"end":"2023-06-30","val":81797000000,"fy":2023,"fp":"Q3","form":"10-Q","filed":"2023-08-04"},
            {"end":"2021-09-30","val":365000000000,"fy":2021,"fp":"FY","form":"8-K","filed":"2021-10-01"}]}},
        "NetIncomeLoss": {"units": {"USD": [
            {"end":"2023-09-30","val":96995000000,"fy":2023,"fp":"FY","form":"10-K","filed":"2023-11-03"}]}},
        "EarningsPerShareDiluted": {"units": {"USD/shares": [
            {"end":"2023-09-30","val":6.13,"fy":2023,"fp":"FY","form":"10-K","filed":"2023-11-03"}]}},
        "Assets": {"units": {"USD": [
            {"end":"2023-09-30","val":352583000000,"fy":2023,"fp":"FY","form":"10-K","filed":"2023-11-03"}]}},
        "CommonStockSharesOutstanding": {"units": {"shares": [
            {"end":"2023-09-30","val":15550061000,"fy":2023,"fp":"FY","form":"10-K","filed":"2023-11-03"}]}},
    }}}


def test_extract_facts_shapes_rows():
    rows = sec_client.extract_facts(_companyfacts(), ticker="AAPL")
    rev = [r for r in rows if r["metric"]=="revenue"]
    # 8-K form dropped; 3 valid revenue rows (2 annual + 1 quarterly)
    assert len(rev)==3
    r0 = next(r for r in rev if r["period_end"]==dt.date(2023,9,30))
    assert r0["ticker"]=="AAPL" and r0["cik"]==320193 and r0["value"]==383285000000
    assert r0["filed_date"]==dt.date(2023,11,3) and r0["fiscal_period"]=="FY" and r0["form"]=="10-K"
    assert r0["xbrl_tag"]=="Revenues"
    metrics = {r["metric"] for r in rows}
    assert {"revenue","net_income","eps_diluted","assets","shares"} <= metrics


def test_extract_facts_priority_tag_fallback():
    cf = {"cik": 1, "facts": {"us-gaap": {
        "RevenueFromContractWithCustomerExcludingAssessedTax": {"units": {"USD": [
            {"end":"2023-12-31","val":500,"fy":2023,"fp":"FY","form":"10-K","filed":"2024-02-01"}]}}}}}
    rows = sec_client.extract_facts(cf, ticker="X")
    rev = [r for r in rows if r["metric"]=="revenue"]
    assert len(rev)==1 and rev[0]["xbrl_tag"]=="RevenueFromContractWithCustomerExcludingAssessedTax"


def test_extract_facts_empty_is_safe():
    assert sec_client.extract_facts({}, ticker="X") == []
    assert sec_client.extract_facts({"facts": {"us-gaap": {}}}, ticker="X") == []


def test_load_cik_map(monkeypatch):
    payload = {"0": {"cik_str": 320193, "ticker": "AAPL", "title": "Apple Inc."},
               "1": {"cik_str": 789019, "ticker": "MSFT", "title": "Microsoft"}}
    monkeypatch.setattr(sec_client, "_get", lambda u, ua, timeout=30: _Resp(payload))
    m = sec_client.load_cik_map("UA/1.0 test@x.com")
    assert m["AAPL"]=="0000320193" and m["MSFT"]=="0000789019"


def test_fetch_fundamentals_ok(monkeypatch):
    monkeypatch.setattr(sec_client, "_get", lambda u, ua, timeout=30: _Resp(_companyfacts()))
    monkeypatch.setattr(sec_client.time, "sleep", lambda s: None)
    res = sec_client.fetch_fundamentals("AAPL", "0000320193", "UA/1.0 test@x.com")
    assert res.status=="ok" and len(res.rows)>5 and res.ticker=="AAPL"


def test_fetch_fundamentals_404(monkeypatch):
    monkeypatch.setattr(sec_client, "_get", lambda u, ua, timeout=30: _Resp({}, status=404))
    monkeypatch.setattr(sec_client.time, "sleep", lambda s: None)
    res = sec_client.fetch_fundamentals("ZZZ", "0000000001", "UA/1.0 test@x.com")
    assert res.status=="empty" and "404" in res.error


def test_shares_prefers_dei_cover_page_count():
    cf = {"cik": 1, "facts": {
        "dei": {"EntityCommonStockSharesOutstanding": {"units": {"shares": [
            {"end": "2023-09-30", "val": 15_500_000_000, "fy": 2023, "fp": "FY",
             "form": "10-K", "filed": "2023-11-03"}]}}},
        "us-gaap": {"CommonStockSharesOutstanding": {"units": {"shares": [
            {"end": "2023-09-30", "val": 125, "fy": 2023, "fp": "FY",
             "form": "10-K", "filed": "2023-11-03"}]}}}}}
    rows = sec_client.extract_facts(cf, ticker="BKR")
    shares = [r for r in rows if r["metric"] == "shares"]
    assert len(shares) == 1
    assert shares[0]["value"] == 15_500_000_000        # dei wins over the broken us-gaap 125
    assert shares[0]["xbrl_tag"] == "EntityCommonStockSharesOutstanding"
