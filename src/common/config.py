"""Securities-universe config: load the manifest and read the constituents list."""
from __future__ import annotations
import csv
import yaml


def load_securities_universe(path: str = "config/securities_universe.yaml") -> dict:
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def read_constituents(path: str) -> list[dict]:
    """Read the committed universe CSV into tidy dicts (ticker upper-cased)."""
    out = []
    with open(path, newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            t = (r.get("ticker") or "").strip().upper()
            if not t:
                continue
            out.append({"ticker": t, "name": r.get("name"), "sector": r.get("sector"),
                        "industry": r.get("industry"), "cik": (r.get("cik") or "").strip() or None})
    return out
