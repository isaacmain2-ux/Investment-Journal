"""
Addition #2 pre-flight: confirm the CFTC Socrata dataset is reachable, its schema
is intact, and each manifest `match` pattern resolves to a real contract - printing
the actual market_and_exchange_names it matched so the patterns can be corrected
before a full ingest. No warehouse writes, no API key.

Usage (from the project root):
    python -m src.extract.cot_preflight
"""
from __future__ import annotations

import sys

from src.common.config import load_cot_markets, iter_cot_markets
from src.extract.cot_client import probe_schema, list_markets


def main(config_path: str = "config/cot_markets.yaml") -> int:
    cfg = load_cot_markets(config_path)
    markets = iter_cot_markets(cfg)
    meta = cfg["meta"]
    dataset, base = meta["dataset"], meta.get("base")

    try:
        cols = probe_schema(dataset, base)
    except Exception as e:      # noqa: BLE001
        print(f"!! schema/connectivity check failed: {e}")
        return 1
    print(f"Dataset {dataset} reachable; {len(cols)} columns, required fields present.\n")

    resolved = 0
    for m in markets:
        try:
            names = list_markets(m["match"], dataset, base)
        except Exception as e:      # noqa: BLE001
            print(f"  !! {m['id']:<8} error: {e}")
            continue
        if names:
            resolved += 1
            head = names[0] + (f"  (+{len(names) - 1} more)" if len(names) > 1 else "")
            print(f"  ok {m['id']:<8} '{m['match']}' -> {head}")
        else:
            print(f"  !! {m['id']:<8} '{m['match']}' matched NO market - fix the pattern")

    print(f"\n{resolved}/{len(markets)} patterns resolved.")
    return 0 if resolved == len(markets) else 1


if __name__ == "__main__":
    sys.exit(main())
