# InsidrsAI

A full-stack platform that ingests SEC Form 4 insider-trading filings, measures how those trades performed
afterward, and uses an LLM to rate each signal. It ran as a paid subscription product for 100+ users and is now
kept online as a **portfolio showcase**.

- **Live site:** [insidrsai.com](https://insidrsai.com)
- **Recruiters:** [insidrsai.com/recruiters](https://insidrsai.com/recruiters) has a 3-minute guided tour of the
  real app. It signs you into a read-only demo account; no sign-up needed.

> **Status:** market data is frozen at the last sync (the market-data subscription is paused), and subscriptions
> are closed. Everything on the site is real production data as of that date.

## What's inside

- **Ingestion:** a poller on EDGAR's live Form 4 feed feeds a Postgres-backed job queue (dedupe keys, priorities,
  retries). Separate API and compute workers parse filing XML into one event per insider per filing.
- **Signal research:** 60/180 trading-day forward returns from the first tradeable day after each filing went
  public, net of SPY. These roll up into per-insider win rates. Features include cluster buying (2+ insiders in 14
  days), pre-trade momentum, 52-week range position, and 50/200-day moving averages.
- **AI rating:** Gemini receives a structured feature package (never raw filings) and must return strict JSON
  validated against a versioned schema, with one repair attempt on failure. Inputs are hashed so unchanged events
  are never re-scored.
- **Product:** React/TypeScript SPA, cookie-based JWT auth, Stripe subscriptions (Checkout, trials, Customer
  Portal, signed idempotent webhooks), admin monitoring, a support inbox, and a read-only showcase role.
- **Deploy:** Docker Compose on a Linux VM (Postgres, FastAPI, two worker types, and Caddy for automatic HTTPS).

## Showcase mode

`SHOWCASE_MODE` (default `1`) turns the site into a portfolio piece:

- The paywall is off, and Stripe checkout is closed. The Customer Portal still works for existing subscribers.
- `POST /auth/demo-login` signs visitors into the read-only showcase account, creating it if needed. Admin pages
  mask customer names, emails, phones, and Stripe IDs for that account. Job error strings are scrubbed of
  credentials for all viewers.
- The leaderboard's 60-day window is anchored on the last date with stored prices instead of today.
- Feeds (events, For You, tickers, ticker pages) show visitors only fully analyzed events: an AI rating plus stored
  prices after the filing. Lookback windows count back from the last priced day. Admins still see every ingested
  filing.
- The SPA shows a portfolio banner, the `/recruiters` page, and the guided tour.

Set `SHOWCASE_MODE=0` to restore normal paid-product behavior.

## Pausing Gemini classification

Gemini classification is **off by default**. Admins can turn it on or off from **Site settings** in the app; the
switch lives in the database, so no redeploy is needed. While it's paused, the SEC poller and the other workers keep
ingesting and processing filings, but AI jobs finish without calling Gemini. The site shows an "AI classification is
paused" notice, and manual "Regenerate AI" requests are refused. Filings ingested while paused are not rated
retroactively when it's turned back on.

## Project layout

- `insider_platform/`: FastAPI app, DB layer, SEC ingestion, analytics, AI, billing
- `scripts/`: run scripts + init DB
- `frontend/`: Vite/React SPA (the tour lives in `src/components/tour/`, the recruiters page in `src/pages/recruiters.tsx`)
- `deploy/`: production reverse proxy config (Caddy) + Dockerfile

## Quick start (local dev)

1) Copy environment file:

```bash
cp .env.example .env
```

2) Start Postgres:

```bash
docker compose up -d db
```

3) Initialize / migrate the database schema (recommended):

```bash
python scripts/init_db.py
```

Note: the API and workers will also run migrations automatically on startup, so this is mainly useful to migrate ahead of time.

4) Start the API:

```bash
python scripts/run_api.py
```

5) Start workers (optional but recommended):

```bash
python scripts/run_api_worker.py
python scripts/run_compute_worker.py
```

6) Start the frontend:

```bash
cd frontend
npm install
npm run dev
```

Open the app at:

- Frontend: `http://localhost:5173`
- API: `http://localhost:8000`


## Backfill fundamentals (sector/beta)

If you add new fundamentals fields (like `sector` / `beta`) and want to populate them for existing tickers, you can enqueue market-cap/fundamentals jobs:

```bash
python scripts/enqueue_market_cap.py --all
```

Run with `--force` to refresh all tickers:

```bash
python scripts/enqueue_market_cap.py --all --force
```

## Production (Docker + Caddy)

Use `docker-compose.prod.yml`.

```bash
docker compose -f docker-compose.prod.yml up -d --build
```

Caddy will serve:

- Frontend (SPA)
- Reverse proxy API under `/api/backend/*`

See `LAUNCH_GUIDE.md` for a complete DigitalOcean + Namecheap deployment walkthrough.
