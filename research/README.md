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
| 0 | Inspect schema, data gaps, live vs backfilled ratings | queries written; awaiting output from the server |
| 1 | Build analysis dataset + sanity checks | code written, tested on synthetic data only |
| 2 | Q1 ratings vs returns, Q2 track-record persistence | not started |
| 3 | Q3 winner features + robustness | not started |
| 4 | Write-up + product implications | not started |

## Layout

| File | Purpose |
|------|---------|
| `phase0/inspect.sql` | One-off read-only inspection of the production database |
| `config.yaml` | Every parameter that affects a result |
| `extract.py` | Postgres -> Parquet (`data/events`, `ratings`, `prices`, `benchmark`) |
| `build_dataset.py` | Parquet -> `data/analysis.parquet`, one row per (event, side) |
| `sanity_check.py` | Prints 10 random buys with everything needed to verify them by hand |
| `tests/` | Unit tests for the return and point-in-time logic; synthetic-data seeder |
| `analysis/` | One script per research question (Phase 2 onward) |

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
$R python -m research.build_dataset
```

```bash
$R python -m research.sanity_check
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

## Known issues found by reading the code (to be confirmed with Phase 0 output)

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
