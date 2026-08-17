"""Tests for P2 fct_security_metrics: momentum, point-in-time fundamentals, ratios."""
import datetime as dt
import pytest
pd = pytest.importorskip("pandas")
from src.transform import build_security_metrics as M


def test_momentum_offsets():
    closes = pd.Series([100.0] * 300)
    closes.iloc[-1] = 120.0; closes.iloc[-22] = 110.0
    closes.iloc[-127] = 100.0; closes.iloc[-253] = 80.0
    m = M._mom(closes)
    assert abs(m["last_close"] - 120.0) < 1e-9
    assert abs(m["ret_1m"] - (120/110 - 1)) < 1e-9
    assert abs(m["ret_6m"] - (120/100 - 1)) < 1e-9
    assert abs(m["ret_12_1m"] - (110/80 - 1)) < 1e-9
    assert m["dist_52w_high"] <= 0


def test_momentum_short_history_guards():
    m = M._mom(pd.Series([100.0, 101.0, 102.0]))
    assert m["last_close"] == 102.0 and m["ret_12_1m"] is None and m["ret_1m"] is None


def _fund_rows():
    R = []
    def add(metric, pend, fp, filed, val):
        R.append({"ticker": "AAPL", "metric": metric, "period_end": pend,
                  "fiscal_period": fp, "filed_date": filed, "value": val})
    add("revenue", dt.date(2023, 9, 30), "FY", dt.date(2023, 11, 3), 383e9)
    add("revenue", dt.date(2022, 9, 30), "FY", dt.date(2022, 10, 28), 394e9)
    add("net_income", dt.date(2023, 9, 30), "FY", dt.date(2023, 11, 3), 97e9)
    add("equity", dt.date(2023, 9, 30), "FY", dt.date(2023, 11, 3), 62e9)
    add("shares", dt.date(2023, 9, 30), "FY", dt.date(2023, 11, 3), 15.5e9)
    add("eps_diluted", dt.date(2023, 9, 30), "FY", dt.date(2023, 11, 3), 6.13)
    add("eps_diluted", dt.date(2022, 9, 30), "FY", dt.date(2022, 10, 28), 6.11)
    return pd.DataFrame(R)


def test_latest_fundamentals_point_in_time():
    fund = _fund_rows()
    fm = M.latest_fundamentals(fund, dt.date(2024, 1, 1))["AAPL"]
    assert fm["revenue"] == 383e9 and fm["revenue_prev"] == 394e9
    fm_old = M.latest_fundamentals(fund, dt.date(2023, 1, 1))["AAPL"]
    assert fm_old["revenue"] == 394e9 and fm_old["revenue_prev"] is None


def test_compute_row_ratios():
    fm = M.latest_fundamentals(_fund_rows(), dt.date(2024, 1, 1))["AAPL"]
    pm = {"last_close": 190.0, "ret_6m": 0.1}
    row = M.compute_row("AAPL", "Tech", pm, fm)
    mktcap = 190.0 * 15.5e9
    assert abs(row["market_cap"] - mktcap) < 1
    assert abs(row["earnings_yield"] - (97e9 / mktcap)) < 1e-9
    assert abs(row["pb"] - (mktcap / 62e9)) < 1e-6
    assert abs(row["roe"] - (97e9 / 62e9)) < 1e-9
    assert abs(row["net_margin"] - (97e9 / 383e9)) < 1e-9
    assert abs(row["rev_growth_yoy"] - (383e9 / 394e9 - 1)) < 1e-9
    assert row["ret_6m"] == 0.1


def test_compute_row_safe_on_missing():
    row = M.compute_row("X", None, {"last_close": None}, {})
    assert row["market_cap"] is None and row["pe"] is None and row["roe"] is None


def test_build_combines_and_tags_asof():
    prices = pd.DataFrame({"ticker": ["AAPL"], "date": [dt.date(2026, 8, 3)], "close": [190.0]})
    rows = M.build(prices, _fund_rows(), pd.DataFrame({"ticker": ["AAPL"], "sector": ["Tech"]}),
                   dt.date(2026, 8, 3))
    assert len(rows) == 1 and rows[0]["asof_date"] == dt.date(2026, 8, 3)
    assert rows[0]["sector"] == "Tech" and rows[0]["last_close"] == 190.0


def test_sane_bounds_helper():
    assert M._sane(0.03, -0.5, 0.5) == 0.03
    assert M._sane(399259.0, -0.5, 0.5) is None       # the BKR blow-up gets nulled
    assert M._sane(None, 0, 1) is None


def test_guard_broken_shares_nulls_cap_ratios():
    # 40 x 125 shares = $5,000 market cap -> below the floor -> no cap-based ratios
    row = M.compute_row("BKR", "Energy", {"last_close": 40.0},
                        {"shares": 125, "net_income": 2e9, "equity": 5e9})
    assert row["market_cap"] is None
    assert row["earnings_yield"] is None and row["pe"] is None and row["pb"] is None


def test_guard_negative_equity_nulls_book_ratios():
    # MCD-like: real market cap, but negative book equity
    row = M.compute_row("MCD", "Consumer", {"last_close": 300.0},
                        {"shares": 720e6, "net_income": 8e9, "equity": -5e9,
                         "revenue": 25e9, "long_term_debt": 40e9})
    assert row["market_cap"] is not None                     # cap is fine
    assert row["pb"] is None and row["roe"] is None and row["debt_to_equity"] is None
    assert row["net_margin"] is not None and row["earnings_yield"] is not None   # income ratios OK


# ---------------- end-to-end run() against a DB ----------------
duckdb = pytest.importorskip("duckdb")
from src.load import load_securities as L


def test_run_end_to_end_populates_fct():
    con = duckdb.connect(":memory:")
    L.ensure_schema(con)
    # dim + one ticker with 300 days of prices + fundamentals
    L.upsert_securities(con, [{"ticker": "AAPL", "name": "Apple", "sector": "Tech", "cik": 320193}])
    import datetime as dt
    base = dt.date(2025, 6, 1)
    prices = []
    for i in range(300):
        prices.append({"ticker": "AAPL", "date": base + dt.timedelta(days=i),
                       "open": 100.0, "high": 100.0, "low": 100.0, "close": 100.0 + i * 0.1,
                       "volume": 1e6})
    L.load_prices(con, prices)
    L.load_fundamentals(con, [
        {"ticker": "AAPL", "cik": "0000320193", "metric": "net_income", "xbrl_tag": "x",
         "period_end": dt.date(2024, 9, 30), "fiscal_year": 2024, "fiscal_period": "FY",
         "form": "10-K", "filed_date": dt.date(2024, 11, 1), "unit": "USD", "value": 100e9},
        {"ticker": "AAPL", "cik": "0000320193", "metric": "shares", "xbrl_tag": "x",
         "period_end": dt.date(2024, 9, 30), "fiscal_year": 2024, "fiscal_period": "FY",
         "form": "10-K", "filed_date": dt.date(2024, 11, 1), "unit": "shares", "value": 15e9},
        {"ticker": "AAPL", "cik": "0000320193", "metric": "equity", "xbrl_tag": "x",
         "period_end": dt.date(2024, 9, 30), "fiscal_year": 2024, "fiscal_period": "FY",
         "form": "10-K", "filed_date": dt.date(2024, 11, 1), "unit": "USD", "value": 60e9},
    ])
    assert M.run(con) == 0
    row = con.execute("SELECT ticker, last_close, market_cap, earnings_yield, roe, ret_6m "
                      "FROM fct_security_metrics WHERE ticker='AAPL'").fetchone()
    tk, last_close, mktcap, ey, roe, ret6 = row
    assert tk == "AAPL"
    assert abs(last_close - (100.0 + 299 * 0.1)) < 1e-6      # last close
    assert abs(mktcap - last_close * 15e9) < 1                # cap = price x shares
    assert abs(ey - (100e9 / mktcap)) < 1e-9                  # earnings yield
    assert abs(roe - (100e9 / 60e9)) < 1e-9                   # ROE
    assert ret6 is not None and ret6 > 0                      # rising series
