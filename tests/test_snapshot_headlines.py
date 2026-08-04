"""Tests for the FT headline block folded into the daily snapshot.

The pure aggregation (derive.headline_summary) is tested directly in pandas.
A DuckDB integration test then checks the optional fold-in in derive.run:
the snapshot gains the headline columns when fct_headlines exists, and builds
without them when it doesn't. The integration test skips if duckdb is absent."""
import datetime as dt

import pandas as pd
import pytest

from src.transform import derive
from src.transform.derive import headline_summary


def _headlines():
    """A fct_headlines-shaped frame: 6 stories on 7 Jan, 2 on 6 Jan, 1 undated."""
    d7, d6 = dt.date(2026, 1, 7), dt.date(2026, 1, 6)
    rows = []
    for i in range(1, 7):                       # H1..H6 through the day (H6 latest)
        rows.append({"published_date": d7, "published_at": dt.datetime(2026, 1, 7, 7 + i, 0),
                     "title": f"H{i}", "section": "core"})
    rows += [
        {"published_date": d6, "published_at": dt.datetime(2026, 1, 6, 9, 0), "title": "A", "section": "core"},
        {"published_date": d6, "published_at": dt.datetime(2026, 1, 6, 8, 0), "title": "B", "section": "core"},
        {"published_date": None, "published_at": None, "title": "Undated", "section": "core"},
    ]
    return pd.DataFrame(rows)


def test_counts_and_top_titles():
    out = headline_summary(_headlines())          # default top_n = 5
    r7 = out[out["date"] == dt.date(2026, 1, 7)].iloc[0]
    assert r7["n_headlines"] == 6                  # all six counted
    # the five most-recent titles, freshest first
    assert r7["top_headlines"] == "H6 | H5 | H4 | H3 | H2"

    r6 = out[out["date"] == dt.date(2026, 1, 6)].iloc[0]
    assert r6["n_headlines"] == 2
    assert r6["top_headlines"] == "A | B"          # A (09:00) before B (08:00)


def test_undated_rows_ignored():
    out = headline_summary(_headlines())
    assert len(out) == 2                           # only the two real calendar days


def test_top_n_is_configurable():
    out = headline_summary(_headlines(), top_n=2)
    r7 = out[out["date"] == dt.date(2026, 1, 7)].iloc[0]
    assert r7["top_headlines"] == "H6 | H5"


def test_handles_missing_table():
    assert len(headline_summary(None)) == 0        # fct_headlines absent -> empty, no crash
    assert len(headline_summary(pd.DataFrame())) == 0


def test_all_undated_yields_empty():
    df = pd.DataFrame([{"published_date": None, "published_at": None, "title": "x", "section": "core"}])
    assert len(headline_summary(df)) == 0


# ---------------------------------------------------------------- integration
def _analytics(con):
    con.execute("CREATE TABLE fct_series_analytics "
                "(series_id VARCHAR, obs_date DATE, value DOUBLE, primary_value DOUBLE, primary_zscore DOUBLE)")
    con.executemany("INSERT INTO fct_series_analytics VALUES (?,?,?,?,?)",
                    [("DGS10", "2026-01-06", 4.0, 4.0, 0.1),
                     ("DGS10", "2026-01-07", 4.1, 4.1, 0.2)])


def test_fold_in_present(monkeypatch=None):
    duckdb = pytest.importorskip("duckdb")
    con = duckdb.connect(":memory:")
    _analytics(con)
    con.execute("CREATE TABLE fct_headlines (item_id VARCHAR, title VARCHAR, summary VARCHAR, "
                "link VARCHAR, published_at TIMESTAMP, published_date DATE, first_feed VARCHAR, "
                "section VARCHAR, region VARCHAR, first_seen_at TIMESTAMP)")
    con.execute("INSERT INTO fct_headlines VALUES ('s1','Alpha',NULL,'l',"
                "TIMESTAMP '2026-01-07 09:00:00', DATE '2026-01-07','markets','core','global', "
                "TIMESTAMP '2026-01-07 09:30:00')")
    con.execute("INSERT INTO fct_headlines VALUES ('s2','Beta',NULL,'l',"
                "TIMESTAMP '2026-01-07 10:00:00', DATE '2026-01-07','home','core','global', "
                "TIMESTAMP '2026-01-07 10:30:00')")
    derive.run(con)
    n, top = con.execute("SELECT n_headlines, top_headlines FROM fct_daily_snapshot "
                         "WHERE date = DATE '2026-01-07'").fetchone()
    assert n == 2
    assert top == "Beta | Alpha"                   # Beta (10:00) is fresher than Alpha (09:00)


def test_snapshot_builds_without_headlines(monkeypatch=None):
    duckdb = pytest.importorskip("duckdb")
    con = duckdb.connect(":memory:")
    _analytics(con)                                # no fct_headlines table at all
    derive.run(con)
    cols = [d[0] for d in con.execute("SELECT * FROM fct_daily_snapshot LIMIT 0").description]
    assert "n_headlines" not in cols               # block simply absent, no crash
    assert "dgs10" in cols                          # macro snapshot still built


def test_vol_summary_passthrough_and_empty():
    import datetime as dt
    vt = pd.DataFrame({"date": [dt.date(2026, 1, 7)], "vix_ts_ratio": [1.08],
                       "ts_state": ["backwardation"], "vix": [28.0]})
    out = derive.vol_summary(vt)
    assert list(out.columns) == ["date", "vix_ts_ratio", "ts_state"]
    assert out.iloc[0]["ts_state"] == "backwardation"
    assert len(derive.vol_summary(None)) == 0
    assert len(derive.vol_summary(pd.DataFrame())) == 0


def test_positioning_summary_and_pit_asof():
    import datetime as dt
    # two weeks of VIX positioning; available_from is the Friday release
    pos = pd.DataFrame([
        {"market_id": "vix",   "available_from": dt.date(2026, 7, 17), "net_lev_pctile": 0.90},
        {"market_id": "vix",   "available_from": dt.date(2026, 7, 24), "net_lev_pctile": 0.95},
        {"market_id": "sp500", "available_from": dt.date(2026, 7, 17), "net_lev_pctile": 0.60},
    ])
    summ = derive.positioning_summary(pos)
    assert list(summ.columns) == ["available_from", "vix_lev_pctile", "sp500_lev_pctile", "positioning_note"]
    assert "VIX lev 95%ile" in summ.iloc[-1]["positioning_note"]
    assert len(derive.positioning_summary(None)) == 0

    # point-in-time as-of: a Thursday before the Friday release must NOT see that week
    snap = pd.DataFrame({"date": [dt.date(2026, 7, 16), dt.date(2026, 7, 18), dt.date(2026, 7, 25)]})
    snap["_d"] = pd.to_datetime(snap["date"])
    merged = pd.merge_asof(snap.sort_values("_d"), summ.sort_values("available_from"),
                           left_on="_d", right_on="available_from", direction="backward")
    v = dict(zip(merged["date"], merged["vix_lev_pctile"]))
    assert pd.isna(v[dt.date(2026, 7, 16)])          # before first release -> nothing
    assert v[dt.date(2026, 7, 18)] == 0.90           # after 07-17 release
    assert v[dt.date(2026, 7, 25)] == 0.95           # after 07-24 release


def test_fold_positioning_handles_mixed_datetime_resolution():
    import datetime as dt
    pos = pd.DataFrame([
        {"market_id": "vix", "available_from": dt.date(2026, 7, 17), "net_lev_pctile": 0.90},
        {"market_id": "vix", "available_from": dt.date(2026, 7, 24), "net_lev_pctile": 0.95},
    ])
    summ = derive.positioning_summary(pos)
    summ["available_from"] = pd.to_datetime(summ["available_from"]).astype("datetime64[us]")   # us
    snap = pd.DataFrame({"date": [dt.date(2026, 7, 16), dt.date(2026, 7, 18), dt.date(2026, 7, 25)],
                         "vix": [20.0, 21.0, 22.0]})
    snap["date"] = pd.to_datetime(snap["date"]).astype("datetime64[s]")                        # s (mismatch)
    out = derive._fold_positioning(snap, summ)          # must not raise on mixed units
    v = dict(zip(pd.to_datetime(out["date"]).dt.date, out["vix_lev_pctile"]))
    assert pd.isna(v[dt.date(2026, 7, 16)])             # before first Friday release
    assert v[dt.date(2026, 7, 18)] == 0.90
    assert v[dt.date(2026, 7, 25)] == 0.95
