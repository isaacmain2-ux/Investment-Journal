"""Tests for src/report/charts.py - each builder returns a non-empty embeddable
string for real data, and a graceful placeholder for empty data. Headless."""
import pandas as pd

from src.report import charts


def _ts():
    return pd.DataFrame({"date": pd.bdate_range("2026-01-01", periods=30),
                         "a": range(30), "b": range(30, 60)})


def test_line_svg():
    out = charts.line(_ts(), "date", ["a", "b"], labels=["A", "B"])
    assert "<svg" in out and "chart" in out


def test_line_empty():
    assert "chart-empty" in charts.line(pd.DataFrame(), "date", ["a"])
    assert "chart-empty" in charts.line(_ts(), "date", ["missing"])


def test_diverging_and_hbar():
    assert "<svg" in charts.diverging_bar(["x", "y", "z"], [1.0, -2.0, 0.5])
    assert "<svg" in charts.hbar(["x", "y"], [1.0, 2.0])
    assert "chart-empty" in charts.diverging_bar(["x"], [None])


def test_scatter():
    assert "<svg" in charts.scatter([1, 2, 3], [3, 2, 1], labels=["a", "b", "c"], quadrants=True)
    assert "chart-empty" in charts.scatter([], [])


def test_heatmap_png():
    m = pd.DataFrame({"mom": [1.0, -1.0], "value": [0.5, -0.5]}, index=["AAA", "BBB"])
    out = charts.heatmap(m)
    assert "data:image/png;base64," in out
    assert "chart-empty" in charts.heatmap(pd.DataFrame())


def test_sparkline():
    assert "<svg" in charts.sparkline([1, 2, 3, 2, 4])
    assert charts.sparkline([1]) == ""          # too short -> nothing
