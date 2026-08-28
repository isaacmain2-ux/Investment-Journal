"""Tests for the journal insight rules (Review due, Benchmark gap, Journal gone
quiet) and the Journal dashboard section. All dates are computed relative to
pd.Timestamp.today() (as the rules themselves do), not hardcoded, so the tests
don't go stale."""
import pandas as pd

from src.report import insights, sections

TODAY = pd.Timestamp.today().normalize()


def _positions(**overrides):
    row = {"portfolio": "main", "ticker": "NVDA", "status": "OPEN", "quantity_open": 10.0,
           "avg_cost": 200.0, "realized_pnl_cum": 0.0,
           "first_entry_date": (TODAY - pd.Timedelta(days=10)).date(),
           "last_trade_date": (TODAY - pd.Timedelta(days=10)).date(),
           "conviction": "high", "timeframe": "months", "catalyst": "capex",
           "thesis": "Top-5 scan", "tags": "ai"}
    row.update(overrides)
    return pd.DataFrame([row])


def _last_close(ticker="NVDA", price=200.0):
    return pd.DataFrame([{"ticker": ticker, "asof_date": TODAY.date(), "last_close": price}])


# ------------------------------------------------------------------ Review due
def test_review_due_fires_on_deep_drawdown():
    flags = insights.build({"positions": _positions(), "security_last_close": _last_close(price=150.0)})
    assert any("Review due" in f["text"] and f["severity"] == insights.WARN for f in flags)


def test_review_due_does_not_fire_on_small_move():
    flags = insights.build({"positions": _positions(), "security_last_close": _last_close(price=195.0)})
    assert not any("Review due" in f["text"] for f in flags)


def test_review_due_fires_past_stated_timeframe():
    old = _positions(first_entry_date=(TODAY - pd.Timedelta(days=200)).date(), timeframe="months")
    flags = insights.build({"positions": old, "security_last_close": _last_close(price=201.0)})
    assert any("Review due" in f["text"] and "timeframe" in f["text"] for f in flags)


def test_review_due_ignores_closed_positions():
    closed = _positions(status="CLOSED")
    flags = insights.build({"positions": closed, "security_last_close": _last_close(price=100.0)})
    assert not any("Review due" in f["text"] for f in flags)


def test_no_positions_no_flags():
    assert insights.build({}) == []
    assert not any(f.get("category") == "journal" for f in insights.build({"positions": pd.DataFrame()}))


# ------------------------------------------------------------------ Benchmark gap
def _portfolio_value(start_val=1000.0, end_val=1200.0):
    d0, d1 = TODAY - pd.Timedelta(days=30), TODAY
    return pd.DataFrame([
        {"portfolio": "main", "date": d0.date(), "total_value": start_val,
         "market_value": start_val, "cost_basis_open": start_val, "unrealized_pnl": 0.0,
         "realized_pnl_cum": 0.0, "n_positions_open": 1},
        {"portfolio": "main", "date": d1.date(), "total_value": end_val,
         "market_value": end_val, "cost_basis_open": start_val,
         "unrealized_pnl": end_val - start_val, "realized_pnl_cum": 0.0, "n_positions_open": 1},
    ])


def _equity(spx_start=5000.0, spx_end=5100.0):
    d0, d1 = TODAY - pd.Timedelta(days=30), TODAY
    return pd.DataFrame([
        {"ticker": "^GSPC", "price_date": d0.date(), "adj_close": spx_start},
        {"ticker": "^GSPC", "price_date": d1.date(), "adj_close": spx_end},
    ])


def test_benchmark_gap_ahead():
    flags = insights.build({"portfolio_value": _portfolio_value(1000, 1300),   # +30%
                            "equity": _equity(5000, 5100)})                    # +2%
    f = next(x for x in flags if "S&P 500" in x["text"])
    assert "ahead of" in f["text"] and f["severity"] == insights.NOTE


def test_benchmark_gap_behind():
    flags = insights.build({"portfolio_value": _portfolio_value(1000, 1010),   # +1%
                            "equity": _equity(5000, 5300)})                    # +6%
    f = next(x for x in flags if "S&P 500" in x["text"])
    assert "behind" in f["text"]


def test_benchmark_gap_no_equity_no_flag():
    flags = insights.build({"portfolio_value": _portfolio_value()})
    assert not any("S&P 500" in f["text"] for f in flags if f.get("category") == "journal")


# ------------------------------------------------------------------ Journal gone quiet
def _trades(last_days_ago):
    return pd.DataFrame([
        {"trade_id": "T1", "trade_date": (TODAY - pd.Timedelta(days=last_days_ago)).date(),
         "ticker": "NVDA", "action": "BUY", "quantity": 10, "price": 100},
    ])


def test_journal_quiet_fires_after_threshold():
    flags = insights.build({"journal_trades": _trades(insights.JOURNAL_QUIET_DAYS + 1)})
    assert any("gone quiet" in f["text"] for f in flags)


def test_journal_quiet_does_not_fire_when_recent():
    flags = insights.build({"journal_trades": _trades(1)})
    assert not any("gone quiet" in f["text"] for f in flags)


# ------------------------------------------------------------------ section rendering
def test_journal_section_no_data():
    html = sections.journal({})
    assert "Hypothetical" in html and "No trades logged" in html


def test_journal_section_renders_positions_and_kpis():
    bundle = {
        "positions": _positions(),
        "security_last_close": _last_close(price=220.0),
        "portfolio_value": _portfolio_value(1000, 1200),
        "journal_trades": _trades(1),
    }
    html = sections.journal(bundle)
    assert "NVDA" in html and "Open positions" in html
    assert "Portfolio value" in html
    assert "Trade log" in html


def test_journal_section_never_raises_on_empty_frames():
    html = sections.journal({"positions": pd.DataFrame(), "portfolio_value": pd.DataFrame(),
                             "journal_trades": pd.DataFrame()})
    assert "Hypothetical" in html
