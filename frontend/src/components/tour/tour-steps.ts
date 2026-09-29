/**
 * The recruiter tour: an ordered walk through the real app, one stop per page.
 *
 * Each stop names a route and (optionally) a `data-tour="..."` element on that page to
 * highlight. Copy is written for a non-specialist first, with the engineering detail
 * tucked into "Under the hood".
 */

export type TourFeatured = {
  /** Detail page of a strong signal pulled from the live leaderboard at tour start. */
  eventPath: string | null;
  ticker: string | null;
};

export type TourStep = {
  id: string;
  path: (featured: TourFeatured) => string;
  target?: string;
  eyebrow: string;
  title: string;
  body: string;
  details: string[];
};

export const TOUR_STEPS: TourStep[] = [
  {
    id: "leaderboard",
    path: () => "/",
    target: "leaderboard",
    eyebrow: "Landing page",
    title: "The leaderboard",
    body:
      "Insider filings from the 60 days before the data freeze, ranked by how the stock moved after the filing became public. It's computed from the database, not hard-coded.",
    details: [
      "A single Postgres query uses LATERAL joins to find each filing's first tradeable close and the latest close, then ranks by return.",
      "Repeat filings for the same ticker collapse into one row with an insider count, so one busy company can't fill the board.",
      "A ticker-validation cache drops bad symbol mappings, and the absurd returns they produce, before they reach the page.",
      "When I stopped paying for market data, the board went empty because its window was counted back from today. It now anchors on the last day with stored prices.",
    ],
  },
  {
    id: "events",
    path: () => "/app/events",
    target: "events-feed",
    eyebrow: "Data pipeline",
    title: "Every Form 4, parsed and scored",
    body:
      "Company insiders have to report trades in their own stock on SEC Form 4 within two business days. This feed is built from those filings.",
    details: [
      "A poller watches EDGAR's live Form 4 feed and enqueues new filings every couple of minutes.",
      "A Postgres-backed job queue with dedupe keys, priorities, and retries fans work out to separate API and compute workers.",
      "The parser normalizes the filing XML: open-market buys vs. sells, derivative vs. non-derivative rows, footnotes, and holdings after the trade.",
      "Rows roll up into one event per insider per filing, with a share-weighted average price and the % change in the insider's holdings.",
    ],
  },
  {
    id: "event",
    path: (f) => f.eventPath || "/app/events",
    target: "event-summary",
    eyebrow: "Signal research",
    title: "Anatomy of a signal",
    body:
      "This is one of the top performers from the leaderboard. The chart marks the trade and filing dates, and the cards show what the insider did and what happened next.",
    details: [
      "Forward returns are measured 60 and 180 trading days from the first tradeable day after the filing became public, not the trade date, so there's no look-ahead bias.",
      "Each return is compared with SPY over the same window to get excess return, which builds each insider's historical win rate.",
      "Cluster detection flags two or more distinct insiders trading the same direction within a 14-day window.",
      "Trend features: 20/60-day momentum before the trade, distance from the 52-week high/low, and position vs. the 50/200-day moving averages.",
    ],
  },
  {
    id: "ai",
    path: (f) => f.eventPath || "/app/events",
    target: "ai-explanation",
    eyebrow: "Applied AI",
    title: "An AI rating with guardrails",
    body:
      "Gemini rates each event, but it never reads raw filings. It gets a structured package of the features above and has to answer in strict JSON.",
    details: [
      "Output is validated against a versioned schema. If parsing or validation fails, the model gets one repair attempt with the exact error.",
      "Inputs are canonicalized and hashed, so an unchanged event is never re-scored. That kept costs down while scoring tens of thousands of filings a week.",
      "Prompt and schema versions are stored with every output, so ratings can be recalibrated or regenerated in bulk.",
      "The demo account can see the exact input package the model received. It's further down this page.",
    ],
  },
  {
    id: "ticker",
    path: (f) => (f.ticker ? `/app/ticker/${encodeURIComponent(f.ticker)}` : "/app/tickers"),
    target: "ticker-header",
    eyebrow: "Company view",
    title: "Everything for one ticker",
    body:
      "Each company page collects every insider event for the symbol, with filters for buys or sells, trade size, clusters, AI-rated events, and insider role.",
    details: [
      "Officer, director, and 10%-owner flags come straight from the Form 4 reporting-owner relationship fields.",
      "Market-cap buckets, sector, and beta come from cached fundamentals with staleness windows, which keeps data-provider costs predictable.",
      "Regular users only see open-market trades. Admins can switch on everything else (grants, option exercises, gifts) to audit the parser.",
    ],
  },
  {
    id: "for-you",
    path: () => "/app/for-you",
    target: "for-you-summary",
    eyebrow: "Personalization",
    title: "A feed shaped by saved preferences",
    body:
      "Users save a trade side, a minimum AI score, preferred sectors, and a beta cap on their profile. The server turns those into one filtered, paginated query.",
    details: [
      "Preferences are stored as normalized JSON with defaults, so older profiles keep working when new filters ship.",
      "Multi-line filings are de-duplicated so each filing shows up once in the feed.",
    ],
  },
  {
    id: "monitoring",
    path: () => "/app/admin/monitoring",
    target: "monitoring-overview",
    eyebrow: "Running it in production",
    title: "An ops dashboard for a one-person team",
    body:
      "I ran the platform by myself, so I built my own ops view: queue depth, throughput, p50/p95 latency by job type, and recent errors. It's quiet now because ingestion is paused.",
    details: [
      "Deployed with Docker Compose on a Linux VM: Postgres, the FastAPI API, two worker types, and Caddy for HTTPS and reverse proxying.",
      "Credentials are scrubbed from job error messages before they reach this page.",
      "The admin area also covers users, a support inbox, feedback, and site settings. In this demo, customer names and emails are masked and everything is read-only.",
    ],
  },
  {
    id: "pricing",
    path: () => "/pricing",
    target: "pricing-card",
    eyebrow: "Monetization",
    title: "Stripe subscriptions, end to end",
    body:
      "InsidrsAI ran as a paid product for 100+ users. Checkout is closed now, but the billing integration is still in the code.",
    details: [
      "Stripe Checkout for monthly and yearly plans with a 7-day free trial, plus the Customer Portal for self-serve changes and cancellations.",
      "Signed webhooks keep subscription state in sync, and processed event IDs are recorded so Stripe's retries are idempotent.",
      "The paywall is enforced twice: FastAPI returns 402 on gated endpoints, and React route guards handle the UI.",
    ],
  },
  {
    id: "wrap-up",
    path: () => "/recruiters",
    target: "contact",
    eyebrow: "That's the tour",
    title: "Thanks for looking around",
    body:
      "The demo account stays signed in, so feel free to keep exploring. The full source is on GitHub, and I'm happy to walk through any part of it.",
    details: [],
  },
];
