"""
Addition #3 pre-flight: confirm Yahoo option chains are reachable and each ticker
yields a usable skew, printing the sampled expiry and measures so the source can be
sanity-checked before it's run on a schedule. No warehouse writes.

Usage (from the project root):
    python -m src.extract.skew_preflight
"""
from __future__ import annotations

import sys
from datetime import date

from src.common.config import load_skew_tickers, iter_skew_tickers
from src.extract.skew_client import fetch_skew


def main(config_path: str = "config/skew_tickers.yaml") -> int:
    cfg = load_skew_tickers(config_path)
    tickers = iter_skew_tickers(cfg)
    meta = cfg["meta"]
    target_dte = int(meta.get("target_dte", 30))
    m = meta.get("moneyness", {}) or {}
    m_put, m_atm, m_call = float(m.get("put", 0.90)), float(m.get("atm", 1.00)), float(m.get("call", 1.10))
    capture = date.today()

    ok = 0
    for t in tickers:
        res = fetch_skew(t["id"], t["ticker"], target_dte=target_dte, capture_date=capture,
                         m_put=m_put, m_atm=m_atm, m_call=m_call)
        if res.status == "ok":
            ok += 1
            ps, rr = res.measures.get("put_skew"), res.measures.get("risk_reversal")
            print(f"  ok {t['id']:<6} {t['ticker']:<5} exp {res.expiry} ({res.dte}d)  "
                  f"spot {res.spot:.2f}  put_skew {ps:+.4f}  rr {rr:+.4f}")
        else:
            print(f"  !! {t['id']:<6} {t['ticker']:<5} {res.status}: {res.error or ''}")

    print(f"\n{ok}/{len(tickers)} tickers returned a usable skew.")
    return 0 if ok == len(tickers) else 1


if __name__ == "__main__":
    sys.exit(main())
