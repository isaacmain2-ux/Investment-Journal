-- 12_skew.sql
-- Options skew as one row per (ticker, capture_date). Carries the raw skew measures
-- and attaches EXPANDING point-in-time extremes - a z-score and a point-in-time
-- percentile of put_skew within each ticker's own accumulated history - plus the
-- day-over-day change. Rebuilt each run (idempotent).
--
-- This layer accumulates its own history (Yahoo serves only the current chain), so
-- the z-score and percentile are thin or NULL at first and become meaningful only
-- after enough captures. The expanding window and percentile use only rows up to and
-- including the current capture, so they are point-in-time by construction.

DROP TABLE IF EXISTS fct_skew;

CREATE TABLE fct_skew AS
WITH base AS (
    SELECT ticker_id, ticker, capture_date, expiry, dte, spot,
           atm_iv, put_iv, call_iv, put_skew, risk_reversal
    FROM stg_options_skew
),
enriched AS (
    SELECT
        b.*,
        (put_skew - AVG(put_skew) OVER w)
            / NULLIF(STDDEV_SAMP(put_skew) OVER w, 0) AS put_skew_z,
        (risk_reversal - AVG(risk_reversal) OVER w)
            / NULLIF(STDDEV_SAMP(risk_reversal) OVER w, 0) AS rr_z,
        put_skew - LAG(put_skew) OVER (PARTITION BY ticker_id ORDER BY capture_date) AS put_skew_chg
    FROM base b
    WINDOW w AS (PARTITION BY ticker_id ORDER BY capture_date
                 ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW)
)
SELECT
    e.*,
    CAST((SELECT count(*) FROM base p
            WHERE p.ticker_id = e.ticker_id
              AND p.capture_date <= e.capture_date
              AND p.put_skew <= e.put_skew) AS DOUBLE)
    / NULLIF((SELECT count(*) FROM base q
                WHERE q.ticker_id = e.ticker_id
                  AND q.capture_date <= e.capture_date), 0) AS put_skew_pctile
FROM enriched e
ORDER BY ticker_id, capture_date;
