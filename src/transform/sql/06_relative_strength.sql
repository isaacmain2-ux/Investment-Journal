-- 06_relative_strength.sql
-- Sector / style / country rotation: each ETF measured against the market (S&P 500).
--   * rel_close    : the relative-price ratio  (etf adj_close / market adj_close)
--   * excess_Nd    : the ETF's trailing return MINUS the market's, at 21/63/252 days
--                    (positive = outperforming the market over that horizon)
--   * rs_trend_21d : 21-day change in rel_close (is the ETF GAINING ground? = RS momentum)
-- Reading it: positive excess AND positive rs_trend = leading and improving (the sweet
-- spot); negative on both = lagging and weakening.
-- Depends on: fct_equity_analytics (built by 05). Rebuilt each run (idempotent).

DROP TABLE IF EXISTS fct_relative_strength;

CREATE TABLE fct_relative_strength AS
WITH mkt AS (
    SELECT price_date,
           adj_close AS mkt_close,
           ret_21d   AS mkt_ret_21d,
           ret_63d   AS mkt_ret_63d,
           ret_252d  AS mkt_ret_252d
    FROM fct_equity_analytics
    WHERE ticker = '^GSPC'
),
rel AS (
    SELECT
        e.ticker,
        e.price_date,
        e."group",
        e.sector,
        e.adj_close,
        m.mkt_close,
        e.adj_close / m.mkt_close   AS rel_close,
        e.ret_21d  - m.mkt_ret_21d  AS excess_21d,
        e.ret_63d  - m.mkt_ret_63d  AS excess_63d,
        e.ret_252d - m.mkt_ret_252d AS excess_252d
    FROM fct_equity_analytics e
    JOIN mkt m USING (price_date)
    WHERE e."group" IN ('sector_etfs', 'style_etfs', 'country_etfs')
)
SELECT
    rel.*,
    rel_close / LAG(rel_close, 21) OVER (PARTITION BY ticker ORDER BY price_date) - 1
        AS rs_trend_21d
FROM rel
ORDER BY ticker, price_date;
