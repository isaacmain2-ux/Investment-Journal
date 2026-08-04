"""Tests for src/extract/cot_client.py - the network is mocked, so offline."""
import json
from src.extract import cot_client


class _Resp:
    def __init__(self, payload, status=200):
        self._p = payload; self.status_code = status; self.content = json.dumps(payload).encode()
    def json(self): return self._p
    def raise_for_status(self):
        if self.status_code >= 400:
            import requests; raise requests.HTTPError(str(self.status_code))


def _row(name="E-MINI S&P 500 STOCK INDEX - CHICAGO MERCANTILE EXCHANGE", d="2026-07-28T00:00:00.000",
         oi="2500000", ll="180000", ls="240000", lsp="30000"):
    return {"market_and_exchange_names": name, "report_date_as_yyyy_mm_dd": d,
            "open_interest_all": oi, "lev_money_positions_long": ll,
            "lev_money_positions_short": ls, "lev_money_positions_spread": lsp,
            "asset_mgr_positions_long": "900000", "asset_mgr_positions_short": "300000",
            "dealer_positions_long_all": "50000", "dealer_positions_short_all": "70000",
            "futonly_or_combined": "Combined"}


def test_fetch_parses_and_coerces(monkeypatch):
    captured = {}
    def fake_get(url, params, headers=None, timeout=45):
        captured["params"] = params; return _Resp([_row(), _row(d="2026-08-04T00:00:00.000")])
    monkeypatch.setattr(cot_client, "_get", fake_get)
    res = cot_client.fetch_market("sp500", "E-MINI S&P 500 STOCK INDEX")
    assert res.status == "ok" and res.n_rows == 2
    r0 = res.rows[0]
    assert r0["market_id"] == "sp500"
    assert r0["open_interest"] == 2500000 and isinstance(r0["open_interest"], int)  # string -> int
    assert r0["lev_long"] == 180000 and r0["lev_short"] == 240000
    import datetime as dt
    assert r0["report_date"] == dt.date(2026, 7, 28)
    assert "like" in captured["params"]["$where"].lower()


def test_since_filter_added(monkeypatch):
    captured = {}
    def fake_get(url, params, headers=None, timeout=45):
        captured["where"] = params["$where"]; return _Resp([_row()])
    monkeypatch.setattr(cot_client, "_get", fake_get)
    cot_client.fetch_market("vix", "VIX FUTURES", since="2026-01-01")
    assert "2026-01-01" in captured["where"] and "report_date_as_yyyy_mm_dd >" in captured["where"]


def test_empty_status(monkeypatch):
    monkeypatch.setattr(cot_client, "_get", lambda u, p, headers=None, timeout=45: _Resp([]))
    assert cot_client.fetch_market("x", "NOTHING").status == "empty"


def test_error_status_non_retryable(monkeypatch):
    monkeypatch.setattr(cot_client, "_get", lambda u, p, headers=None, timeout=45: _Resp([], status=404))
    res = cot_client.fetch_market("x", "Y")
    assert res.status == "error" and res.http_status == 404


def test_probe_schema_ok_and_missing(monkeypatch):
    monkeypatch.setattr(cot_client, "_get", lambda u, p, headers=None, timeout=45: _Resp([_row()]))
    cols = cot_client.probe_schema()
    assert cot_client._NAME in cols
    # a dataset missing a required column raises
    monkeypatch.setattr(cot_client, "_get",
                        lambda u, p, headers=None, timeout=45: _Resp([{"market_and_exchange_names": "x"}]))
    import pytest
    with pytest.raises(ValueError):
        cot_client.probe_schema()


def test_list_markets(monkeypatch):
    monkeypatch.setattr(cot_client, "_get", lambda u, p, headers=None, timeout=45: _Resp(
        [{"market_and_exchange_names": "B"}, {"market_and_exchange_names": "A"}]))
    assert cot_client.list_markets("TREASURY") == ["A", "B"]


def test_combined_filter_toggles(monkeypatch):
    captured = {}
    def fake_get(url, params, headers=None, timeout=45):
        captured["where"] = params["$where"]; return _Resp([_row()])
    monkeypatch.setattr(cot_client, "_get", fake_get)
    cot_client.fetch_market("sp500", "E-MINI S&P 500", combined_only=True)
    assert "futonly_or_combined" in captured["where"]
    cot_client.fetch_market("sp500", "E-MINI S&P 500", combined_only=False)
    assert "futonly_or_combined" not in captured["where"]


def test_pick_primary_contract(monkeypatch):
    # 'EURO FX' pattern also matches a cross-rate; the plain contract has more OI
    def fake_get(url, params, headers=None, timeout=45):
        return _Resp([
            _row(name="EURO FX - CHICAGO MERCANTILE EXCHANGE", oi="600000"),
            _row(name="EURO FX/BRITISH POUND XRATE - CHICAGO MERCANTILE EXCHANGE", oi="4000"),
        ])
    monkeypatch.setattr(cot_client, "_get", fake_get)
    res = cot_client.fetch_market("eur", "EURO FX")
    assert res.n_rows == 1                                   # only the primary kept
    assert res.chosen_market.startswith("EURO FX - ")
    assert any("XRATE" in d for d in res.dropped_markets)    # cross-rate dropped
