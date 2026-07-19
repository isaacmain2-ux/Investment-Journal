-- 07_factor_scores.sql
-- Cross-sectional factor scores for the watchlist: each stock ranked against the
-- OTHER watchlist stocks on the same date (not against its own history).
--   * momentum  : trailing 12-month return (ret_252d)
--   * low-vol   : 21-day volatility, INVERTED (lower vol -> higher score)
--   * trend     : distance above the 200-day moving average (adj_close/ma_200 - 1)
-- Each raw factor is turned into a cross-sectional z-score (vs the peer group that
-- day); composite_z is their average - a simple multi-factor screen where a high
-- score = strong momentum, low vol, and a strong uptrend relative to peers.
-- Price-based only for now (value/quality need fundamentals - Phase 1b-2).
-- Depends on: fct_equity_analytics (built by 05). Rebuilt each run (idempotent).

DROP TABLE IF EXISTS fct_factor_scores;

CREATE TABLE fct_factor_scores AS
WITH base AS (
    SELECT
        ticker, price_date, sector,
        ret_252d AS mom_raw,
        vol_21d  AS vol_raw,
        CASE WHEN ma_200 IS NOT NULL AND ma_200 <> 0
             THEN adj_close / ma_200 - 1 END AS trend_raw
    FROM fct_equity_analytics
    WHERE "group" = 'watchlist'
),
scored AS (
    SELECT
        base.*,
        (mom_raw   - AVG(mom_raw)   OVER d) / NULLIF(STDDEV_SAMP(mom_raw)   OVER d, 0) AS mom_z,
        (vol_raw   - AVG(vol_raw)   OVER d) / NULLIF(STDDEV_SAMP(vol_raw)   OVER d, 0) AS vol_z,
        (trend_raw - AVG(trend_raw) OVER d) / NULLIF(STDDEV_SAMP(trend_raw) OVER d, 0) AS trend_z
    FROM base
    WINDOW d AS (PARTITION BY price_date)
)
SELECT
    ticker, price_date, sector,
    mom_raw, vol_raw, trend_raw,
    mom_z,
    -vol_z AS lowvol_z,                              -- lower vol -> higher score
    trend_z,
    (mom_z + (-vol_z) + trend_z) / 3.0 AS composite_z
FROM scored
ORDER BY price_date, composite_z DESC;
