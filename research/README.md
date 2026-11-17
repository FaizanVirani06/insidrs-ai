# InsidrsAI research pipeline

**Results: see [WRITEUP.md](WRITEUP.md).** Follow-up study in progress: [PREREGISTRATION.md](PREREGISTRATION.md) (holdout 2025+ locked). The sections below are the working log.

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
| 1 | Build analysis dataset + sanity checks | done (runs on the full database; returns match an independent recomputation) |
| 2 | Q1 ratings vs returns, Q2 track-record persistence | done |
| 3 | Q3 winner features, Q4 sells, robustness | done (results below and in WRITEUP.md) |
| 4 | Write-up + product implications | done: [WRITEUP.md](WRITEUP.md) |

## Layout

| File | Purpose |
|------|---------|
| `phase0/inspect.sql` | One-off read-only inspection of the production database |
| `config.yaml` | Every parameter that affects a result |
| `extract.py` | Postgres -> Parquet (`data/events`, `ratings`, `prices`, `benchmark`) |
| `fetch_prices.py` | Yahoo Finance -> `data/prices_yf.parquet` (adjusted close, close, volume, adjusted open/high/low) + SPY and IWM |
| `fetch_shares.py` | SEC XBRL -> `data/shares.parquet` (reported shares outstanding, for point-in-time market cap) |
| `build_dataset.py` | Parquet -> `data/analysis.parquet`, one row per (event, side) |
| `sanity_check.py` | Prints 10 random buys with everything needed to verify them by hand |
| `tests/` | Unit tests for the return and point-in-time logic; synthetic-data seeder |
| `analysis/stats.py` | Cluster bootstrap, information coefficient, FDR adjustment |
| `analysis/q1_ratings.py` | Q1: AI rating vs forward excess return, live and backfilled kept apart |
| `analysis/q2_track_records.py` | Q2: does an insider's past win rate predict their next trade? |
| `analysis/q3_features.py` | Q3: base rates vs two benchmarks, single features, logistic regression, tree model |
| `analysis/q4_sells.py` | Q4: stock returns after insider sells, versus buys |
| `analysis/robustness.py` | Fund-concentration checks on the Q2 fund result; returns net of assumed trading costs |
| `run_all.py` | Runs every step in order; stops at the first failure |
| `fetch_factors.py` | Fama-French 5 factors + momentum, daily, from Ken French's library |
| `build_events.py` | Event-time windows (trade -> filing -> entry -> +h) and pre-registered features |
| `analysis/h_preregistered.py` | Pre-registered tests H1-H5; development sample unless `--open-holdout` |
| `fetch_acceptance.py` | Exact EDGAR acceptance times of Form 4s, plus earnings-release 8-Ks and Schedule 13D/13G (SEC submissions data) |
| `analysis/realtime.py` | Study 2: how much of the disclosure reaction a real-time reader can capture |
| `fetch_filer_13d.py` | Schedule 13D filings made by each 10%-holder buyer (for S10b) |
| `phase0/check_10b5.sql` | Read-only check of how 10b5-1 plans appear in the Form 4 XML (run before Study 3 extraction) |
| `build_study3.py` | Study 3 features: earnings releases (8-K 2.02), 13D filings, 10b5-1 flags, option exercises, switchers, accumulation |
| `analysis/study3.py` | Study 3: pre-registered hypotheses S1-S10 (`--stage dev`, then `A`, then `B`); refuses holdouts before the Amendment 4(a) dates |
| `analysis/erules.py` | Amendment 4(b): execution rules E1-E3 against the standard entry (development; holdout B only) |
| `run.sh` | Host-side entry point on the droplet: refuses a dirty tree, passes the commit hash, appends all output to one summary file |
| `runner.py` | In-container wrapper used by `run.sh`: prints module, commit, start/end time, elapsed time and peak memory |

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
$R python -m research.fetch_shares
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

```bash
$R python -m research.analysis.q3_features
```

```bash
$R python -m research.analysis.q4_sells
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
| Market cap | today's snapshot | SEC-reported shares outstanding (latest report filed before the Form 4) x the price the insider paid |

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

## Study 2 results (pre-registered, development sample 2010-2024, run 17 Nov 2026)

Using each Form 4's exact acceptance time and daily open and close prices
(excess vs IWM):

- **Gap, lost to anyone using daily prices: +0.99%.** For the 65% of filings
  accepted after the close, this is the overnight move to the next open.
- **Capture, gained by buying at the first available price instead of the
  next-day close: +0.33% (95% CI +0.26, +0.41), median +0.09%.** It is the
  same in every sub-period (+0.34 / +0.34 / +0.32). R1 is supported in development.
- **Holdout (2025+ filings, opened once for R1): capture +0.28% (CI +0.06, +0.50),
  one-sided p = 0.007. Confirmed out of sample.**
- **60 days from the first price: +0.59% gross, −1.33% after assumed costs**
  (CI −2.28, −0.30). R2 is not supported.

- **By liquidity (exploratory):** capture is +0.24% to +0.45% in every tier,
  and negative after one assumed round trip in every tier. The most liquid
  stocks (over $10M a day) come out at −0.06% (CI −0.23, +0.12), about break-even.

Reading: of the roughly 1.5% disclosure reaction, about two thirds is priced
before an outsider using daily data can trade, and about a fifth is capturable
by acting at once. That captured part is smaller than the assumed round-trip
cost for most of these stocks.

## Study 1 results (pre-registered, development sample 2010-2024, run 17 Nov 2026)

**Where the return arrives** (all 56,244 qualifying buys with factor data):

| Window | Factor BHAR (95% CI) | Excess vs IWM |
|---|---|---|
| Trade to the day before filing (insider only) | +0.29% (+0.23, +0.35) | +0.27% |
| Disclosure: day before filing to the day after | +1.58% (+1.33, +1.79) | +1.49% |
| Tradeable, 60 days | +1.69% (+0.41, +3.47), median +0.49% | +0.25% |
| Tradeable, 180 days | +3.72% (+1.50, +6.56), median +0.47% | -0.76% |

The disclosure reaction is consistent across all three measures. After entry,
the factor-adjusted mean is positive but carried by a minority of trades
(medians near zero, hit rates 51-52%). Against the Russell 2000 it is near zero.

**Hypotheses:** none met the development criteria (table in PREREGISTRATION.md).
H1 came out opposite to the prediction: routine beat opportunistic by 4.8 points
(BHAR, 60 days). Exploratory composition (not a claim): routine buys come from only
285 insiders, 70% of them 10%-holder filers, with half the volatility and three
times the purchase size of opportunistic buys. Most of the gap is between
non-financial 10% holders: routine +5.8% versus opportunistic -8.2% (60-day excess vs IWM).

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

## Q2 results (run 15 Nov 2026): do insider track records persist?

Test period: filings from 2018 on (51,111 qualifying buys). A trade's "record"
is the insider's win rate on earlier buys whose holding period had ended.
Spread = next-trade excess return of insiders with past win rate above 60%
minus those below 40%.

**Officers and directors**

| Min prior trades | 60-day spread (95% CI) | 180-day spread (95% CI) |
|---|---|---|
| 1 | +0.1% (-1.9, +1.8) | -2.5% (-6.1, +1.2) |
| 3 | -0.8% (-3.6, +1.5) | -2.6% (-7.7, +3.1) |
| 5 | -2.5% (-6.2, +0.8) | -6.6% (-12.8, +0.8) |
| 10 | -2.6% (-6.4, +1.2) | -7.4% (-14.8, +0.9) |

- Rank correlation between past win rate and next-trade return: 0.02 at both horizons, not significant.
- Requiring a longer record does not help; the point estimates get worse.
- **Conclusion: no evidence that officer/director track records persist.**

**Funds and 10% holders**

- 60 days: spread +7.9% (min 1 prior trade), +8.8% (min 3), +5.6% (min 5), +6.4% (min 10);
  rank correlation about 0.08. Raw p-values 0.002-0.03, FDR-adjusted 0.09-0.17.
- 180 days: nothing (rank correlation about 0, spreads not significant).
- **Conclusion: suggestive short-horizon persistence for funds, not established.**
  It fades by 180 days and may reflect a fund's own continued buying in thin stocks.
  Needs a check that it is not driven by a handful of funds.

**Shrinkage:** fitted on 2010-2017, average win rate 46.7% (60d) / 43.6% (180d),
prior strength k = 5.6 / 3.2 trades. k is probably too small: an insider's
repeat buys in one stock share an outcome, which exaggerates how much
insiders appear to differ.

## Q3 results (run 16 Nov 2026, market cap not yet available)

Excess return vs the Russell 2000 ETF; 74,734 qualifying buys.

**Base rates**
- Mean excess -0.1% at 60 days and -1.1% at 180; median -1.7% and -4.4%;
  45.6% and 43.3% beat the benchmark. The average buy matches its benchmark,
  the typical buy loses, and a minority of large winners makes up the difference.
- By period at 180 days: 2010-17 +1.3%, 2018-19 +3.0%, 2020-21 -3.5%, 2022-23 -6.3%, 2024-26 0.0%.

**Single features (top minus bottom bucket, FDR across 24 tests)**
- Above the 200-day average: +5.2 points at 180 days (FDR p 0.002); above the 50-day: +4.6 (0.003).
- Far above the 52-week low: +5.1 points at 180 days (FDR p 0.08).
- Purchase size, purchase as % of holdings, cluster buying, insider's number
  of earlier buys, market regime: no significant spread.

**Models (fitted on filings through 2021, scored on 2022 onward)**

| Model | Horizon | Test AUC | Base hit rate | Top-20% hit rate | Top minus bottom 20% (95% CI) |
|---|---|---|---|---|---|
| Logistic regression | 60d | 0.526 | 43.6% | 47.7% | +2.1 pts (-0.9, +5.1) |
| Gradient-boosted trees | 60d | 0.546 | 43.6% | 51.7% | +5.3 pts (+2.8, +8.1) |
| Logistic regression | 180d | 0.538 | 41.7% | 45.3% | +6.9 pts (+1.8, +12.6) |
| Gradient-boosted trees | 180d | 0.552 | 41.7% | 49.4% | +9.3 pts (+4.2, +14.9) |

- A modest, real out-of-sample ranking signal, mostly from price trend and the
  recent market return. The top 20% still averages only +1.9% / +1.1% excess:
  the spread comes mainly from avoiding the worst buys.
- Logistic coefficients that survive FDR: missing trend data (a company with
  under a year of price history) lowers the odds of beating the benchmark
  (odds ratio 0.72 at 60d, 0.67 at 180d); "other officer" raises them at 180d (1.14).
  Cluster buying is borderline (1.17 at 60d, FDR p 0.07).

**Live AI rating, re-checked against the Russell 2000:** IC -0.09 (was -0.10
against the S&P 500), so the benchmark does not explain the Q1 result.

## Q3 update with point-in-time market cap, and Q4 (run 16 Nov 2026)

Market cap (SEC share count x reported trade price) is available for 73% of rows.

- **Company size:** no significant relation. 180-day excess vs Russell 2000:
  micro -0.9%, small +1.0%, mid -4.6%, large -4.4% (wide intervals).
  Top-minus-bottom market-cap quintile: -2.8 points (FDR p 0.29).
  The earlier "large caps lose 14%" was the look-ahead artifact.
- **Purchase as a share of market cap:** nothing (+0.7 points at 180 days).
- **Models with market cap included:** tree model AUC 0.547 (60d) / 0.551 (180d);
  top-minus-bottom 20% +5.3 points (CI +2.8, +8.2) and +6.2 points (CI +0.5, +12.0).
- **Live AI rating within size groups (60 days, vs Russell 2000):** IC +0.03 large,
  -0.06 mid, -0.16 small, -0.04 micro. The negative relation is not a size effect.

**Q4, sells (167,834 qualifying sells, excess vs Russell 2000):**
- Stocks insiders sold returned +0.4% at 60 days and +0.3% at 180: no underperformance.
- No subgroup is negative: largest 10% by dollars, sold more than 25% of holdings,
  two or more other insiders also selling, or any role.
- Stocks sold did slightly better than stocks bought (+0.5 / +1.4 points, not significant).
- Live AI sell rating vs later return: IC +0.005 (n=17,629). No signal.
- **Conclusion: sells carry no detectable signal in this data.** Pre-planned
  (10b5-1) and tax sales are not separated out.

## Scheduled refresh

`research.run_all` re-extracts, re-downloads prices and share counts, rebuilds
the dataset and reruns every analysis, writing a log to `output/logs/` and a
status file to `output/last_run.json`. To run it on the 2nd of each month at
06:00 server time, add this line with `crontab -e` (adjust the path):

```
0 6 2 * * cd /root/insidersproject && SUMMARY=research/output/cron_summary.txt research/run.sh research.run_all
```

## A leak this study introduced and removed (16 Nov 2026)

The first version of the research market cap rescaled today's market cap by
the price change since the filing. That quantity contains the stock's future
return: a company that later collapsed (and diluted) looks "large" at the time
of the buy. The first Q3 run therefore showed "large caps" losing 14% over 180
days and market cap as the strongest feature. Those two results (market cap,
and purchase as a share of market cap) were artifacts and are withdrawn.
Market cap is now built only from inputs public on the filing date, with a
unit test that a share count filed on or after the Form 4 date is never used.

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
