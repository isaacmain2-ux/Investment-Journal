-- 08_factor_scores.sql
-- Cross-sectional factor scores for the watchlist: each stock ranked against the
-- OTHER watchlist stocks on the same date (not against its own history).
--
-- PRICE factors (fct_equity_analytics):
--   momentum : trailing 12-month return | low-vol : 21-day vol INVERTED | trend : vs 200d MA
-- FUNDAMENTAL factors (fct_fundamentals, joined POINT-IN-TIME on available_from):
--   quality  : net margin + return on equity
--   growth   : revenue growth + EPS growth
-- VALUE factor (fct_valuation, currency-safe yields):
--   value    : mean of earnings / sales / FCF yields (higher yield = cheaper)
--
-- composite_z averages whichever factor z-scores exist for a stock, so a company
-- missing a factor (banks: no gross margin; unresolved currency: no value) still
-- scores on the rest rather than dropping out.
--
-- Depends on: fct_equity_analytics, fct_fundamentals, fct_valuation. Idempotent.

DROP TABLE IF EXISTS fct_factor_scores;

CREATE TABLE fct_factor_scores AS
WITH px AS (
    SELECT
        ticker, price_date, sector,
        ret_252d AS mom_raw,
        vol_21d  AS vol_raw,
        CASE WHEN ma_200 IS NOT NULL AND ma_200 <> 0
             THEN adj_close / ma_200 - 1 END AS trend_raw
    FROM fct_equity_analytics
    WHERE "group" = 'watchlist'
),
joined AS (
    SELECT
        px.*,
        f.period_end AS fund_period_end,
        f.net_margin, f.roe, f.revenue_growth_yoy, f.eps_growth_yoy,
        v.value_raw
    FROM px
    ASOF LEFT JOIN fct_fundamentals f
      ON f.ticker = px.ticker
     AND f.available_from <= px.price_date
    LEFT JOIN fct_valuation v
      ON v.ticker = px.ticker AND v.price_date = px.price_date
),
raw_factors AS (
    SELECT
        joined.*,
        (COALESCE(net_margin, 0) + COALESCE(roe, 0))
            / NULLIF((CASE WHEN net_margin IS NULL THEN 0 ELSE 1 END)
                   + (CASE WHEN roe IS NULL THEN 0 ELSE 1 END), 0) AS quality_raw,
        (COALESCE(revenue_growth_yoy, 0) + COALESCE(eps_growth_yoy, 0))
            / NULLIF((CASE WHEN revenue_growth_yoy IS NULL THEN 0 ELSE 1 END)
                   + (CASE WHEN eps_growth_yoy IS NULL THEN 0 ELSE 1 END), 0) AS growth_raw
    FROM joined
),
scored AS (
    SELECT
        raw_factors.*,
        (mom_raw     - AVG(mom_raw)     OVER d) / NULLIF(STDDEV_SAMP(mom_raw)     OVER d, 0) AS mom_z,
        (vol_raw     - AVG(vol_raw)     OVER d) / NULLIF(STDDEV_SAMP(vol_raw)     OVER d, 0) AS vol_z,
        (trend_raw   - AVG(trend_raw)   OVER d) / NULLIF(STDDEV_SAMP(trend_raw)   OVER d, 0) AS trend_z,
        (quality_raw - AVG(quality_raw) OVER d) / NULLIF(STDDEV_SAMP(quality_raw) OVER d, 0) AS quality_z,
        (growth_raw  - AVG(growth_raw)  OVER d) / NULLIF(STDDEV_SAMP(growth_raw)  OVER d, 0) AS growth_z,
        (value_raw   - AVG(value_raw)   OVER d) / NULLIF(STDDEV_SAMP(value_raw)   OVER d, 0) AS value_z
    FROM raw_factors
    WINDOW d AS (PARTITION BY price_date)
),
final AS (
    SELECT
        ticker, price_date, sector, fund_period_end,
        mom_raw, vol_raw, trend_raw, quality_raw, growth_raw, value_raw,
        mom_z,
        -vol_z AS lowvol_z,
        trend_z, quality_z, growth_z, value_z
    FROM scored
)
SELECT
    final.*,
    (COALESCE(mom_z, 0) + COALESCE(lowvol_z, 0) + COALESCE(trend_z, 0)
     + COALESCE(quality_z, 0) + COALESCE(growth_z, 0) + COALESCE(value_z, 0))
    / NULLIF((CASE WHEN mom_z     IS NULL THEN 0 ELSE 1 END)
           + (CASE WHEN lowvol_z  IS NULL THEN 0 ELSE 1 END)
           + (CASE WHEN trend_z   IS NULL THEN 0 ELSE 1 END)
           + (CASE WHEN quality_z IS NULL THEN 0 ELSE 1 END)
           + (CASE WHEN growth_z  IS NULL THEN 0 ELSE 1 END)
           + (CASE WHEN value_z   IS NULL THEN 0 ELSE 1 END), 0) AS composite_z
FROM final
ORDER BY price_date, composite_z DESC;
