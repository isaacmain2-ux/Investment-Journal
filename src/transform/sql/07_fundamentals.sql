-- 07_fundamentals.sql
-- Annual fundamentals per company: pivots the key line items out of the long
-- staging table and computes CURRENCY-SAFE ratios. Every ratio here divides two
-- figures drawn from the same statement, so numerator and denominator share a
-- currency and no FX conversion is needed. Valuation ratios that mix PRICE with
-- EARNINGS are deliberately NOT here - they need the reporting-currency
-- conversion and arrive in the next step.
--
-- Point-in-time: available_from (period_end + reporting lag) is carried through,
-- so downstream joins use the date the figures were actually public.
--
-- Note: gross and operating margin are NULL for banks (no cost of goods sold).
-- That is correct behaviour, not missing data.
--
-- Depends on: stg_fundamentals. Rebuilt each run (idempotent).

DROP TABLE IF EXISTS fct_fundamentals;

CREATE TABLE fct_fundamentals AS
WITH pivoted AS (
    SELECT
        ticker,
        period_end,
        MAX(available_from) AS available_from,
        MAX(CASE WHEN metric = 'Total Revenue'                  THEN value END) AS revenue,
        MAX(CASE WHEN metric = 'Gross Profit'                   THEN value END) AS gross_profit,
        MAX(CASE WHEN metric = 'Operating Income'               THEN value END) AS operating_income,
        MAX(CASE WHEN metric = 'Net Income Common Stockholders' THEN value END) AS net_income,
        MAX(CASE WHEN metric = 'Diluted EPS'                    THEN value END) AS diluted_eps,
        MAX(CASE WHEN metric = 'Diluted Average Shares'         THEN value END) AS diluted_shares,
        MAX(CASE WHEN metric = 'Total Assets'                   THEN value END) AS total_assets,
        MAX(CASE WHEN metric = 'Stockholders Equity'            THEN value END) AS equity,
        MAX(CASE WHEN metric = 'Total Debt'                     THEN value END) AS total_debt,
        MAX(CASE WHEN metric = 'Operating Cash Flow'            THEN value END) AS operating_cash_flow,
        MAX(CASE WHEN metric = 'Capital Expenditure'            THEN value END) AS capex,
        MAX(CASE WHEN metric = 'Free Cash Flow'                 THEN value END) AS free_cash_flow
    FROM stg_fundamentals
    WHERE freq = 'annual'
    GROUP BY ticker, period_end
),
ratios AS (
    SELECT
        pivoted.*,
        gross_profit     / NULLIF(revenue, 0)      AS gross_margin,
        operating_income / NULLIF(revenue, 0)      AS operating_margin,
        net_income       / NULLIF(revenue, 0)      AS net_margin,
        net_income       / NULLIF(equity, 0)       AS roe,
        net_income       / NULLIF(total_assets, 0) AS roa,
        free_cash_flow   / NULLIF(revenue, 0)      AS fcf_margin,
        total_debt       / NULLIF(equity, 0)       AS debt_to_equity
    FROM pivoted
)
SELECT
    ratios.*,
    revenue     / NULLIF(LAG(revenue)     OVER w, 0) - 1 AS revenue_growth_yoy,
    net_income  / NULLIF(LAG(net_income)  OVER w, 0) - 1 AS net_income_growth_yoy,
    diluted_eps / NULLIF(LAG(diluted_eps) OVER w, 0) - 1 AS eps_growth_yoy
FROM ratios
WINDOW w AS (PARTITION BY ticker ORDER BY period_end)
ORDER BY ticker, period_end;
