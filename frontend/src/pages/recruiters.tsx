import * as React from "react";
import { Link } from "react-router-dom";

import { DemoButton } from "@/components/demo-button";
import { useTour } from "@/components/tour/tour-provider";
import { TOUR_STEPS } from "@/components/tour/tour-steps";
import { OWNER } from "@/lib/showcase";
import { fmtLongDate, useSiteStatus } from "@/lib/site-status";

function Stat({ label, value, helper }: { label: string; value: string; helper?: string }) {
  return (
    <div className="rounded-2xl border border-zinc-800/70 bg-black/40 p-5">
      <div className="text-[11px] font-semibold uppercase tracking-[0.18em] text-zinc-500">{label}</div>
      <div className="mt-2 text-3xl font-semibold tabular-nums text-zinc-50">{value}</div>
      {helper ? <div className="mt-1 text-xs text-zinc-500">{helper}</div> : null}
    </div>
  );
}

function Node({ children, tone = "zinc" }: { children: React.ReactNode; tone?: "zinc" | "purple" | "cyan" | "amber" }) {
  const toneClass = {
    zinc: "border-zinc-700/80 bg-zinc-900/70 text-zinc-100",
    purple: "border-purple-500/40 bg-purple-500/10 text-purple-100",
    cyan: "border-cyan-500/40 bg-cyan-500/10 text-cyan-100",
    amber: "border-amber-500/40 bg-amber-500/10 text-amber-100",
  }[tone];
  return <div className={`rounded-lg border px-3 py-2 text-sm font-medium ${toneClass}`}>{children}</div>;
}

function Arrow() {
  return (
    <span aria-hidden className="text-zinc-500">
      →
    </span>
  );
}

function Lane({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="grid gap-3 md:grid-cols-[120px_minmax(0,1fr)] md:items-center">
      <div className="text-[11px] font-semibold uppercase tracking-[0.18em] text-zinc-500">{label}</div>
      <div className="flex flex-wrap items-center gap-2">{children}</div>
    </div>
  );
}

function Highlight({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <li className="rounded-xl border border-zinc-800/70 bg-black/30 p-4">
      <div className="text-sm font-semibold text-zinc-100">{title}</div>
      <div className="mt-1 text-sm leading-6 text-zinc-400">{children}</div>
    </li>
  );
}

const STACK = [
  "Python",
  "FastAPI",
  "PostgreSQL",
  "React 19",
  "TypeScript",
  "Tailwind CSS",
  "Docker Compose",
  "Caddy",
  "Gemini API",
  "Stripe",
  "SEC EDGAR",
  "Linux VM",
];

export function RecruitersPage() {
  const tour = useTour();
  const status = useSiteStatus();
  const stats = status.stats;

  return (
    <div className="mx-auto max-w-6xl space-y-12 pb-8">
      <section className="relative overflow-hidden rounded-[2rem] border border-zinc-800/70 bg-black/55 px-6 py-10 shadow-2xl shadow-purple-500/10 backdrop-blur-xl sm:px-10 sm:py-14">
        <div className="pointer-events-none absolute inset-0 bg-[radial-gradient(circle_at_top_left,rgba(168,85,247,0.22),transparent_36%),radial-gradient(circle_at_bottom_right,rgba(34,211,238,0.18),transparent_36%)]" />
        <div className="relative grid gap-10 lg:grid-cols-[minmax(0,1fr)_320px] lg:items-start">
          <div>
            <div className="inline-flex items-center rounded-full border border-cyan-500/30 bg-cyan-500/10 px-4 py-1.5 text-xs font-semibold uppercase tracking-[0.18em] text-cyan-200">
              For recruiters
            </div>
            <h1 className="mt-6 text-4xl font-semibold tracking-tight text-zinc-50 sm:text-5xl">
              Hi, I&apos;m {OWNER.name.split(" ")[0]}. I built InsidrsAI end to end.
            </h1>
            <p className="mt-5 max-w-2xl text-lg leading-8 text-zinc-300">
              It&apos;s a full-stack platform that ingests SEC insider-trading filings, measures how those trades
              actually performed, and uses an LLM to rate each signal. I ran it as a paid subscription product with
              100+ users. It&apos;s now kept online as a portfolio piece, and everything below is the real production
              app.
            </p>

            <div className="mt-8 flex flex-col gap-3 sm:flex-row sm:items-start">
              <button
                type="button"
                onClick={() => void tour.start(0)}
                disabled={tour.starting}
                className="btn-primary h-12 px-7 text-base"
              >
                {tour.starting ? "Starting…" : "Start the guided tour"}
              </button>
              <DemoButton className="btn-secondary h-12 px-6">Explore on my own</DemoButton>
              <a href={OWNER.repo} target="_blank" rel="noreferrer" className="btn-ghost h-12 px-4">
                View the source ↗
              </a>
            </div>
            <p className="mt-3 text-sm text-zinc-500">
              About 3 minutes, {TOUR_STEPS.length} stops. No sign-up: the tour signs you into a read-only demo account.
            </p>
            {tour.error ? <p className="mt-2 text-sm text-red-300">{tour.error}</p> : null}
          </div>

          <div className="glass-panel p-5 dark:bg-zinc-950/60">
            <div className="text-lg font-semibold text-zinc-50">{OWNER.name}</div>
            <div className="mt-1 text-sm text-zinc-400">{OWNER.school}</div>
            <div className="mt-3 text-sm leading-6 text-zinc-300">{OWNER.degrees}</div>
            <div className="mt-4 rounded-xl border border-emerald-500/30 bg-emerald-500/10 px-3 py-2 text-sm font-medium text-emerald-200">
              {OWNER.availability}
            </div>
            <div className="mt-4 flex flex-wrap gap-2">
              <a href={OWNER.linkedin} target="_blank" rel="noreferrer" className="btn-secondary h-9 px-3 text-xs">
                LinkedIn
              </a>
              <a href={OWNER.github} target="_blank" rel="noreferrer" className="btn-secondary h-9 px-3 text-xs">
                GitHub
              </a>
              <a href={`mailto:${OWNER.email}`} className="btn-secondary h-9 px-3 text-xs">
                Email
              </a>
              {OWNER.resumeUrl ? (
                <a href={OWNER.resumeUrl} target="_blank" rel="noreferrer" className="btn-secondary h-9 px-3 text-xs">
                  Résumé
                </a>
              ) : null}
            </div>
          </div>
        </div>
      </section>

      <section className="rounded-2xl border border-amber-500/30 bg-amber-500/10 p-5 text-sm leading-6 text-amber-100">
        <span className="font-semibold">Heads-up: live data is paused.</span> I stopped paying for the market-data API
        while I&apos;m not actively developing the project, so prices end
        {status.market_data_as_of ? <> on {fmtLongDate(status.market_data_as_of)}</> : " at the last sync"}. Everything
        you&apos;ll see is real production data as of that day. Subscriptions are closed, and the whole app is open
        through the demo account.
        {!status.ai_classification_enabled ? (
          <>
            {" "}
            New filings are still being ingested, but AI classification is paused due to a temporary halt in
            development, so recent filings won&apos;t have AI ratings.
          </>
        ) : null}
      </section>

      {stats && stats.filings > 0 ? (
        <section className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          <Stat
            label="Form 4 filings ingested"
            value={stats.filings.toLocaleString()}
            helper={stats.first_filing_date ? `${fmtLongDate(stats.first_filing_date)} – ${fmtLongDate(stats.last_filing_date)}` : undefined}
          />
          <Stat label="Insider events analyzed" value={stats.insider_events.toLocaleString()} helper="One per insider per filing" />
          <Stat label="Companies covered" value={stats.issuers.toLocaleString()} />
          <Stat label="AI ratings generated" value={stats.ai_ratings.toLocaleString()} helper="Schema-validated Gemini outputs" />
        </section>
      ) : null}

      <section className="space-y-5">
        <div>
          <div className="text-xs font-semibold uppercase tracking-[0.18em] text-zinc-500">The tour</div>
          <h2 className="mt-2 text-3xl font-semibold text-zinc-100">What you&apos;ll see</h2>
          <p className="mt-2 max-w-2xl text-sm leading-7 text-zinc-400">
            Each stop opens a real page and points at the part worth looking at, with a short &quot;under the hood&quot;
            note on how it works. Jump in anywhere.
          </p>
        </div>
        <ol className="grid gap-3 md:grid-cols-2 lg:grid-cols-3">
          {TOUR_STEPS.map((step, i) => (
            <li key={step.id}>
              <button
                type="button"
                onClick={() => void tour.start(i)}
                disabled={tour.starting}
                className="group flex h-full w-full items-start gap-3 rounded-xl border border-zinc-800/70 bg-black/35 p-4 text-left transition hover:border-cyan-500/40 hover:bg-cyan-500/5"
              >
                <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full border border-zinc-700 text-xs font-semibold text-zinc-300 group-hover:border-cyan-400/60 group-hover:text-cyan-200">
                  {i + 1}
                </span>
                <span>
                  <span className="block text-[11px] font-semibold uppercase tracking-[0.16em] text-zinc-500">{step.eyebrow}</span>
                  <span className="mt-1 block text-sm font-semibold text-zinc-100">{step.title}</span>
                </span>
              </button>
            </li>
          ))}
        </ol>
      </section>

      <section className="space-y-5">
        <div>
          <div className="text-xs font-semibold uppercase tracking-[0.18em] text-zinc-500">Architecture</div>
          <h2 className="mt-2 text-3xl font-semibold text-zinc-100">How the pieces fit</h2>
        </div>
        <div className="glass-panel space-y-6 p-6 dark:bg-zinc-950/55">
          <Lane label="Ingest">
            <Node>SEC EDGAR Form 4 feed</Node>
            <Arrow />
            <Node>Poller (every ~2 min)</Node>
            <Arrow />
            <Node tone="purple">Job queue in Postgres · dedupe, priorities, retries</Node>
          </Lane>
          <Lane label="Compute">
            <Node>Parse &amp; aggregate</Node>
            <Node>Cluster detection</Node>
            <Node>Prices &amp; trend features</Node>
            <Node>60/180-day outcomes vs SPY</Node>
            <Node>Insider win-rate stats</Node>
            <Node tone="cyan">Gemini rating · schema-validated</Node>
          </Lane>
          <Lane label="Serve">
            <Node tone="purple">PostgreSQL</Node>
            <Arrow />
            <Node>FastAPI</Node>
            <Arrow />
            <Node>Caddy · HTTPS</Node>
            <Arrow />
            <Node>React + TypeScript SPA</Node>
          </Lane>
          <Lane label="External">
            <Node tone="cyan">Stripe · Checkout, Portal, signed webhooks</Node>
            <Node tone="amber">EODHD market data · paused</Node>
            <Node>X API · admin posting tool</Node>
          </Lane>
          <p className="text-xs leading-6 text-zinc-500">
            Everything runs as Docker Compose services on one Linux VM: Postgres, the API, an API worker, a compute
            worker, and Caddy.
          </p>
        </div>
      </section>

      <section className="grid gap-8 lg:grid-cols-2">
        <div>
          <div className="text-xs font-semibold uppercase tracking-[0.18em] text-zinc-500">Software engineering</div>
          <ul className="mt-4 space-y-3">
            <Highlight title="Designed and shipped the whole stack">
              FastAPI backend, React/TypeScript frontend, Postgres schema and migrations, background workers, and the
              deployment. Solo, from first commit to paying users.
            </Highlight>
            <Highlight title="A pipeline that survives real-world data">
              Idempotent job queue with dedupe keys and retries, versioned parse/compute stages that can be replayed,
              and validation caches for messy ticker mappings.
            </Highlight>
            <Highlight title="Payments and access control">
              Stripe subscriptions with trials and webhooks, cookie-based JWT auth, role-based admin views, and a
              read-only showcase role that masks customer data.
            </Highlight>
          </ul>
        </div>
        <div>
          <div className="text-xs font-semibold uppercase tracking-[0.18em] text-zinc-500">Quant &amp; finance</div>
          <ul className="mt-4 space-y-3">
            <Highlight title="Signal quality, measured honestly">
              Forward returns at 60 and 180 trading days from the first tradeable day after each filing went public,
              net of SPY, rolled up into each insider&apos;s win rate and average excess return.
            </Highlight>
            <Highlight title="Feature engineering">
              Cluster buying (2+ insiders in 14 days), pre-trade momentum, 52-week range position, 50/200-day moving
              averages, holdings change, and insider role.
            </Highlight>
            <Highlight title="LLM as a scoring layer, not an oracle">
              Gemini sees structured features only, answers in strict JSON checked against a schema, and never
              re-scores unchanged inputs.
            </Highlight>
          </ul>
        </div>
      </section>

      <section>
        <div className="text-xs font-semibold uppercase tracking-[0.18em] text-zinc-500">Stack</div>
        <div className="mt-4 flex flex-wrap gap-2">
          {STACK.map((s) => (
            <span key={s} className="rounded-full border border-zinc-800/80 bg-black/35 px-3 py-1.5 text-sm text-zinc-300">
              {s}
            </span>
          ))}
        </div>
      </section>

      <section
        data-tour="contact"
        className="relative overflow-hidden rounded-[2rem] border border-purple-500/20 bg-gradient-to-r from-purple-500/12 via-zinc-950/80 to-cyan-500/12 p-8"
      >
        <div className="relative flex flex-col gap-6 lg:flex-row lg:items-center lg:justify-between">
          <div className="max-w-2xl">
            <div className="text-2xl font-semibold text-zinc-100">Let&apos;s talk</div>
            <p className="mt-2 text-sm leading-7 text-zinc-300">
              I&apos;m looking for software engineering and quantitative/finance co-ops for January – August 2027. Happy to
              walk through any part of this codebase.
            </p>
          </div>
          <div className="flex flex-wrap gap-3">
            <a href={`mailto:${OWNER.email}`} className="btn-primary h-11 px-6">
              Email me
            </a>
            <a href={OWNER.linkedin} target="_blank" rel="noreferrer" className="btn-secondary h-11 px-6">
              LinkedIn
            </a>
            <Link to="/" className="btn-ghost h-11 px-4">
              Back to the site
            </Link>
          </div>
        </div>
      </section>
    </div>
  );
}
