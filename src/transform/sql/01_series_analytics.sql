-- 01_series_analytics.sql
-- Per-series enrichment for every FRED series in the warehouse.
-- For each (series, date) it computes:
--   * period change (chg) and period % change (chg_pct) vs the previous observation
--   * calendar-matched year-over-year change (chg_yoy) via an ASOF join to the most
--     recent observation on or before one year earlier (correct for any frequency)
--   * zscore        : EXPANDING point-in-time z-score of the raw level
--   * primary_value : the analytically-correct representation, chosen by the series'
--                     intended_transform  (level -> value, yoy -> chg_yoy, mom -> chg)
--   * primary_zscore: EXPANDING point-in-time z-score of primary_value  <-- use this one
--   * roll_vol_21   : 21-observation rolling volatility of period returns (daily series)
-- All values use only data up to and including their own date (no look-ahead).
-- Dropped and rebuilt each run (idempotent).

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
),
prim AS (
    SELECT
        yoy.*,
        CASE intended_transform
             WHEN 'yoy' THEN chg_yoy
             WHEN 'mom' THEN chg
             ELSE value
        END AS primary_value
    FROM yoy
),
prim_z AS (
    SELECT
        prim.*,
        AVG(primary_value)         OVER pw AS prim_mean,
        STDDEV_SAMP(primary_value) OVER pw AS prim_sd
    FROM prim
    WINDOW pw AS (PARTITION BY series_id ORDER BY obs_date
                  ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW)
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
    primary_value,
    CASE WHEN prim_sd IS NOT NULL AND prim_sd <> 0
         THEN (primary_value - prim_mean) / prim_sd
    END AS primary_zscore,
    roll_vol_21,
    freq,
    intended_transform
FROM prim_z
ORDER BY series_id, obs_date;
