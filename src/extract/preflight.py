"""
Pre-flight check: confirm the FRED API key works and the network is reachable
by fetching one well-known series (DGS10, the US 10-year yield).

Run from the project root:
    python -m src.extract.preflight
"""
from __future__ import annotations

import os
import sys

from dotenv import load_dotenv

from src.extract.fred_client import fetch_series


def main() -> int:
    load_dotenv()
    key = os.environ.get("FRED_API_KEY")
    if not key:
        print("FRED_API_KEY not found in .env — add it (see docs) and retry.")
        return 1

    print("Contacting FRED for DGS10 (US 10-year yield)...")
    r = fetch_series("DGS10", key, start="2024-01-01")

    if r.status == "ok":
        last = r.df.iloc[-1]
        print(f"OK — fetched {r.n_obs} observations of DGS10.")
        print(f"Latest: {last['obs_date']} = {last['value']}%")
        print("\nPre-flight passed. Your key works and FRED is reachable.")
        return 0

    print(f"FAILED — status={r.status}  error={r.error}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
