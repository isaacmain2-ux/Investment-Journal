-- 02_curve.sql
-- The yield curve as one row per date. Pivots the individual rate series into
-- columns, exposes FRED's authoritative slope/breakeven series directly, and
-- adds the real/nominal split and a cross-check slope computed from the levels.
-- Rebuilt each run (idempotent).

DROP TABLE IF EXISTS fct_curve;

CREATE TABLE fct_curve AS
WITH pivoted AS (
    SELECT
        obs_date AS date,
        MAX(CASE WHEN series_id = 'DGS3MO'      THEN value END) AS y3m,
        MAX(CASE WHEN series_id = 'DGS2'        THEN value END) AS y2,
        MAX(CASE WHEN series_id = 'DGS5'        THEN value END) AS y5,
        MAX(CASE WHEN series_id = 'DGS10'       THEN value END) AS y10,
        MAX(CASE WHEN series_id = 'DGS30'       THEN value END) AS y30,
        MAX(CASE WHEN series_id = 'T10Y2Y'      THEN value END) AS slope_2s10s,
        MAX(CASE WHEN series_id = 'T10Y3M'      THEN value END) AS slope_3m10y,
        MAX(CASE WHEN series_id = 'DFII10'      THEN value END) AS real_10y,
        MAX(CASE WHEN series_id = 'T10YIE'      THEN value END) AS breakeven_10y,
        MAX(CASE WHEN series_id = 'THREEFYTP10' THEN value END) AS term_premium_10y
    FROM stg_fred_observations
    WHERE series_id IN ('DGS3MO','DGS2','DGS5','DGS10','DGS30',
                        'T10Y2Y','T10Y3M','DFII10','T10YIE','THREEFYTP10')
    GROUP BY obs_date
)
SELECT
    *,
    y10 - y2 AS slope_2s10s_calc      -- cross-check vs FRED's T10Y2Y
FROM pivoted
ORDER BY date;
