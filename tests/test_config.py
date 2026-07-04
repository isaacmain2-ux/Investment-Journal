"""Tests for src/common/config.py — pure/offline, no network."""
import yaml
import pytest

from src.common.config import load_config, iter_series


def test_real_config_loads_and_validates():
    cfg = load_config("config/macro_series.yaml")
    series = iter_series(cfg)
    assert len(series) == 60                      # the full catalogue
    ids = [s["id"] for s in series]
    assert len(ids) == len(set(ids))              # no duplicate ids
    assert cfg["meta"]["base_currency"] == "GBP"
    # every series carries the fields the pipeline relies on
    for s in series:
        assert {"id", "name", "region", "freq", "transform", "category"} <= set(s)


def _write(tmp_path, obj):
    p = tmp_path / "cfg.yaml"
    p.write_text(yaml.safe_dump(obj))
    return str(p)


def test_bad_freq_rejected(tmp_path):
    bad = {"meta": {"base_currency": "GBP"},
           "series": {"x": [{"id": "A", "name": "a", "region": "US",
                             "freq": "X", "transform": "level"}]}}
    with pytest.raises(ValueError):
        load_config(_write(tmp_path, bad))


def test_bad_transform_rejected(tmp_path):
    bad = {"meta": {"base_currency": "GBP"},
           "series": {"x": [{"id": "A", "name": "a", "region": "US",
                             "freq": "D", "transform": "wobble"}]}}
    with pytest.raises(ValueError):
        load_config(_write(tmp_path, bad))


def test_duplicate_id_rejected(tmp_path):
    bad = {"meta": {"base_currency": "GBP"},
           "series": {"a": [{"id": "DUP", "name": "a", "region": "US",
                             "freq": "D", "transform": "level"}],
                      "b": [{"id": "DUP", "name": "b", "region": "US",
                             "freq": "D", "transform": "level"}]}}
    with pytest.raises(ValueError):
        load_config(_write(tmp_path, bad))


def test_missing_field_rejected(tmp_path):
    bad = {"meta": {"base_currency": "GBP"},
           "series": {"a": [{"id": "A", "name": "a", "region": "US", "freq": "D"}]}}
    with pytest.raises(ValueError):
        load_config(_write(tmp_path, bad))
