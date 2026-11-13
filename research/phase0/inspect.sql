-- Phase 0: read-only inspection of the production database.
-- Prints aggregates only (no user/account tables are touched).
--
-- Run on the server from the repo root:
--   docker compose -f docker-compose.prod.yml exec -T db \
--     psql -U postgres -d insider_platform -f - < research/phase0/inspect.sql > phase0_output.txt 2>&1
--
-- NOTE: dates and timestamps are stored as TEXT (ISO strings) in this schema,
-- and a few carry a timezone suffix (e.g. 2025-08-29-05:00), so every cast
-- takes the first 10 characters and is guarded by a pattern check.

\pset pager off
\timing off
SET default_transaction_read_only = on;   -- every statement below is read-only

\echo '===== A1. Tables: estimated rows and size ====='
SELECT c.relname AS table_name,
       c.reltuples::bigint AS est_rows,
       pg_size_pretty(pg_total_relation_size(c.oid)) AS total_size
FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE n.nspname = 'public' AND c.relkind = 'r'
ORDER BY pg_total_relation_size(c.oid) DESC;

\echo '===== A2. Columns that exist in the live DB (to catch drift from schema.py) ====='
SELECT table_name, string_agg(column_name || ':' || data_type, ', ' ORDER BY ordinal_position) AS columns
FROM information_schema.columns
WHERE table_schema = 'public'
  AND table_name IN ('filings','insider_events','event_outcomes','issuer_prices_daily',
                     'benchmark_prices_daily','ai_outputs','insider_issuer_stats',
                     'issuer_master','market_cap_cache','issuer_fundamentals_cache','jobs')
GROUP BY table_name ORDER BY table_name;

\echo '===== B1. Filings by year and form type (4 vs 4/A) ====='
SELECT LEFT(filing_date,4) AS yr, form_type, COUNT(*) AS n
FROM filings GROUP BY 1,2 ORDER BY 1,2;

\echo '===== B2. Events by year: all / buys (code P) / sells (code S) ====='
SELECT LEFT(filing_date,4) AS yr,
       COUNT(*) AS events,
       SUM(has_buy) AS buys,
       SUM(has_sell) AS sells,
       COUNT(DISTINCT issuer_cik) FILTER (WHERE has_buy=1) AS issuers_with_buys
FROM insider_events GROUP BY 1 ORDER BY 1;

\echo '===== B3. Who are the buyers? (role flags; 10% owners are mostly funds) ====='
SELECT COALESCE(is_officer,0) AS officer, COALESCE(is_director,0) AS director,
       COALESCE(is_ten_percent_owner,0) AS ten_pct, COUNT(*) AS buys,
       ROUND(AVG(buy_dollars_total)::numeric,0) AS avg_dollars,
       PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY buy_dollars_total) AS median_dollars
FROM insider_events WHERE has_buy=1 GROUP BY 1,2,3 ORDER BY buys DESC;

\echo '===== B4. Owner identity quality (cik vs name-hash vs unknown keys) ====='
SELECT CASE WHEN owner_key LIKE 'namehash:%' THEN 'namehash'
            WHEN owner_key LIKE 'unknown:%' THEN 'unknown'
            ELSE 'cik' END AS key_type,
       COUNT(*) AS buy_events, COUNT(DISTINCT owner_key) AS distinct_owners
FROM insider_events WHERE has_buy=1 GROUP BY 1;

\echo '===== B5. Buys per insider (how many insiders even HAVE a track record?) ====='
WITH per AS (
  SELECT owner_key, COUNT(*) AS n FROM insider_events WHERE has_buy=1 GROUP BY 1
)
SELECT CASE WHEN n=1 THEN '1' WHEN n=2 THEN '2' WHEN n<=4 THEN '3-4'
            WHEN n<=9 THEN '5-9' WHEN n<=19 THEN '10-19' ELSE '20+' END AS buys_per_insider,
       COUNT(*) AS insiders, SUM(n) AS buy_events
FROM per GROUP BY 1 ORDER BY MIN(n);

\echo '===== B6. Amendments: 4/A buy events, and how many restate an earlier Form 4 buy ====='
SELECT COUNT(*) AS amended_buy_events,
       COUNT(*) FILTER (WHERE EXISTS (
          SELECT 1 FROM insider_events e2 JOIN filings f2 USING (accession_number)
          WHERE e2.issuer_cik=e.issuer_cik AND e2.owner_key=e.owner_key AND e2.has_buy=1
            AND e2.buy_trade_date=e.buy_trade_date AND f2.form_type='4'
            AND e2.accession_number<>e.accession_number)) AS with_matching_original
FROM insider_events e JOIN filings f USING (accession_number)
WHERE e.has_buy=1 AND f.form_type LIKE '4/A%';

\echo '===== B7. Possible duplicate buys (same issuer+owner+trade date+shares, different accession) ====='
SELECT COUNT(*) AS duplicate_groups, COALESCE(SUM(n),0) AS events_involved FROM (
  SELECT COUNT(*) AS n FROM insider_events WHERE has_buy=1
  GROUP BY issuer_cik, owner_key, buy_trade_date, buy_shares_total HAVING COUNT(*)>1
) d;

\echo '===== B7b. Dates that are not plain YYYY-MM-DD ====='
SELECT COUNT(*) FILTER (WHERE filing_date !~ '^\d{4}-\d{2}-\d{2}$') AS odd_filing_dates,
       COUNT(*) FILTER (WHERE buy_trade_date IS NOT NULL AND buy_trade_date !~ '^\d{4}-\d{2}-\d{2}$') AS odd_buy_trade_dates,
       COUNT(*) FILTER (WHERE sell_trade_date IS NOT NULL AND sell_trade_date !~ '^\d{4}-\d{2}-\d{2}$') AS odd_sell_trade_dates
FROM insider_events;

\echo '===== B7c. Buy dollar amounts: how many are implausible? ====='
SELECT COUNT(*) FILTER (WHERE buy_dollars_total >= 1e7)  AS over_10m,
       COUNT(*) FILTER (WHERE buy_dollars_total >= 1e8)  AS over_100m,
       COUNT(*) FILTER (WHERE buy_dollars_total >= 1e9)  AS over_1b,
       COUNT(*) FILTER (WHERE buy_dollars_total >= 1e11) AS over_100b,
       COUNT(*) FILTER (WHERE buy_dollars_total > market_cap AND market_cap > 0) AS over_market_cap,
       COUNT(*) FILTER (WHERE buy_vwap_price >= 10000) AS price_over_10k,
       MAX(buy_dollars_total) AS max_dollars, MAX(buy_vwap_price) AS max_price
FROM insider_events WHERE has_buy=1;

\echo '===== B7d. Is the historical backfill complete? (filing counts by year are very uneven) ====='
SELECT LEFT(filing_date,4) AS yr, status, COUNT(*) AS n, COUNT(DISTINCT issuer_cik) AS issuers
FROM backfill_queue GROUP BY 1,2 ORDER BY 1,2;

SELECT LEFT(filing_date,4) AS yr, COUNT(DISTINCT issuer_cik) AS issuers_with_any_filing
FROM filings GROUP BY 1 ORDER BY 1;

\echo '===== B8. Buy data-quality flags ====='
SELECT COUNT(*) AS buys,
       COUNT(*) FILTER (WHERE buy_dollars_total IS NULL OR buy_dollars_total<=0) AS no_dollars,
       COUNT(*) FILTER (WHERE buy_dollars_total < 5000) AS under_5k,
       COUNT(*) FILTER (WHERE buy_vwap_price < 1) AS vwap_under_1,
       COUNT(*) FILTER (WHERE buy_vwap_is_partial=1) AS partial_price,
       COUNT(*) FILTER (WHERE buy_pct_holdings_change IS NULL) AS no_pct_holdings,
       COUNT(*) FILTER (WHERE has_sell=1) AS also_has_sell,
       COUNT(*) FILTER (WHERE (CASE WHEN filing_date ~ '^\d{4}-\d{2}-\d{2}' THEN LEFT(filing_date,10)::date END) - (CASE WHEN buy_trade_date ~ '^\d{4}-\d{2}-\d{2}' THEN LEFT(buy_trade_date,10)::date END) > 5) AS filed_late_gt5d,
       COUNT(*) FILTER (WHERE (CASE WHEN filing_date ~ '^\d{4}-\d{2}-\d{2}' THEN LEFT(filing_date,10)::date END) < (CASE WHEN buy_trade_date ~ '^\d{4}-\d{2}-\d{2}' THEN LEFT(buy_trade_date,10)::date END)) AS filed_before_trade,
       COUNT(*) FILTER (WHERE ticker IS NULL OR ticker='') AS no_ticker
FROM insider_events WHERE has_buy=1;

\echo '===== C1. Buy outcomes by year: available vs missing ====='
SELECT LEFT(e.filing_date,4) AS yr, COUNT(*) AS buys,
       COUNT(o.accession_number) AS has_outcome_row,
       COUNT(o.excess_return_60d) AS has_ex60,
       COUNT(o.excess_return_180d) AS has_ex180
FROM insider_events e
LEFT JOIN event_outcomes o ON o.issuer_cik=e.issuer_cik AND o.owner_key=e.owner_key
     AND o.accession_number=e.accession_number AND o.side='buy'
WHERE e.has_buy=1 GROUP BY 1 ORDER BY 1;

\echo '===== C2. Why are buy outcomes missing? ====='
SELECT COALESCE(missing_reason_60d,'(present)') AS reason_60d,
       COALESCE(missing_reason_180d,'(present)') AS reason_180d,
       outcomes_version, bench_symbol, COUNT(*) AS n
FROM event_outcomes WHERE side='buy' GROUP BY 1,2,3,4 ORDER BY n DESC;

\echo '===== C3. SURVIVORSHIP: old buys (filed > 1 year ago) with no 180d return, by price-series status ====='
WITH px AS (
  SELECT issuer_cik, MIN(date) AS first_px, MAX(date) AS last_px, COUNT(*) AS n_px
  FROM issuer_prices_daily GROUP BY 1
)
SELECT CASE WHEN px.issuer_cik IS NULL THEN 'no price series at all'
            WHEN (CASE WHEN px.last_px ~ '^\d{4}-\d{2}-\d{2}' THEN LEFT(px.last_px,10)::date END) < CURRENT_DATE - 30 THEN 'series ended (delisted/acquired/stale)'
            WHEN px.first_px > e.filing_date THEN 'series starts after filing'
            ELSE 'series looks live' END AS price_status,
       COUNT(*) AS old_buys_missing_180d, COUNT(DISTINCT e.issuer_cik) AS issuers
FROM insider_events e
LEFT JOIN event_outcomes o ON o.issuer_cik=e.issuer_cik AND o.owner_key=e.owner_key
     AND o.accession_number=e.accession_number AND o.side='buy'
LEFT JOIN px ON px.issuer_cik=e.issuer_cik
WHERE e.has_buy=1 AND (CASE WHEN e.filing_date ~ '^\d{4}-\d{2}-\d{2}' THEN LEFT(e.filing_date,10)::date END) < CURRENT_DATE - 365 AND o.excess_return_180d IS NULL
GROUP BY 1 ORDER BY 2 DESC;

\echo '===== C4. Raw distribution of buy excess returns (look for absurd tails = split/price errors) ====='
SELECT COUNT(*) AS n,
       ROUND(AVG(excess_return_60d)::numeric,4) AS mean60,
       ROUND((PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY excess_return_60d))::numeric,4) AS med60,
       ROUND(AVG((excess_return_60d>0)::int)::numeric,4) AS hit60,
       ROUND(MIN(return_60d)::numeric,3) AS min_r60,
       ROUND((PERCENTILE_CONT(0.001) WITHIN GROUP (ORDER BY return_60d))::numeric,3) AS p0_1,
       ROUND((PERCENTILE_CONT(0.999) WITHIN GROUP (ORDER BY return_60d))::numeric,3) AS p99_9,
       ROUND(MAX(return_60d)::numeric,3) AS max_r60,
       COUNT(*) FILTER (WHERE return_60d > 5) AS r60_over_500pct,
       COUNT(*) FILTER (WHERE p0 < 1) AS anchor_px_under_1
FROM event_outcomes WHERE side='buy' AND excess_return_60d IS NOT NULL;

\echo '===== D1. Price coverage for issuers that have buys ====='
WITH b AS (SELECT DISTINCT issuer_cik FROM insider_events WHERE has_buy=1),
     px AS (SELECT issuer_cik, MIN(date) first_px, MAX(date) last_px, COUNT(*) n_px
            FROM issuer_prices_daily GROUP BY 1)
SELECT COUNT(*) AS issuers_with_buys,
       COUNT(px.issuer_cik) AS with_prices,
       COUNT(*) FILTER (WHERE (CASE WHEN px.last_px ~ '^\d{4}-\d{2}-\d{2}' THEN LEFT(px.last_px,10)::date END) >= CURRENT_DATE - 30) AS series_current,
       COUNT(*) FILTER (WHERE (CASE WHEN px.last_px ~ '^\d{4}-\d{2}-\d{2}' THEN LEFT(px.last_px,10)::date END) <  CURRENT_DATE - 30) AS series_ended,
       COUNT(*) FILTER (WHERE px.n_px < 250) AS under_250_rows
FROM b LEFT JOIN px USING (issuer_cik);

\echo '===== D2. Where do price series end? (year of last price, for ended series) ====='
SELECT LEFT(last_px,4) AS last_price_year, COUNT(*) AS issuers FROM (
  SELECT issuer_cik, MAX(date) AS last_px FROM issuer_prices_daily GROUP BY 1) t
GROUP BY 1 ORDER BY 1;

\echo '===== D3. Price source symbols (suffix tells us the provider/exchange) and tickers per issuer ====='
SELECT COALESCE(SUBSTRING(source_ticker FROM '\.([A-Za-z]+)$'),'(no suffix)') AS suffix,
       COUNT(DISTINCT issuer_cik) AS issuers, COUNT(*) AS price_rows
FROM issuer_prices_daily GROUP BY 1 ORDER BY 3 DESC LIMIT 15;

SELECT n_symbols, COUNT(*) AS issuers FROM (
  SELECT issuer_cik, COUNT(DISTINCT source_ticker) AS n_symbols FROM issuer_prices_daily GROUP BY 1) t
GROUP BY 1 ORDER BY 1;

\echo '===== D4. Stale-adjustment check: 1-day moves of >+150% or <-60% in adj_close (split/adjustment breaks) ====='
WITH r AS (
  SELECT issuer_cik, date, adj_close / NULLIF(LAG(adj_close) OVER (PARTITION BY issuer_cik ORDER BY date),0) - 1 AS ret
  FROM issuer_prices_daily
)
SELECT COUNT(*) AS extreme_days, COUNT(DISTINCT issuer_cik) AS issuers_affected,
       COUNT(*) FILTER (WHERE ret > 1.5) AS jumps_up, COUNT(*) FILTER (WHERE ret < -0.6) AS jumps_down
FROM r WHERE ret > 1.5 OR ret < -0.6;

\echo '===== D5. Benchmark series ====='
SELECT symbol, MIN(date) AS first_dt, MAX(date) AS last_dt, COUNT(*) AS n FROM benchmark_prices_daily GROUP BY 1;

\echo '===== D6. Point-in-time check: is market cap a single current snapshot? ====='
SELECT LEFT(market_cap_updated_at,7) AS snapshot_month, COUNT(*) AS buy_events,
       MIN(filing_date) AS earliest_filing, MAX(filing_date) AS latest_filing
FROM insider_events WHERE has_buy=1 GROUP BY 1 ORDER BY 1;

SELECT market_cap_bucket, COUNT(*) AS buys FROM insider_events WHERE has_buy=1 GROUP BY 1 ORDER BY 2 DESC;

SELECT COUNT(*) AS tickers, COUNT(sector) AS with_sector, COUNT(shares_outstanding) AS with_shares_out,
       MIN(updated_at) AS oldest, MAX(updated_at) AS newest
FROM issuer_fundamentals_cache;

\echo '===== E1. AI outputs: versions, counts, id range ====='
SELECT model_id, prompt_version, input_schema_version, COUNT(*) AS n,
       COUNT(buy_rating) AS with_buy_rating, COUNT(sell_rating) AS with_sell_rating,
       MIN(ai_output_id) AS min_id, MAX(ai_output_id) AS max_id,
       MIN(generated_at) AS min_generated_at, MAX(generated_at) AS max_generated_at
FROM ai_outputs GROUP BY 1,2,3 ORDER BY min_id;

\echo '===== E2. Events with more than one rating (re-runs) ====='
SELECT n_outputs, COUNT(*) AS events FROM (
  SELECT COUNT(*) AS n_outputs FROM ai_outputs GROUP BY issuer_cik, owner_key, accession_number) t
GROUP BY 1 ORDER BY 1;

\echo '===== E3. Buy rating distribution (latest rating on the event) ====='
SELECT FLOOR(ai_buy_rating) AS rating_floor, COUNT(*) AS buys
FROM insider_events WHERE has_buy=1 AND ai_buy_rating IS NOT NULL GROUP BY 1 ORDER BY 1;

\echo '===== E4. LIVE vs BACKFILL (a): rated buys by filing month ====='
SELECT LEFT(filing_date,7) AS filing_month, COUNT(*) AS rated_buys
FROM insider_events WHERE has_buy=1 AND ai_buy_rating IS NOT NULL
GROUP BY 1 ORDER BY 1 DESC LIMIT 40;

SELECT COUNT(*) FILTER (WHERE filing_date <  '2026-02-01') AS rated_buys_filed_before_project_start,
       COUNT(*) FILTER (WHERE filing_date >= '2026-02-01') AS rated_buys_filed_after_project_start
FROM insider_events WHERE has_buy=1 AND ai_buy_rating IS NOT NULL;

\echo '===== E5. LIVE vs BACKFILL (b): lag in days from filing to rating, three different clocks ====='
\echo '  clock 1 = ai_outputs.generated_at  (WRITTEN BY THE MODEL - may be unreliable)'
\echo '  clock 2 = insider_events.ai_computed_at (server clock, latest rating only)'
\echo '  clock 3 = newest server timestamp inside input_json (lower bound on rating time)'
WITH x AS (
  SELECT (CASE WHEN e.filing_date ~ '^\d{4}-\d{2}-\d{2}' THEN LEFT(e.filing_date,10)::date END) AS fd,
         CASE WHEN o.generated_at ~ '^\d{4}-\d{2}-\d{2}' THEN LEFT(o.generated_at,10)::date END AS model_clock,
         CASE WHEN e.ai_computed_at ~ '^\d{4}-\d{2}-\d{2}' THEN LEFT(e.ai_computed_at,10)::date END AS server_clock,
         CASE WHEN (o.input_json::jsonb #>> '{issuer_context,market_cap_updated_at}') ~ '^\d{4}-\d{2}-\d{2}'
              THEN LEFT(o.input_json::jsonb #>> '{issuer_context,market_cap_updated_at}',10)::date END AS input_clock
  FROM ai_outputs o
  JOIN insider_events e USING (issuer_cik, owner_key, accession_number)
  WHERE e.has_buy=1 AND o.buy_rating IS NOT NULL
), lag AS (
  SELECT 'model generated_at' AS clock, model_clock - fd AS d FROM x
  UNION ALL SELECT 'server ai_computed_at', server_clock - fd FROM x
  UNION ALL SELECT 'input_json mcap ts (lower bound)', input_clock - fd FROM x
)
SELECT clock,
       CASE WHEN d IS NULL THEN 'z) unknown' WHEN d < 0 THEN 'a) negative (!)'
            WHEN d <= 3 THEN 'b) 0-3d  (live)' WHEN d <= 14 THEN 'c) 4-14d'
            WHEN d <= 60 THEN 'd) 15-60d' WHEN d <= 180 THEN 'e) 61-180d'
            ELSE 'f) >180d (backfill, outcome already known)' END AS lag_bucket,
       COUNT(*) AS n
FROM lag GROUP BY 1,2 ORDER BY 1,2;

\echo '===== E6. Do the model clock and server clock agree? ====='
SELECT COUNT(*) AS n,
       COUNT(*) FILTER (WHERE ABS(LEFT(ai_generated_at,10)::date - LEFT(ai_computed_at,10)::date) <= 1) AS agree_within_1d,
       COUNT(*) FILTER (WHERE ABS(LEFT(ai_generated_at,10)::date - LEFT(ai_computed_at,10)::date) > 30) AS differ_gt_30d
FROM insider_events
WHERE ai_generated_at ~ '^\d{4}-\d{2}-\d{2}' AND ai_computed_at ~ '^\d{4}-\d{2}-\d{2}';

\echo '===== E7. Are AI job rows still in the jobs table? (a second server clock) ====='
SELECT job_type, status, COUNT(*) AS n, MIN(created_at) AS first_created, MAX(updated_at) AS last_updated
FROM jobs WHERE job_type='RUN_AI_FOR_EVENT' GROUP BY 1,2;

\echo '===== E8. When was rating activity happening? (ai_computed_at by month) ====='
SELECT LEFT(ai_computed_at,7) AS rated_month, COUNT(*) AS events
FROM insider_events WHERE ai_computed_at IS NOT NULL GROUP BY 1 ORDER BY 1;

\echo '===== F1. LEAKAGE: did the model SEE outcome-derived stats? (insider_stats in the stored inputs) ====='
SELECT COUNT(*) AS rated_buys,
       COUNT(*) FILTER (WHERE COALESCE((o.input_json::jsonb #>> '{insider_stats,buy,eligible_n_60d}')::int,0) > 0)
           AS saw_buy_win_rate_60d,
       COUNT(*) FILTER (WHERE COALESCE((o.input_json::jsonb #>> '{insider_stats,buy,eligible_n_180d}')::int,0) > 0)
           AS saw_buy_win_rate_180d,
       COUNT(*) FILTER (WHERE o.input_json::jsonb #> '{issuer_context,news}' IS NOT NULL) AS saw_news,
       COUNT(*) FILTER (WHERE o.input_json::jsonb #> '{issuer_context,fundamentals}' IS NOT NULL) AS saw_fundamentals
FROM ai_outputs o JOIN insider_events e USING (issuer_cik, owner_key, accession_number)
WHERE e.has_buy=1 AND o.buy_rating IS NOT NULL;

\echo '===== F2. How far does the final rating sit from the deterministic baseline? ====='
SELECT ROUND((o.buy_rating - (o.input_json::jsonb #>> '{baseline,buy,rating}')::float)::numeric, 0) AS rating_minus_baseline,
       COUNT(*) AS n
FROM ai_outputs o
WHERE o.buy_rating IS NOT NULL AND (o.input_json::jsonb #>> '{baseline,buy,rating}') IS NOT NULL
GROUP BY 1 ORDER BY 1;

\echo '===== F3. Top-level keys of a stored AI input (so we know every field the model saw) ====='
SELECT string_agg(k, ', ' ORDER BY k) AS input_keys
FROM (SELECT jsonb_object_keys(input_json::jsonb) AS k
      FROM ai_outputs ORDER BY ai_output_id DESC LIMIT 200) t
WHERE k IS NOT NULL;

\echo '===== G1. One sample rated buy (public SEC data only) ====='
SELECT e.ticker, e.filing_date, e.buy_trade_date, e.owner_title, e.buy_dollars_total,
       e.ai_buy_rating, e.ai_generated_at, e.ai_computed_at, e.market_cap_bucket,
       o.anchor_trading_date, o.p0, o.return_60d, o.bench_return_60d, o.excess_return_60d
FROM insider_events e
LEFT JOIN event_outcomes o ON o.issuer_cik=e.issuer_cik AND o.owner_key=e.owner_key
     AND o.accession_number=e.accession_number AND o.side='buy'
WHERE e.has_buy=1 AND e.ai_buy_rating IS NOT NULL
ORDER BY e.filing_date DESC LIMIT 3;

