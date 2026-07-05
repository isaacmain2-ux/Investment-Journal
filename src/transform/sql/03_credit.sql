-- 03_credit.sql
-- Credit conditions as one row per date. Pivots the ICE BofA OAS series into
-- columns, derives the risk-appetite gauges (IG-HY spread, quality spread), and
-- attaches EXPANDING point-in-time z-scores of those derived spreads so "tight
-- vs cheap vs history" is answerable. Rebuilt each run (idempotent).

DROP TABLE IF EXISTS fct_credit;

CREATE TABLE fct_credit AS
WITH pivoted AS (
    SELECT
        obs_date AS date,
        MAX(CASE WHEN series_id = 'BAMLC0A0CM'    THEN value END) AS ig_oas,
        MAX(CASE WHEN series_id = 'BAMLH0A0HYM2'  THEN value END) AS hy_oas,
        MAX(CASE WHEN series_id = 'BAMLC0A1CAAA'  THEN value END) AS aaa_oas,
        MAX(CASE WHEN series_id = 'BAMLC0A4CBBB'  THEN value END) AS bbb_oas,
        MAX(CASE WHEN series_id = 'BAMLH0A1HYBB'  THEN value END) AS bb_oas,
        MAX(CASE WHEN series_id = 'BAMLH0A3HYC'   THEN value END) AS ccc_oas,
        MAX(CASE WHEN series_id = 'BAMLEMCBPIOAS' THEN value END) AS em_oas
    FROM stg_fred_observations
    WHERE series_id IN ('BAMLC0A0CM','BAMLH0A0HYM2','BAMLC0A1CAAA','BAMLC0A4CBBB',
                        'BAMLH0A1HYBB','BAMLH0A3HYC','BAMLEMCBPIOAS')
    GROUP BY obs_date
),
spreads AS (
    SELECT
        *,
        hy_oas - ig_oas   AS ig_hy_spread,
        ccc_oas - bb_oas  AS quality_spread
    FROM pivoted
)
SELECT
    *,
    (ig_hy_spread - AVG(ig_hy_spread) OVER w)
        / NULLIF(STDDEV_SAMP(ig_hy_spread) OVER w, 0)      AS ig_hy_spread_z,
    (quality_spread - AVG(quality_spread) OVER w)
        / NULLIF(STDDEV_SAMP(quality_spread) OVER w, 0)    AS quality_spread_z
FROM spreads
WINDOW w AS (ORDER BY date ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW)
ORDER BY date;
