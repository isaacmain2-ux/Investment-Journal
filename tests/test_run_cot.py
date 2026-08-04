"""Orchestration tests for run_cot.py - every stage is mocked, so no network or db.
Asserts stage order, flag pass-through, and stop-at-first-failure."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import src.extract.cot_preflight as pf
import src.extract.cot_ingest as ing
import src.transform.run_transform as rt
import run_cot


def _wire(mp, order, pf_rc=0, ing_rc=0, rt_rc=0, test_rc=0):
    mp.setattr(pf, "main", lambda *a, **k: (order.append("preflight"), pf_rc)[1])
    mp.setattr(ing, "run", lambda only=None, full=False, **k: (order.append(("load", only, full)), ing_rc)[1])
    mp.setattr(rt, "run", lambda *a, **k: (order.append("transform"), rt_rc)[1])
    mp.setattr(run_cot.subprocess, "call", lambda *a, **k: (order.append("test"), test_rc)[1])


def test_default_is_load_then_transform(monkeypatch):
    order = []; _wire(monkeypatch, order)
    assert run_cot.run() == 0
    assert order == [("load", None, False), "transform"]


def test_full_order_with_all_flags(monkeypatch):
    order = []; _wire(monkeypatch, order)
    assert run_cot.run(preflight=True, test=True, only=["vix"], full=True) == 0
    assert order == ["preflight", ("load", ["vix"], True), "test", "transform"]


def test_preflight_failure_stops_before_load(monkeypatch):
    order = []; _wire(monkeypatch, order, pf_rc=1)
    assert run_cot.run(preflight=True) == 1
    assert order == ["preflight"]


def test_load_failure_stops_before_transform(monkeypatch):
    order = []; _wire(monkeypatch, order, ing_rc=2)
    assert run_cot.run() == 2
    assert order == [("load", None, False)]


def test_test_failure_stops_before_transform(monkeypatch):
    order = []; _wire(monkeypatch, order, test_rc=1)
    assert run_cot.run(test=True) == 1
    assert order == [("load", None, False), "test"]


def test_skip_transform_loads_only(monkeypatch):
    order = []; _wire(monkeypatch, order)
    assert run_cot.run(skip_transform=True) == 0
    assert order == [("load", None, False)]
