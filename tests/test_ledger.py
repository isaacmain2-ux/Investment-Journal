"""Tests for src/journal/ledger.py - the only module that touches trades.csv directly."""
import datetime as dt

from src.journal import ledger


def test_read_missing_file_returns_empty(tmp_path):
    assert ledger.read_trades(str(tmp_path / "nope.csv")) == []


def test_append_creates_file_with_header(tmp_path):
    p = tmp_path / "trades.csv"
    row = {"trade_id": "2026-08-23-NVDA-01", "trade_date": "2026-08-23", "portfolio": "main",
           "ticker": "NVDA", "action": "BUY", "quantity": 10, "price": 187.4,
           "currency": "USD", "fees": 0, "conviction": "high", "timeframe": "months",
           "catalyst": "capex", "thesis": "Top-5 scan", "tags": "ai",
           "entered_at": ledger.now_iso()}
    n = ledger.append_trades([row], str(p))
    assert n == 1
    assert p.exists()
    text = p.read_text(encoding="utf-8")
    assert text.splitlines()[0] == ",".join(ledger.FIELDS)

    back = ledger.read_trades(str(p))
    assert len(back) == 1
    assert back[0]["ticker"] == "NVDA"
    assert back[0]["quantity"] == 10.0
    assert back[0]["action"] == "BUY"


def test_append_is_additive_not_overwrite(tmp_path):
    p = tmp_path / "trades.csv"
    row1 = {"trade_id": "T1", "trade_date": "2026-08-23", "ticker": "NVDA", "action": "BUY",
            "quantity": 10, "price": 187.4}
    row2 = {"trade_id": "T2", "trade_date": "2026-08-24", "ticker": "CAT", "action": "BUY",
            "quantity": 6, "price": 412.55}
    ledger.append_trades([row1], str(p))
    ledger.append_trades([row2], str(p))
    rows = ledger.read_trades(str(p))
    assert [r["trade_id"] for r in rows] == ["T1", "T2"]
    # header only written once
    assert p.read_text(encoding="utf-8").count(",".join(ledger.FIELDS)) == 1


def test_read_ignores_blank_rows(tmp_path):
    p = tmp_path / "trades.csv"
    p.write_text(",".join(ledger.FIELDS) + "\n\n\n", encoding="utf-8")
    assert ledger.read_trades(str(p)) == []


def test_portfolio_defaults_to_main(tmp_path):
    p = tmp_path / "trades.csv"
    ledger.append_trades([{"trade_id": "T1", "trade_date": "2026-08-23", "ticker": "NVDA",
                           "action": "buy", "quantity": 1, "price": 1}], str(p))
    rows = ledger.read_trades(str(p))
    assert rows[0]["portfolio"] == "main"
    assert rows[0]["action"] == "BUY"          # coerced to upper


def test_next_trade_id_increments_within_same_day_ticker():
    assert ledger.next_trade_id([], dt.date(2026, 8, 23), "NVDA") == "2026-08-23-NVDA-01"
    existing = ["2026-08-23-NVDA-01"]
    assert ledger.next_trade_id(existing, dt.date(2026, 8, 23), "NVDA") == "2026-08-23-NVDA-02"


def test_next_trade_id_distinct_per_ticker():
    existing = ["2026-08-23-NVDA-01"]
    assert ledger.next_trade_id(existing, dt.date(2026, 8, 23), "CAT") == "2026-08-23-CAT-01"


def test_next_trade_id_accepts_string_date():
    assert ledger.next_trade_id([], "2026-08-23", "V") == "2026-08-23-V-01"
