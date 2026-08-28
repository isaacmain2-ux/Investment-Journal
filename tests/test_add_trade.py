"""Tests for src/journal/add_trade.py - the pure row-builder and the interactive
confirm/log flow (stdin simulated via monkeypatch, file I/O redirected to tmp_path)."""
import datetime as dt

import pandas as pd
import pytest

from src.journal import add_trade, ledger


# ------------------------------------------------------------------ build_trade_row
def test_build_trade_row_happy_path():
    row = add_trade.build_trade_row("nvda", "buy", 10, 187.40, [],
                                    trade_date=dt.date(2026, 8, 23), thesis="Top-5 scan")
    assert row["trade_id"] == "2026-08-23-NVDA-01"
    assert row["ticker"] == "NVDA" and row["action"] == "BUY"
    assert row["quantity"] == 10.0 and row["price"] == 187.40
    assert row["currency"] == "USD" and row["fees"] == 0.0
    assert row["conviction"] == "medium" and row["timeframe"] == "months"
    assert row["thesis"] == "Top-5 scan"


def test_build_trade_row_increments_sequence():
    row1 = add_trade.build_trade_row("NVDA", "BUY", 5, 100, [], trade_date=dt.date(2026, 8, 23))
    row2 = add_trade.build_trade_row("NVDA", "BUY", 5, 101, [row1["trade_id"]],
                                     trade_date=dt.date(2026, 8, 23))
    assert row1["trade_id"] == "2026-08-23-NVDA-01"
    assert row2["trade_id"] == "2026-08-23-NVDA-02"


@pytest.mark.parametrize("ticker,action,qty,price", [
    ("", "BUY", 1, 1), ("NVDA", "HOLD", 1, 1), ("NVDA", "BUY", 0, 1), ("NVDA", "BUY", 1, 0),
    ("NVDA", "BUY", -5, 1), ("NVDA", "BUY", 1, -5),
])
def test_build_trade_row_rejects_bad_input(ticker, action, qty, price):
    with pytest.raises(ValueError):
        add_trade.build_trade_row(ticker, action, qty, price, [])


def test_build_trade_row_falls_back_bad_conviction_timeframe():
    row = add_trade.build_trade_row("NVDA", "BUY", 1, 1, [], conviction="extreme",
                                    timeframe="decades")
    assert row["conviction"] == "medium"
    assert row["timeframe"] == "months"


def test_build_trade_row_accepts_string_date():
    row = add_trade.build_trade_row("NVDA", "BUY", 1, 1, [], trade_date="2026-08-23")
    assert row["trade_date"] == "2026-08-23"


# ------------------------------------------------------------------ interactive flow
def _candidates():
    return pd.DataFrame([
        {"ticker": "NVDA", "asof_date": dt.date(2026, 8, 21), "sector": "Technology",
         "composite_z": 1.82, "composite_pct": 0.97, "value_pct": 0.41, "momentum_pct": 0.97,
         "quality_pct": 0.88, "growth_pct": 0.95, "last_close": 187.40},
        {"ticker": "CAT", "asof_date": dt.date(2026, 8, 21), "sector": "Industrials",
         "composite_z": 1.31, "composite_pct": 0.90, "value_pct": 0.68, "momentum_pct": 0.71,
         "quality_pct": 0.66, "growth_pct": 0.74, "last_close": 412.55},
    ])


def test_interactive_log_appends_confirmed_rows(tmp_path, monkeypatch):
    monkeypatch.setattr(ledger, "PATH", str(tmp_path / "trades.csv"))
    monkeypatch.setattr(add_trade.ledger, "PATH", str(tmp_path / "trades.csv"))
    # picks "1,2"; NVDA: qty 10, blank price (defaults), blank conviction/timeframe/catalyst/thesis/tags
    # CAT: qty 6, blank everything
    answers = iter([
        "1,2",
        "10", "", "high", "", "capex", "riding the cycle", "ai,momentum",
        "6", "", "", "", "", "", "",
    ])
    monkeypatch.setattr("builtins.input", lambda *_a, **_k: next(answers))
    n = add_trade.interactive_log(_candidates(), dt.date(2026, 8, 21))
    assert n == 2
    rows = ledger.read_trades(str(tmp_path / "trades.csv"))
    assert len(rows) == 2
    nvda = next(r for r in rows if r["ticker"] == "NVDA")
    assert nvda["quantity"] == 10.0
    assert nvda["price"] == 187.40           # defaulted from last_close
    assert nvda["conviction"] == "high"
    assert "Top-5 scan 2026-08-21" in nvda["thesis"]
    assert "riding the cycle" in nvda["thesis"]
    cat = next(r for r in rows if r["ticker"] == "CAT")
    assert cat["quantity"] == 6.0
    assert cat["price"] == 412.55


def test_interactive_log_skip_all(tmp_path, monkeypatch):
    monkeypatch.setattr(ledger, "PATH", str(tmp_path / "trades.csv"))
    monkeypatch.setattr("builtins.input", lambda *_a, **_k: "n")
    n = add_trade.interactive_log(_candidates(), dt.date(2026, 8, 21))
    assert n == 0
    assert not (tmp_path / "trades.csv").exists()


def test_interactive_log_blank_quantity_skips_that_row(tmp_path, monkeypatch):
    monkeypatch.setattr(ledger, "PATH", str(tmp_path / "trades.csv"))
    monkeypatch.setattr(add_trade.ledger, "PATH", str(tmp_path / "trades.csv"))
    answers = iter(["1,2", "", "6", "", "", "", "", "", ""])   # row 1: blank qty -> skipped
    monkeypatch.setattr("builtins.input", lambda *_a, **_k: next(answers))
    n = add_trade.interactive_log(_candidates(), dt.date(2026, 8, 21))
    assert n == 1
    rows = ledger.read_trades(str(tmp_path / "trades.csv"))
    assert rows[0]["ticker"] == "CAT"


def test_interactive_log_no_candidates():
    assert add_trade.interactive_log(pd.DataFrame(), None) == 0
    assert add_trade.interactive_log(None, None) == 0
