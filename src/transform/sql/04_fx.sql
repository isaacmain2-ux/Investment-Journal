-- 04_fx.sql
-- FX as one row per date, expressed for a GBP base. FRED provides the USD pairs
-- (USD per GBP, USD per EUR) and derives the sterling cross-rates the rest of
-- the project needs. Rebuilt each run (idempotent).
--   gbp_per_usd = 1 / (USD per GBP)
--   eur_per_gbp = (USD per GBP) / (USD per EUR)
--   gbp_per_eur = (USD per EUR) / (USD per GBP)

DROP TABLE IF EXISTS fct_fx;

CREATE TABLE fct_fx AS
WITH pivoted AS (
    SELECT
        obs_date AS date,
        MAX(CASE WHEN series_id = 'DEXUSUK' THEN value END) AS usd_per_gbp,
        MAX(CASE WHEN series_id = 'DEXUSEU' THEN value END) AS usd_per_eur
    FROM stg_fred_observations
    WHERE series_id IN ('DEXUSUK','DEXUSEU')
    GROUP BY obs_date
)
SELECT
    date,
    usd_per_gbp,
    usd_per_eur,
    CASE WHEN usd_per_gbp <> 0 THEN 1.0 / usd_per_gbp END          AS gbp_per_usd,
    CASE WHEN usd_per_eur <> 0 THEN usd_per_gbp / usd_per_eur END  AS eur_per_gbp,
    CASE WHEN usd_per_gbp <> 0 THEN usd_per_eur / usd_per_gbp END  AS gbp_per_eur
FROM pivoted
ORDER BY date;
