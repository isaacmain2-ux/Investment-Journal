"""
Journal P3 - the confirm/log step: turn a confirmed pick into a fully-reasoned
ledger row with zero manual file editing.

`build_trade_row()` is the pure core - given the inputs (ticker, action, quantity,
price, ...) and the set of already-used trade_ids, it returns a correctly-shaped
dict ready for `ledger.append_trades()`. That function is what's unit-tested here.

`interactive_log()` and `prompt_manual_trade()` are the terminal UI: they call
`input()` for each field, defaulting quantity/price/conviction/etc. sensibly, and
pre-fill the thesis with the factor snapshot from the scan (`scan_candidates.thesis_snapshot`)
so the reasoning is captured at the moment of the decision. They are exercised in
tests by monkeypatching `builtins.input`.

Usage (from the project root):
    python -m src.journal.scan_candidates --log        # scan, then confirm/log (usual path)
    python -m src.journal.add_trade --ticker NVDA --action BUY   # a trade outside the scan list
"""
from __future__ import annotations

import argparse
from datetime import date, datetime

import pandas as pd

from src.journal import ledger

DEFAULT_CONVICTION = "medium"
DEFAULT_TIMEFRAME = "months"
VALID_CONVICTION = {"low", "medium", "high"}
VALID_TIMEFRAME = {"weeks", "months", "years"}


def build_trade_row(ticker: str, action: str, quantity: float, price: float,
                     existing_ids: list[str] | None = None, *, trade_date=None,
                     portfolio: str = "main", currency: str = "USD", fees: float = 0.0,
                     conviction: str = DEFAULT_CONVICTION, timeframe: str = DEFAULT_TIMEFRAME,
                     catalyst: str = "", thesis: str = "", tags: str = "",
                     entered_at: str | None = None) -> dict:
    """The pure core: validate + shape one trade into a ledger-ready dict. Raises
    ValueError on a bad ticker/action/quantity/price rather than writing anything -
    the file is only ever touched with a row known to be well-formed."""
    ticker = (ticker or "").strip().upper()
    action = (action or "").strip().upper()
    if not ticker:
        raise ValueError("ticker is required.")
    if action not in ledger.VALID_ACTIONS:
        raise ValueError(f"action must be one of {sorted(ledger.VALID_ACTIONS)}, got {action!r}.")
    if quantity is None or float(quantity) <= 0:
        raise ValueError("quantity must be a positive number.")
    if price is None or float(price) <= 0:
        raise ValueError("price must be a positive number.")

    td = trade_date or date.today()
    if isinstance(td, str):
        td = datetime.fromisoformat(td[:10]).date()
    conviction = (conviction or DEFAULT_CONVICTION).strip().lower()
    if conviction not in VALID_CONVICTION:
        conviction = DEFAULT_CONVICTION
    timeframe = (timeframe or DEFAULT_TIMEFRAME).strip().lower()
    if timeframe not in VALID_TIMEFRAME:
        timeframe = DEFAULT_TIMEFRAME

    trade_id = ledger.next_trade_id(existing_ids or [], td, ticker)
    return {
        "trade_id": trade_id, "trade_date": td.isoformat(), "portfolio": portfolio or "main",
        "ticker": ticker, "action": action, "quantity": float(quantity), "price": float(price),
        "currency": currency or "USD", "fees": float(fees or 0.0),
        "conviction": conviction, "timeframe": timeframe,
        "catalyst": (catalyst or "").strip(), "thesis": (thesis or "").strip(),
        "tags": (tags or "").strip(), "entered_at": entered_at or ledger.now_iso(),
    }


# ------------------------------------------------------------------ interactive UI
def _ask(prompt: str, default: str = "") -> str:
    suffix = f" [{default}]" if default else ""
    val = input(f"  {prompt}{suffix}: ").strip()
    return val or default


def prompt_one_trade(ticker: str, existing_ids: list[str], *, default_price=None,
                      default_thesis: str = "", default_action: str = "BUY",
                      trade_date=None) -> dict | None:
    """Prompt for one confirmed ticker's trade details. Returns None if quantity is
    left blank / zero (treated as "skip this one")."""
    print(f"\n{ticker} ({default_action})")
    qty_raw = _ask("quantity")
    try:
        quantity = float(qty_raw) if qty_raw else 0.0
    except ValueError:
        quantity = 0.0
    if quantity <= 0:
        print(f"  (skipped - no quantity entered for {ticker})")
        return None
    price_default = f"{default_price:.2f}" if default_price is not None else ""
    price_raw = _ask("price", price_default)
    try:
        price = float(price_raw) if price_raw else None
    except ValueError:
        price = None
    conviction = _ask("conviction", DEFAULT_CONVICTION)
    timeframe = _ask("timeframe", DEFAULT_TIMEFRAME)
    catalyst = _ask("catalyst")
    thesis_extra = _ask("thesis (added to the scan snapshot below)" if default_thesis else "thesis")
    if default_thesis and thesis_extra:
        thesis = f"{default_thesis}\n+ {thesis_extra}"
    elif default_thesis:
        thesis = default_thesis
    else:
        thesis = thesis_extra
    tags = _ask("tags")

    row = build_trade_row(ticker, default_action, quantity, price, existing_ids,
                          trade_date=trade_date, conviction=conviction, timeframe=timeframe,
                          catalyst=catalyst, thesis=thesis, tags=tags)
    print(f"  -> logged {row['trade_id']}")
    return row


def interactive_log(candidates: pd.DataFrame, asof) -> int:
    """The scan --log flow: ask which row numbers to confirm, prompt each, append
    all confirmed rows in one write. Returns the number of trades logged."""
    if candidates is None or len(candidates) == 0:
        print("\nNo candidates to log.")
        return 0
    raw = input("\nAdd any to the journal? [row numbers, comma-separated, or 'n']: ").strip()
    if not raw or raw.lower() in ("n", "no"):
        return 0
    try:
        picks = sorted({int(x.strip()) for x in raw.split(",") if x.strip()})
    except ValueError:
        print("Couldn't parse that - expected e.g. '1,3'. Nothing logged.")
        return 0

    existing = [r["trade_id"] for r in ledger.read_trades()]
    new_rows = []
    for i in picks:
        if i < 1 or i > len(candidates):
            print(f"  (skipping row {i} - out of range)")
            continue
        cand = candidates.iloc[i - 1]
        from src.journal.scan_candidates import thesis_snapshot
        default_thesis = thesis_snapshot(cand, asof)
        row = prompt_one_trade(cand["ticker"], existing + [r["trade_id"] for r in new_rows],
                               default_price=cand.get("last_close"), default_thesis=default_thesis,
                               default_action="BUY", trade_date=asof)
        if row:
            new_rows.append(row)

    if not new_rows:
        print("\nNothing logged.")
        return 0
    ledger.append_trades(new_rows)
    print(f"\n{len(new_rows)} trade(s) appended to {ledger.PATH}.")
    return len(new_rows)


def prompt_manual_trade(ticker: str, action: str, trade_date=None) -> dict | None:
    """The --ticker path: a trade outside the scanned list, no pre-filled thesis."""
    existing = [r["trade_id"] for r in ledger.read_trades()]
    row = prompt_one_trade(ticker, existing, default_action=action, trade_date=trade_date)
    if row:
        ledger.append_trades([row])
        print(f"1 trade appended to {ledger.PATH}.")
    return row


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Log a hypothetical trade directly (outside the scan list).")
    ap.add_argument("--ticker", required=True)
    ap.add_argument("--action", choices=sorted(ledger.VALID_ACTIONS), default="BUY")
    ap.add_argument("--date", help="trade date YYYY-MM-DD, defaults to today")
    args = ap.parse_args()
    prompt_manual_trade(args.ticker, args.action, trade_date=args.date)


if __name__ == "__main__":
    main()
