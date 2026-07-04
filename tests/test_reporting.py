"""Tests for src/common/reporting.py — pure string building, no I/O."""
from src.common.reporting import build_report


def _rows():
    return [
        {"series_id": "DGS10", "name": "US 10y", "category": "us_treasury_curve",
         "verify": False, "status": "ok", "n_obs": 100,
         "first_obs": "2024-01-01", "last_obs": "2026-01-01", "error": None},
        {"series_id": "BAD", "name": "bad one", "category": "intl_macro",
         "verify": True, "status": "error", "n_obs": 0,
         "first_obs": None, "last_obs": None, "error": "bad id (400)"},
    ]


def test_report_flags_issues_and_lists_failures():
    md = build_report(_rows(), "2026-07-04", 12.3, "2005-01-01")
    assert "COMPLETED WITH ISSUES" in md          # one error present
    assert "Series attempted: **2**" in md
    assert "`DGS10`" in md and "`BAD`" in md
    assert "## Failures / flagged" in md
    assert "bad id (400)" in md


def test_report_passes_when_clean():
    rows = [{"series_id": "X", "name": "x", "category": "c", "verify": False,
             "status": "ok", "n_obs": 5, "first_obs": "2024-01-01",
             "last_obs": "2024-02-01", "error": None}]
    md = build_report(rows, "2026-07-04", 1.0, "2005-01-01")
    assert "**Result: PASS**" in md
    assert "## Failures" not in md
