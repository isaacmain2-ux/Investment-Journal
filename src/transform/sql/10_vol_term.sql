-- 10_vol_term.sql
-- Volatility term structure & cross-asset vol as one row per date. Pivots the
-- CBOE volatility indices into columns and derives the VIX term-structure ratio
-- (contango vs backwardation) and a banded state. Rebuilt each run (idempotent).
--
-- The core signal is vix_ts_ratio = VIX / VIX3M:
--   < 0.95  contango       (calm, upward-sloping vol curve)
--   >= 1.00 backwardation  (stress, inverted vol curve - near-term fear)
-- Only VIX (already ingested) and VXVCLS are required for it; every other column
-- is optional and simply NULLs out if that series has not been ingested.

DROP TABLE IF EXISTS fct_vol_term;

CREATE TABLE fct_vol_term AS
WITH pivoted AS (
    SELECT
        obs_date AS date,
        MAX(CASE WHEN series_id = 'VIXCLS'   THEN value END) AS vix,
        MAX(CASE WHEN series_id = 'VXVCLS'   THEN value END) AS vix3m,
        MAX(CASE WHEN series_id = 'OVXCLS'   THEN value END) AS ovx,
        MAX(CASE WHEN series_id = 'GVZCLS'   THEN value END) AS gvz,
        MAX(CASE WHEN series_id = 'VXEEMCLS' THEN value END) AS vxeem,
        MAX(CASE WHEN series_id = 'EVZCLS'   THEN value END) AS evz,
        MAX(CASE WHEN series_id = 'VXNCLS'   THEN value END) AS vxn,
        MAX(CASE WHEN series_id = 'RVXCLS'   THEN value END) AS rvx
    FROM stg_fred_observations
    WHERE series_id IN ('VIXCLS','VXVCLS','OVXCLS','GVZCLS',
                        'VXEEMCLS','EVZCLS','VXNCLS','RVXCLS')
    GROUP BY obs_date
),
ratios AS (
    SELECT
        *,
        vix  / NULLIF(vix3m, 0) AS vix_ts_ratio       -- contango / backwardation
    FROM pivoted
)
SELECT
    *,
    CASE
        WHEN vix_ts_ratio IS NULL       THEN NULL
        WHEN vix_ts_ratio >= 1.00       THEN 'backwardation'
        WHEN vix_ts_ratio >= 0.95       THEN 'flat'
        ELSE                                 'contango'
    END AS ts_state
FROM ratios
ORDER BY date;
