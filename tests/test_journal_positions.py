"""Tests for the pure average-cost/mark-to-market functions in
src/transform/journal_positions.py. No database - pandas only, so these run
regardless of whether duckdb is installed (see that module's docstring for why
this logic is Python rather than SQL)."""
import datetime as dt

import pandas as pd
import pytest

from src.transform import journal_positions as jp


def _trade(ticker="NVDA", d="2026-08-01", action="BUY", qty=10, price=100.0, fees=0.0,
           portfolio="main", **extra):
    row = {"portfolio": portfolio, "ticker": ticker, "trade_date": d, "action": action,
           "quantity": qty, "price": price, "fees": fees, "conviction": "high",
           "timeframe": "months", "catalyst": "capex", "thesis": "scan snapshot",
           "tags": "ai", "trade_id": f"{d}-{ticker}-01"}
    row.update(extra)
    return row


# ------------------------------------------------------------------ _walk_trades / compute_positions
def test_single_buy():
    trades = pd.DataFrame([_trade()])
    pos = jp.compute_positions(trades)
    assert len(pos) == 1
    r = pos.iloc[0]
    assert r["ticker"] == "NVDA" and r["status"] == "OPEN"
    assert r["quantity_open"] == 10.0 and r["avg_cost"] == 100.0
    assert r["realized_pnl_cum"] == 0.0


def test_average_cost_on_add():
    trades = pd.DataFrame([
        _trade(d="2026-08-01", action="BUY", qty=10, price=100.0),
        _trade(d="2026-08-02", action="BUY", qty=5, price=110.0),
    ])
    pos = jp.compute_positions(trades)
    r = pos.iloc[0]
    assert r["quantity_open"] == 15.0
    assert r["avg_cost"] == pytest.approx((100 * 10 + 110 * 5) / 15)


def test_partial_sell_realized_pnl_matches_hand_calc():
    trades = pd.DataFrame([
        _trade(d="2026-08-01", action="BUY", qty=10, price=100.0),
        _trade(d="2026-08-02", action="BUY", qty=5, price=110.0),
        _trade(d="2026-08-03", action="SELL", qty=6, price=120.0),
    ])
    pos = jp.compute_positions(trades)
    r = pos.iloc[0]
    avg_cost = (100 * 10 + 110 * 5) / 15
    expected_realized = (120 - avg_cost) * 6
    assert r["quantity_open"] == 9.0
    assert r["avg_cost"] == pytest.approx(avg_cost)          # unchanged by a sell
    assert r["realized_pnl_cum"] == pytest.approx(expected_realized)
    assert r["status"] == "OPEN"


def test_full_sell_closes_position_and_resets_avg_cost():
    trades = pd.DataFrame([
        _trade(d="2026-08-01", action="BUY", qty=10, price=100.0),
        _trade(d="2026-08-02", action="SELL", qty=10, price=120.0),
    ])
    pos = jp.compute_positions(trades)
    r = pos.iloc[0]
    assert r["quantity_open"] == 0.0
    assert r["avg_cost"] == 0.0
    assert r["realized_pnl_cum"] == pytest.approx(200.0)
    assert r["status"] == "CLOSED"


def test_oversell_is_clamped_not_negative():
    """Selling more than is held (a bad manual entry) clamps to the open quantity
    rather than going negative - defensive, since this is a hypothetical/paper book."""
    trades = pd.DataFrame([
        _trade(d="2026-08-01", action="BUY", qty=5, price=100.0),
        _trade(d="2026-08-02", action="SELL", qty=20, price=110.0),
    ])
    pos = jp.compute_positions(trades)
    r = pos.iloc[0]
    assert r["quantity_open"] == 0.0
    assert r["realized_pnl_cum"] == pytest.approx((110 - 100) * 5)


def test_fees_reduce_avg_cost_gain_and_realized_pnl():
    trades = pd.DataFrame([
        _trade(d="2026-08-01", action="BUY", qty=10, price=100.0, fees=10.0),
        _trade(d="2026-08-02", action="SELL", qty=10, price=110.0, fees=5.0),
    ])
    pos = jp.compute_positions(trades)
    r = pos.iloc[0]
    avg_cost = (100 * 10 + 10) / 10        # = 101.0
    assert r["avg_cost"] == pytest.approx(0.0)     # position fully closed -> reset
    expected_realized = (110 - avg_cost) * 10 - 5
    assert r["realized_pnl_cum"] == pytest.approx(expected_realized)


def test_multiple_tickers_and_portfolios_independent():
    trades = pd.DataFrame([
        _trade(ticker="NVDA", d="2026-08-01", action="BUY", qty=10, price=100.0),
        _trade(ticker="CAT", d="2026-08-01", action="BUY", qty=6, price=400.0),
        _trade(ticker="NVDA", d="2026-08-02", action="BUY", qty=1, price=105.0, portfolio="side"),
    ])
    pos = jp.compute_positions(trades).set_index(["portfolio", "ticker"])
    assert pos.loc[("main", "NVDA"), "quantity_open"] == 10.0
    assert pos.loc[("main", "CAT"), "quantity_open"] == 6.0
    assert pos.loc[("side", "NVDA"), "quantity_open"] == 1.0


def test_unrecognised_action_is_skipped_not_fatal():
    trades = pd.DataFrame([
        _trade(action="BUY", qty=10, price=100.0),
        _trade(d="2026-08-02", action="DIVIDEND", qty=1, price=1.0),
    ])
    pos = jp.compute_positions(trades)
    assert len(pos) == 1 and pos.iloc[0]["quantity_open"] == 10.0


def test_empty_and_none_input():
    assert len(jp.compute_positions(None)) == 0
    assert len(jp.compute_positions(pd.DataFrame())) == 0


# ------------------------------------------------------------------ compute_portfolio_value
def _prices():
    dates = ["2026-08-01", "2026-08-02", "2026-08-03", "2026-08-04"]
    closes = [100.0, 110.0, 90.0, 105.0]
    return pd.DataFrame({"ticker": ["NVDA"] * 4, "date": dates, "close": closes})


def test_portfolio_value_marks_open_position_daily():
    trades = pd.DataFrame([_trade(d="2026-08-01", action="BUY", qty=10, price=100.0)])
    val = jp.compute_portfolio_value(trades, _prices())
    v = val.set_index("date")
    assert v.loc[dt.date(2026, 8, 1), "market_value"] == pytest.approx(1000.0)
    assert v.loc[dt.date(2026, 8, 2), "market_value"] == pytest.approx(1100.0)
    assert v.loc[dt.date(2026, 8, 2), "unrealized_pnl"] == pytest.approx(100.0)
    assert v.loc[dt.date(2026, 8, 3), "market_value"] == pytest.approx(900.0)
    assert v.loc[dt.date(2026, 8, 3), "unrealized_pnl"] == pytest.approx(-100.0)


def test_portfolio_value_after_partial_sell_includes_realized():
    trades = pd.DataFrame([
        _trade(d="2026-08-01", action="BUY", qty=10, price=100.0),
        _trade(d="2026-08-04", action="SELL", qty=5, price=105.0),
    ])
    val = jp.compute_portfolio_value(trades, _prices())
    v = val.set_index("date")
    row = v.loc[dt.date(2026, 8, 4)]
    assert row["market_value"] == pytest.approx(5 * 105.0)
    assert row["cost_basis_open"] == pytest.approx(5 * 100.0)
    assert row["realized_pnl_cum"] == pytest.approx((105 - 100) * 5)
    assert row["total_value"] == pytest.approx(5 * 105.0 + 25.0)
    assert row["n_positions_open"] == 1


def test_no_mtm_before_first_trade():
    """Prices exist before the first BUY - those dates shouldn't produce a row."""
    trades = pd.DataFrame([_trade(d="2026-08-03", action="BUY", qty=10, price=90.0)])
    val = jp.compute_portfolio_value(trades, _prices())
    assert dt.date(2026, 8, 1) not in set(val["date"])
    assert dt.date(2026, 8, 2) not in set(val["date"])
    assert dt.date(2026, 8, 3) in set(val["date"])


def test_ticker_with_no_price_history_is_skipped_not_fatal():
    trades = pd.DataFrame([
        _trade(ticker="NVDA", d="2026-08-01", action="BUY", qty=10, price=100.0),
        _trade(ticker="ZZZZ", d="2026-08-01", action="BUY", qty=1, price=1.0),
    ])
    val = jp.compute_portfolio_value(trades, _prices())
    assert len(val) == 4       # only NVDA's 4 priced days; ZZZZ silently skipped
    assert val["n_positions_open"].eq(1).all()


def test_multiple_tickers_sum_by_date():
    prices = pd.concat([_prices(), pd.DataFrame({
        "ticker": ["CAT"] * 4, "date": _prices()["date"],
        "close": [400.0, 410.0, 395.0, 405.0]})], ignore_index=True)
    trades = pd.DataFrame([
        _trade(ticker="NVDA", d="2026-08-01", action="BUY", qty=10, price=100.0),
        _trade(ticker="CAT", d="2026-08-01", action="BUY", qty=6, price=400.0),
    ])
    val = jp.compute_portfolio_value(trades, prices).set_index("date")
    row = val.loc[dt.date(2026, 8, 2)]
    assert row["market_value"] == pytest.approx(10 * 110.0 + 6 * 410.0)
    assert row["n_positions_open"] == 2


def test_empty_and_none_input_portfolio_value():
    assert len(jp.compute_portfolio_value(None, _prices())) == 0
    assert len(jp.compute_portfolio_value(pd.DataFrame([_trade()]), None)) == 0
    assert len(jp.compute_portfolio_value(pd.DataFrame([_trade()]), pd.DataFrame())) == 0
