"""
The journal ledger: data/journal/trades.csv.

This is the ONLY module that reads or writes the CSV directly. Isaac never opens it
in a spreadsheet - `add_trade.py` calls `append_trades()`, `scan_candidates.py` and
`load_journal.py` call `read_trades()`. Plain `csv.DictWriter`/`DictReader`, so no
Microsoft Office (or any spreadsheet app) is ever required.

The file is created on first write with a header row; reading a ledger that doesn't
exist yet returns an empty list rather than raising, so a brand-new project (or a
test) doesn't need to seed anything.
"""
from __future__ import annotations

import csv
from datetime import date, datetime, timezone
from pathlib import Path

PATH = "data/journal/trades.csv"

# column order as written to the CSV - see reports/Journal_Portfolio_Build_Plan.md #3
FIELDS = [
    "trade_id", "trade_date", "portfolio", "ticker", "action", "quantity", "price",
    "currency", "fees", "conviction", "timeframe", "catalyst", "thesis", "tags",
    "entered_at",
]

VALID_ACTIONS = {"BUY", "SELL"}


def read_trades(path: str | None = None) -> list[dict]:
    """Read the ledger into tidy dicts. Missing file -> []. Tolerant of blank rows.
    `path` defaults to the *current* module-level PATH (looked up at call time, not
    import time), so tests can redirect it via monkeypatch.setattr(ledger, "PATH", ...)."""
    p = Path(path if path is not None else PATH)
    if not p.exists():
        return []
    out = []
    with open(p, newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            if not (r.get("trade_id") or "").strip():
                continue
            out.append(_coerce(r))
    return out


def _coerce(r: dict) -> dict:
    row = dict(r)
    row["trade_id"] = row.get("trade_id", "").strip()
    row["ticker"] = (row.get("ticker") or "").strip().upper()
    row["action"] = (row.get("action") or "").strip().upper()
    row["portfolio"] = (row.get("portfolio") or "main").strip() or "main"
    for numeric in ("quantity", "price", "fees"):
        v = row.get(numeric)
        try:
            row[numeric] = float(v) if v not in (None, "") else (0.0 if numeric == "fees" else None)
        except (TypeError, ValueError):
            row[numeric] = None
    return row


def append_trades(rows: list[dict], path: str | None = None) -> int:
    """Append rows to the ledger, writing the header first if the file is new.
    Creates data/journal/ if it doesn't exist. Returns the number of rows written.
    `path` defaults to the current module-level PATH (see read_trades)."""
    if not rows:
        return 0
    p = Path(path if path is not None else PATH)
    p.parent.mkdir(parents=True, exist_ok=True)
    is_new = not p.exists() or p.stat().st_size == 0
    with open(p, "a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS, extrasaction="ignore")
        if is_new:
            w.writeheader()
        for row in rows:
            w.writerow({k: row.get(k, "") for k in FIELDS})
    return len(rows)


def next_trade_id(existing_ids, trade_date, ticker) -> str:
    """{date}-{ticker}-{seq} - deterministic and collision-free for the same
    (date, ticker) pair even across multiple trades in one session."""
    d = trade_date if isinstance(trade_date, (date, datetime)) else \
        datetime.fromisoformat(str(trade_date)[:10]).date()
    prefix = f"{d.isoformat()}-{ticker.upper()}-"
    existing = {str(x) for x in (existing_ids or [])}
    seq = 1
    while f"{prefix}{seq:02d}" in existing:
        seq += 1
    return f"{prefix}{seq:02d}"


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(tzinfo=None, microsecond=0).isoformat(sep=" ")
