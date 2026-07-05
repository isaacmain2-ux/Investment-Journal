-- 01_series_analytics.sql
-- Per-series enrichment for every FRED series in the warehouse.
-- Computes, for each (series, date):
--   * period change (chg) and period % change (chg_pct) vs the previous observation
--   * calendar-matched year-over-year change (chg_yoy) via an ASOF join to the
--     most recent observation on or before one year earlier (works for any freq)
--   * an EXPANDING, point-in-time z-score (value vs the series' own history TO DATE)
--   * a 21-observation rolling volatility of period returns (chiefly for daily series)
-- All values use only data up to and including their own date (no look-ahead).
-- The table is dropped and rebuilt each run, so the transform is idempotent.

DROP TABLE IF EXISTS fct_series_analytics;

CREATE TABLE fct_series_analytics AS
WITH base AS (
    SELECT
        o.series_id,
        o.obs_date,
        o.value,
        d.freq,
        d."transform" AS intended_transform
    FROM stg_fred_observations o
    JOIN dim_fred_series d USING (series_id)
),
windowed AS (
    SELECT
        base.*,
        LAG(value) OVER w                                 AS prev_value,
        value - LAG(value) OVER w                         AS chg,
        CASE WHEN LAG(value) OVER w <> 0
             THEN value / LAG(value) OVER w - 1
        END                                               AS chg_pct,
        AVG(value)         OVER hist                      AS hist_mean,
        STDDEV_SAMP(value) OVER hist                      AS hist_sd
    FROM base
    WINDOW
        w    AS (PARTITION BY series_id ORDER BY obs_date),
        hist AS (PARTITION BY series_id ORDER BY obs_date
                 ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW)
),
rolled AS (
    SELECT
        windowed.*,
        STDDEV_SAMP(chg_pct) OVER (
            PARTITION BY series_id ORDER BY obs_date
            ROWS BETWEEN 20 PRECEDING AND CURRENT ROW
        ) AS roll_vol_21
    FROM windowed
),
yoy AS (
    SELECT
        r.*,
        p.value AS value_1y_ago,
        CASE WHEN p.value IS NOT NULL AND p.value <> 0
             THEN r.value / p.value - 1
        END AS chg_yoy
    FROM rolled r
    ASOF LEFT JOIN rolled p
      ON p.series_id = r.series_id
     AND p.obs_date <= r.obs_date - INTERVAL 1 YEAR
)
SELECT
    series_id,
    obs_date,
    value,
    prev_value,
    chg,
    chg_pct,
    value_1y_ago,
    chg_yoy,
    CASE WHEN hist_sd IS NOT NULL AND hist_sd <> 0
         THEN (value - hist_mean) / hist_sd
    END AS zscore,
    roll_vol_21,
    freq,
    intended_transform
FROM yoy
ORDER BY series_id, obs_date;
