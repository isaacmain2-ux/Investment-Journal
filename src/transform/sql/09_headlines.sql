-- 09_headlines.sql
-- Gold model: fct_headlines - one clean, de-duplicated row per FT story.
--
-- Inputs:
--   stg_headlines   append-de-duped staging (one row per item_id already, but
--                   we de-dupe again defensively, keeping the earliest sighting)
--   dim_news_feed   feed -> group/region, mirrored from the manifest
--
-- Transformations: strip any HTML tags from the summary, derive a calendar
-- published_date, and attach the feed's section/region. run_transform ensures
-- both input tables exist, so this builds an empty table on a warehouse that
-- has never ingested news (rather than failing).

DROP TABLE IF EXISTS fct_headlines;

CREATE TABLE fct_headlines AS
WITH deduped AS (
    SELECT *
    FROM stg_headlines
    QUALIFY ROW_NUMBER() OVER (PARTITION BY item_id ORDER BY first_seen_at) = 1
)
SELECT
    h.item_id,
    h.title,
    NULLIF(TRIM(REGEXP_REPLACE(COALESCE(h.summary, ''), '<[^>]+>', '', 'g')), '') AS summary,
    h.link,
    h.published_at,
    CAST(h.published_at AS DATE) AS published_date,
    h.first_feed,
    f.feed_group                 AS section,
    f.region                     AS region,
    h.first_seen_at
FROM deduped h
LEFT JOIN dim_news_feed f ON f.feed = h.first_feed;
