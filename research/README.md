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
| 0 | Inspect schema, data gaps, live vs backfilled ratings | in progress |
| 1 | Build analysis dataset + sanity checks | not started |
| 2 | Q1 ratings vs returns, Q2 track-record persistence | not started |
| 3 | Q3 winner features + robustness | not started |
| 4 | Write-up + product implications | not started |

## Phase 0

Run on the server, from the repo root:

```bash
docker compose -f docker-compose.prod.yml exec -T db \
  psql -U postgres -d insider_platform -f - < research/phase0/inspect.sql > phase0_output.txt 2>&1
```

The script runs inside a `READ ONLY` transaction and prints aggregates only.
`phase0_output.txt` is git-ignored.

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
