-- 07_valuation.sql
-- Valuation YIELDS for the watchlist - the currency-safe way to mix price with
-- earnings. Price is already sterling (fct_equity_analytics.gbp_adj_close, which
-- handled the pence /100 and FX). The reporting-currency fundamentals are converted
-- to GBP via fct_fx, so numerator and denominator finally share a currency.
--
--   market_cap_gbp = gbp_adj_close x shares_outstanding
--   earnings_yield = net_income(->GBP)     / market_cap_gbp   (inverse P/E; higher = cheaper)
--   sales_yield    = revenue(->GBP)        / market_cap_gbp
--   fcf_yield      = free_cash_flow(->GBP) / market_cap_gbp
--   value_raw      = mean of whichever yields exist
--
-- Fundamentals are joined POINT-IN-TIME (ASOF on available_from). Anything with an
-- unresolved currency, missing shares, or a missing figure yields NULL - never a
-- wrong number. Reporting currency is major units (USD/EUR/GBP), never pence, so no
-- /100 here (that already happened to the price).
--
-- Depends on: fct_equity_analytics, fct_fundamentals, dim_company_meta, fct_fx.
-- Rebuilt each run (idempotent).

DROP TABLE IF EXISTS fct_valuation;

CREATE TABLE fct_valuation AS
WITH px AS (
    SELECT ticker, price_date, gbp_adj_close
    FROM fct_equity_analytics
    WHERE "group" = 'watchlist'
),
withfund AS (
    SELECT px.ticker, px.price_date, px.gbp_adj_close,
           f.revenue, f.net_income, f.free_cash_flow
    FROM px
    ASOF LEFT JOIN fct_fundamentals f
      ON f.ticker = px.ticker
     AND f.available_from <= px.price_date
),
withmeta AS (
    SELECT withfund.*, m.financial_currency, m.shares_outstanding
    FROM withfund
    LEFT JOIN dim_company_meta m USING (ticker)
),
withfx AS (
    SELECT withmeta.*, x.gbp_per_usd, x.gbp_per_eur
    FROM withmeta
    ASOF LEFT JOIN fct_fx x
      ON withmeta.price_date >= x.date
),
converted AS (
    SELECT
        ticker, price_date,
        gbp_adj_close * shares_outstanding AS market_cap_gbp,
        CASE financial_currency
            WHEN 'GBP' THEN 1.0
            WHEN 'USD' THEN gbp_per_usd
            WHEN 'EUR' THEN gbp_per_eur
        END AS fx_to_gbp,
        revenue, net_income, free_cash_flow
    FROM withfx
),
yields AS (
    SELECT
        ticker, price_date, market_cap_gbp,
        net_income     * fx_to_gbp / NULLIF(market_cap_gbp, 0) AS earnings_yield,
        revenue        * fx_to_gbp / NULLIF(market_cap_gbp, 0) AS sales_yield,
        free_cash_flow * fx_to_gbp / NULLIF(market_cap_gbp, 0) AS fcf_yield
    FROM converted
)
SELECT
    yields.*,
    (COALESCE(earnings_yield, 0) + COALESCE(sales_yield, 0) + COALESCE(fcf_yield, 0))
    / NULLIF((CASE WHEN earnings_yield IS NULL THEN 0 ELSE 1 END)
           + (CASE WHEN sales_yield    IS NULL THEN 0 ELSE 1 END)
           + (CASE WHEN fcf_yield      IS NULL THEN 0 ELSE 1 END), 0) AS value_raw
FROM yields
ORDER BY ticker, price_date;
