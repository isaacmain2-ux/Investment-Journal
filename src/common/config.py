"""
Load and validate the project's manifests.

Two manifests, two sets of functions that share the same pattern:
  * the FRED series manifest  (config/macro_series.yaml)  - load_config / iter_series
  * the securities manifest   (config/securities.yaml)    - load_securities / iter_securities

Each loader validates on read, so a malformed manifest fails immediately rather
than halfway through a run.
"""
from __future__ import annotations

from pathlib import Path
import yaml

# ------------------------------------------------------------------ FRED
VALID_FREQ = {"D", "W", "M", "Q"}
VALID_TRANSFORM = {"level", "yoy", "mom"}
REQUIRED_FIELDS = ("id", "name", "region", "freq", "transform")


def load_config(path: str = "config/macro_series.yaml") -> dict:
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"Config not found: {p.resolve()}")
    with open(p, "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    _validate(cfg)
    return cfg


def iter_series(cfg: dict) -> list[dict]:
    out: list[dict] = []
    for category, items in cfg["series"].items():
        for s in items:
            row = dict(s)
            row["category"] = category
            row.setdefault("verify", False)
            out.append(row)
    return out


def _validate(cfg: dict) -> None:
    if not isinstance(cfg, dict) or "series" not in cfg or "meta" not in cfg:
        raise ValueError("Config must have top-level 'meta' and 'series' keys.")
    series = iter_series(cfg)
    if not series:
        raise ValueError("Config contains no series.")
    seen: set[str] = set()
    for s in series:
        for field in REQUIRED_FIELDS:
            if field not in s:
                raise ValueError(
                    f"Series '{s.get('id', '<no id>')}' is missing required field '{field}'.")
        if s["freq"] not in VALID_FREQ:
            raise ValueError(
                f"Series '{s['id']}' has invalid freq '{s['freq']}' (allowed: {sorted(VALID_FREQ)}).")
        if s["transform"] not in VALID_TRANSFORM:
            raise ValueError(
                f"Series '{s['id']}' has invalid transform '{s['transform']}'.")
        if s["id"] in seen:
            raise ValueError(f"Duplicate series id in config: '{s['id']}'.")
        seen.add(s["id"])


# ------------------------------------------------------------ SECURITIES
VALID_SECURITY_TYPES = {"index", "etf", "stock"}
SECURITY_REQUIRED = ("ticker", "name", "type", "region", "currency")


def load_securities(path: str = "config/securities.yaml") -> dict:
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"Securities config not found: {p.resolve()}")
    with open(p, "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    _validate_securities(cfg)
    return cfg


def iter_securities(cfg: dict) -> list[dict]:
    """Flatten {group: [security, ...]} into one list, tagging each with its group."""
    out: list[dict] = []
    for group, items in cfg["securities"].items():
        for s in items:
            row = dict(s)
            row["group"] = group
            row.setdefault("sector", None)
            out.append(row)
    return out


def _validate_securities(cfg: dict) -> None:
    if not isinstance(cfg, dict) or "securities" not in cfg or "meta" not in cfg:
        raise ValueError("Securities config must have top-level 'meta' and 'securities' keys.")
    secs = iter_securities(cfg)
    if not secs:
        raise ValueError("Securities config contains no tickers.")
    seen: set[str] = set()
    for s in secs:
        for field in SECURITY_REQUIRED:
            if field not in s:
                raise ValueError(
                    f"Security '{s.get('ticker', '<no ticker>')}' is missing required field '{field}'.")
        if s["type"] not in VALID_SECURITY_TYPES:
            raise ValueError(
                f"Security '{s['ticker']}' has invalid type '{s['type']}' "
                f"(allowed: {sorted(VALID_SECURITY_TYPES)}).")
        if s["ticker"] in seen:
            raise ValueError(f"Duplicate ticker in securities config: '{s['ticker']}'.")
        seen.add(s["ticker"])
