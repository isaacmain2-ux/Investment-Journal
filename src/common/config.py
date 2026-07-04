"""
Load and validate the FRED series manifest (config/macro_series.yaml).

This is the only place that knows the shape of the config file. Everything
else asks it for a clean, validated list of series to fetch.
"""
from __future__ import annotations

from pathlib import Path
import yaml

VALID_FREQ = {"D", "W", "M", "Q"}
VALID_TRANSFORM = {"level", "yoy", "mom"}
REQUIRED_FIELDS = ("id", "name", "region", "freq", "transform")


def load_config(path: str = "config/macro_series.yaml") -> dict:
    """Read and validate the manifest. Raises on any problem, so a malformed
    config fails immediately rather than halfway through a run."""
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"Config not found: {p.resolve()}")
    with open(p, "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    _validate(cfg)
    return cfg


def iter_series(cfg: dict) -> list[dict]:
    """Flatten the {category: [series, ...]} structure into one list,
    tagging each series with the category it came from."""
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
                    f"Series '{s.get('id', '<no id>')}' is missing required field '{field}'."
                )
        if s["freq"] not in VALID_FREQ:
            raise ValueError(
                f"Series '{s['id']}' has invalid freq '{s['freq']}' (allowed: {sorted(VALID_FREQ)})."
            )
        if s["transform"] not in VALID_TRANSFORM:
            raise ValueError(
                f"Series '{s['id']}' has invalid transform '{s['transform']}' "
                f"(allowed: {sorted(VALID_TRANSFORM)})."
            )
        if s["id"] in seen:
            raise ValueError(f"Duplicate series id in config: '{s['id']}'.")
        seen.add(s["id"])
