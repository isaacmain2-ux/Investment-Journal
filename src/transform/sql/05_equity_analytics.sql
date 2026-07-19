-- 05_equity_analytics.sql
-- Per-security equity analytics from stg_equity_prices.
--   * returns from adj_close: 1-day, and trailing 21 / 63 / 252 trading days (~1m/3m/1y)
--   * vol_21d : 21-day rolling volatility of daily returns
--   * ma_50 / ma_200 : moving averages (trend anchors)
--   * gbp_adj_close : adj_close converted to sterling
--        GBp (pence) -> /100 ; USD/EUR -> x the GBP cross-rate from fct_fx
--        (matched by an ASOF join to the most recent FX row on/before the price date)
-- Depends on: stg_equity_prices, dim_security, fct_fx. Rebuilt each run (idempotent).

DROP TABLE IF EXISTS fct_equity_analytics;

CREATE TABLE fct_equity_analytics AS
WITH px AS (
    SELECT p.ticker, p.price_date, p.close, p.adj_close,
           d.currency, d."group" AS grp, d.sector
    FROM stg_equity_prices p
    JOIN dim_security d USING (ticker)
),
converted AS (
    SELECT
        px.*,
        CASE px.currency
            WHEN 'GBP' THEN px.adj_close
            WHEN 'GBp' THEN px.adj_close / 100.0
            WHEN 'USD' THEN px.adj_close * f.gbp_per_usd
            WHEN 'EUR' THEN px.adj_close * f.gbp_per_eur
        END AS gbp_adj_close
    FROM px
    ASOF LEFT JOIN fct_fx f ON px.price_date >= f.date
),
windowed AS (
    SELECT
        converted.*,
        adj_close / LAG(adj_close)      OVER w - 1 AS ret_1d,
        adj_close / LAG(adj_close, 21)  OVER w - 1 AS ret_21d,
        adj_close / LAG(adj_close, 63)  OVER w - 1 AS ret_63d,
        adj_close / LAG(adj_close, 252) OVER w - 1 AS ret_252d,
        AVG(adj_close) OVER (PARTITION BY ticker ORDER BY price_date
                             ROWS BETWEEN 49  PRECEDING AND CURRENT ROW) AS ma_50,
        AVG(adj_close) OVER (PARTITION BY ticker ORDER BY price_date
                             ROWS BETWEEN 199 PRECEDING AND CURRENT ROW) AS ma_200
    FROM converted
    WINDOW w AS (PARTITION BY ticker ORDER BY price_date)
),
vol AS (
    SELECT
        windowed.*,
        STDDEV_SAMP(ret_1d) OVER (PARTITION BY ticker ORDER BY price_date
                                  ROWS BETWEEN 20 PRECEDING AND CURRENT ROW) AS vol_21d
    FROM windowed
)
SELECT
    ticker, price_date, close, adj_close, currency, grp AS "group", sector,
    gbp_adj_close, ret_1d, ret_21d, ret_63d, ret_252d, vol_21d, ma_50, ma_200
FROM vol
ORDER BY ticker, price_date;
