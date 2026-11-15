# InsidrsAI research pipeline

A read-only quantitative study of the Form 4 data behind InsidrsAI: do the AI
ratings, per-insider track records, and event features predict forward excess
returns on open-market insider purchases?

Rules for everything in this folder:

- **Read-only against production tables.** Research output goes to Parquet
  files or a separate `research` schema, never to app tables.
- **No credentials and no user data in git.** Only aggregate results.
- **Point-in-time only.** A feature may use only what was public on the filing date.

## Status

| Phase | What | State |
|-------|------|-------|
| 0 | Inspect schema, data gaps, live vs backfilled ratings | done (findings below) |
| 1 | Build analysis dataset + sanity checks | code written; tested on synthetic data and a handful of real tickers, not yet on the full database |
| 2 | Q1 ratings vs returns, Q2 track-record persistence | Q1 run on real data (results below); Q2 script written (tested on synthetic data) |
| 3 | Q3 winner features + robustness | not started |
| 4 | Write-up + product implications | not started |

## Layout

| File | Purpose |
|------|---------|
| `phase0/inspect.sql` | One-off read-only inspection of the production database |
| `config.yaml` | Every parameter that affects a result |
| `extract.py` | Postgres -> Parquet (`data/events`, `ratings`, `prices`, `benchmark`) |
| `fetch_prices.py` | Yahoo Finance -> `data/prices_yf.parquet` (adjusted close, close, volume) + SPY |
| `build_dataset.py` | Parquet -> `data/analysis.parquet`, one row per (event, side) |
| `sanity_check.py` | Prints 10 random buys with everything needed to verify them by hand |
| `tests/` | Unit tests for the return and point-in-time logic; synthetic-data seeder |
| `analysis/stats.py` | Cluster bootstrap, information coefficient, FDR adjustment |
| `analysis/q1_ratings.py` | Q1: AI rating vs forward excess return, live and backfilled kept apart |
| `analysis/q2_track_records.py` | Q2: does an insider's past win rate predict their next trade? |

`data/` and `output/` are git-ignored.

## Running on the server

All commands are run from the repo root. `R` is just a shorthand:

```bash
R="docker compose -f docker-compose.prod.yml -f docker-compose.research.yml run --rm research"
```

Phase 0 (one-off):

```bash
docker compose -f docker-compose.prod.yml exec -T db psql -U postgres -d insider_platform -f - < research/phase0/inspect.sql > phase0_output.txt 2>&1
```

Phase 1:

```bash
$R python -m pytest research/tests -q
```

```bash
$R python -m research.extract
```

```bash
$R python -m research.fetch_prices
```

```bash
$R python -m research.build_dataset
```

```bash
$R python -m research.sanity_check
```

Phase 2:

```bash
$R python -m research.analysis.q1_ratings
```

```bash
$R python -m research.analysis.q2_track_records
```

After pulling a change to `research/requirements.txt`, rebuild the image first:

```bash
docker compose -f docker-compose.prod.yml -f docker-compose.research.yml build research
```

The research container connects with a read-only session and only runs
`SELECT`s. It is behind the `research` compose profile, so a normal
`docker compose up` never starts it.

## How returns are built (differences from production)

| | Production (`event_outcomes`) | Research |
|---|---|---|
| Entry | close on the filing date | close on the first trading day **after** the filing date |
| Benchmark window | +N rows in SPY's own series | same calendar dates as the stock |
| Series ends before horizon | dropped (`insufficient_future_data`) | if the series ended well before the newest price in the DB: kept, exits at last price (`delisted`); otherwise `not_matured` |
| Split/adjustment breaks | not detected | windows containing a one-day move > +150% or < -60% are flagged and excluded |
| Track record | all of the insider's trades | only trades whose holding period ended before this filing |
| Cluster | full 14-day window | other insiders who **filed** in the prior 14 days |
| Market cap | today's snapshot | snapshot rescaled by price change since entry (approximate) |

## Phase 0 findings (production database, 13 Nov 2026)

**Universe and coverage**
- 801K filings, 118,447 buy events by 27,813 insiders (all keyed by SEC CIK).
  13,024 insiders have exactly one buy; 5,672 have five or more.
- The company universe is a list of tickers listed in 2026. No price series
  ends before 2026, so **no delisted company is in the data at all**
  (survivorship bias at the universe level; results are biased upward).
- The historical backfill is about half complete (801K parsed of ~1.53M
  queued) and was filled company by company, oldest filings first. Only 2020
  and 2024 are close to complete.

**Prices**
- Production prices and SPY stop on 2026-05-29.
- 13,540 one-day moves beyond +150% / -60% across 1,769 of 5,912 series.
- About 160 series come from non-US symbols (wrong ticker match) and 639
  issuers have rows from more than one source symbol.
- Hence `price_source: yfinance`: one consistent download, never written to
  production. It still has no delisted companies.

**Ratings**
- 65,969 rated events, 15,927 with a buy rating, across three prompt versions
  (v3, v4, v5) and two Gemini models. Rated filings date from Jan 2024 on.
- Rating activity by server clock: 35,861 in Feb 2026 (the batch), then
  3,000-6,000 a month through Sep 2026.
- For rated buys, by server clock: 7,197 rated within 3 days of filing (live),
  7,668 rated more than 180 days after (backfill), about 1,060 in between.
- The model-written timestamp agrees with the server clock within a day for
  98.7% of ratings; the pipeline uses the server clock.
- 11,179 of 15,927 rated buys were shown the insider's stored win rate.
- Ratings are tightly bunched: 14,268 of 15,918 fall between 6.0 and 7.9.

**Production outcomes (before any correction)**
- Buys, 60 days, n=104,890: median excess return -1.6%, 45.4% beat SPY.
  The mean is meaningless (driven by price errors; max 60-day return 89,000x).

**Reported amounts**
- 213 buys over $1B, 320 with a reported price over $10,000 (parse errors);
  378 buy and 458 sell trade dates carry a timezone suffix.

## Q1 results (run 15 Nov 2026): did the AI ratings work?

Qualifying buys only; excess return = stock minus SPY; means winsorized at
1%/99%; intervals from a bootstrap that resamples whole months.

**Live ratings (rated within 7 days of filing; Feb-Sep 2026; 60 days; n=4,035, 8 months)**

| Rating | n | Mean excess | Hit rate |
|---|---|---|---|
| all buys, same months | 4,776 | -4.7% | 38.2% |
| <6 | 209 | -2.0% | 41.6% |
| 6-6.9 | 2,263 | -3.5% | 39.8% |
| 7-7.9 | 1,465 | -8.1% | 35.0% |
| 8+ | 98 | -14.1% | 30.6% |

- Top third minus bottom third by rating: -4.7 points (95% CI -7.2 to -1.1).
- Rank correlation (IC): -0.10 pooled; monthly mean -0.08, negative in 6 of 7 months.
- Split into parts: the formula baseline has IC -0.08; Gemini's adjustment has IC +0.04 (not significant).
- **Conclusion: live ratings did not predict outperformance. Over this window they pointed the wrong way.**
  Seven months in one market regime; no live 180-day result exists yet.

**Backfilled ratings (rated after the outcome; 2024-2025 filings; n=6,190, 23 months)**

- Rating 8+: +3.5% at 60 days, +14.3% at 180 days; top minus bottom third +4.8 / +7.8 points.
- The positive relation comes entirely from Gemini's adjustment (IC +0.09 / +0.13);
  the formula baseline is flat-to-negative here too (IC -0.04 / -0.08).
- 6,131 of 6,190 were shown the insider's stored win rate, which was computed
  with later outcomes included. The adjustment's IC is higher for filings after
  the model's knowledge cutoff (+0.17) than before it (+0.06), so the cause is
  the leaked input, not model memory.
- **Conclusion: backfilled results are contaminated and are not evidence the ratings work.**

**Coverage check:** buys dropped for lack of a Yahoo price had a median
production 60-day excess of -1.5% (hit rate 45.0%) versus -1.2% (46.3%) for
buys kept, so dropping them biases results upward only slightly.

## Known issues found by reading the code

These are properties of the production code that the research pipeline must
correct for; they are documented here so the write-up can cite them.

1. **Stored track records are not point-in-time.** `insider_issuer_stats` is
   computed over all of an insider's outcomes, including the trade being
   evaluated and later trades. The research pipeline recomputes track records
   from earlier, already-matured trades only.
2. **AI ratings saw those stats.** `insider_stats` (win rate / average excess
   return) is part of the model input. For backfilled filings this can include
   the filing's own outcome.
3. **Rating timestamp is model-written.** `ai_outputs.generated_at` is copied
   from the model's JSON, not the server clock.
4. **Market cap, sector and fundamentals are current snapshots**, not values as
   of the filing date.
5. **Cluster flag uses the full 14-day window**, including buys filed after the
   event in question.
6. **Delisted names drop out.** An outcome needs 60/180 further rows in the
   price series; a series that ends (acquisition, delisting) yields
   `insufficient_future_data`, the same code as a trade that has not matured.
7. **Adjusted closes are refreshed incrementally** (last 30 days), so a split
   or dividend after the first download can leave older rows on a stale
   adjustment basis.
8. **Entry price is the close on the filing date.** Most Form 4s are accepted
   after the close, so that price was often not tradeable.
9. **Benchmark window is counted separately** (+60 rows in each series), so
   gaps in an issuer's series misalign the stock and SPY windows.
10. **Only adjusted close is stored**: no volume or unadjusted price, so no
    liquidity filter is possible without more data.
