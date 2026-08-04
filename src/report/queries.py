"""
The one database-facing module: read each gold table into a tidy DataFrame.

Every read is defensive - a missing table (e.g. FT not ingested yet, or a
FRED-only warehouse) returns an empty DataFrame rather than raising, so the
report degrades gracefully. This is the only file that needs DuckDB; everything
downstream is pure functions of the DataFrames returned here.
"""
from __future__ import annotations

import pandas as pd

from . import stats


def _df(con, sql) -> pd.DataFrame:
    try:
        return con.execute(sql).df()
    except Exception:      # noqa: BLE001 - table may not exist yet
        return pd.DataFrame()


def gather(con) -> dict:
    """Pull every table the report uses into one bundle of DataFrames."""
    b = {
        "regime": _df(con, "SELECT * FROM fct_regime ORDER BY date"),
        "curve": _df(con, "SELECT * FROM fct_curve ORDER BY date"),
        "credit": _df(con, "SELECT * FROM fct_credit ORDER BY date"),
        "vol_term": _df(con, "SELECT * FROM fct_vol_term ORDER BY date"),
        "positioning": _df(con, "SELECT * FROM fct_positioning ORDER BY market_id, report_date"),
        "skew": _df(con, "SELECT * FROM fct_skew ORDER BY ticker_id, capture_date"),
        "fx": _df(con, "SELECT * FROM fct_fx ORDER BY date"),
        "snapshot": _df(con, "SELECT * FROM fct_daily_snapshot ORDER BY date"),
        "series_analytics": _df(
            con, "SELECT series_id, obs_date, value, primary_zscore FROM fct_series_analytics"),
        "equity": _df(con, "SELECT ticker, price_date, adj_close, ret_1d, ret_21d, ret_63d, "
                           "ret_252d, vol_21d FROM fct_equity_analytics"),
        "rel_strength": _df(con, 'SELECT ticker, price_date, "group", excess_63d, rs_trend_21d '
                                 "FROM fct_relative_strength"),
        "fundamentals": _df(con, "SELECT * FROM fct_fundamentals"),
        "valuation": _df(con, "SELECT * FROM fct_valuation"),
        "factors": _df(con, "SELECT * FROM fct_factor_scores"),
        "headlines": _df(con, "SELECT item_id, title, link, published_at, published_date, "
                              "section, region FROM fct_headlines"),
        "feed_status": _df(con, "SELECT feed, status, http_status, n_items, n_new FROM ft_feed_status"),
    }
    b["coverage"] = _coverage(con, b)
    return b


def _coverage(con, b) -> dict:
    cov = {}
    cov["FRED macro"] = stats.coverage(b["series_analytics"], "obs_date")
    cov["Equities"] = stats.coverage(b["equity"], "price_date")
    cov["Fundamentals"] = stats.coverage(b["fundamentals"], "period_end")
    cov["FT headlines"] = stats.coverage(b["headlines"], "published_date")
    cov["Daily snapshot"] = stats.coverage(b["snapshot"], "date")
    return cov
