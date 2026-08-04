-- 11_positioning.sql
-- CFTC positioning as one row per (market, report_date). Derives net speculative
-- positioning (Leveraged Funds first-class, Asset Managers alongside), normalises
-- it by open interest, and attaches EXPANDING point-in-time extremes - a z-score
-- and a point-in-time percentile of the net position within each market's own
-- history - plus week-over-week velocity. Rebuilt each run (idempotent).
--
-- Point-in-time: the expanding window and the percentile both use only rows up to
-- and including the current week, so "is this net position extreme versus how this
-- market has ever been positioned?" is answerable without look-ahead. available_from
-- (the Friday release) is carried through for the snapshot's point-in-time join.

DROP TABLE IF EXISTS fct_positioning;

CREATE TABLE fct_positioning AS
WITH base AS (
    SELECT
        market_id, market, report_date, available_from, open_interest,
        lev_long - lev_short AS net_lev,
        am_long  - am_short  AS net_am
    FROM stg_cot
),
enriched AS (
    SELECT
        b.*,
        net_lev / NULLIF(open_interest, 0) AS net_lev_pct_oi,
        net_am  / NULLIF(open_interest, 0) AS net_am_pct_oi,
        (net_lev - AVG(net_lev) OVER w)
            / NULLIF(STDDEV_SAMP(net_lev) OVER w, 0) AS net_lev_z,
        (net_am  - AVG(net_am)  OVER w)
            / NULLIF(STDDEV_SAMP(net_am)  OVER w, 0) AS net_am_z,
        net_lev - LAG(net_lev) OVER (PARTITION BY market_id ORDER BY report_date) AS net_lev_wow
    FROM base b
    WINDOW w AS (PARTITION BY market_id ORDER BY report_date
                 ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW)
)
SELECT
    e.*,
    CAST((SELECT count(*) FROM base p
            WHERE p.market_id = e.market_id
              AND p.report_date <= e.report_date
              AND p.net_lev <= e.net_lev) AS DOUBLE)
    / NULLIF((SELECT count(*) FROM base q
                WHERE q.market_id = e.market_id
                  AND q.report_date <= e.report_date), 0) AS net_lev_pctile
FROM enriched e
ORDER BY market_id, report_date;
