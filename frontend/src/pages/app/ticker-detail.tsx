"use client";

import * as React from "react";
import { useParams } from "react-router-dom";

import { EventCard } from "@/components/event-card";
import { useAuth } from "@/components/auth-provider";
import { apiFetch } from "@/lib/api";
import { fmtDate, fmtInt } from "@/lib/format";
import type { InsiderEventRow } from "@/lib/types";

type EventsResponse = {
  ticker: string;
  issuer: { issuer_cik?: string; issuer_name?: string | null } | null;
  market_cap: { market_cap_bucket?: string | null } | null;
  events: InsiderEventRow[];
  next_offset: number | null;
  total?: number | null;
  reparse_needed?: boolean;
  reparse_enqueued?: boolean;
};

const QUICK_DOLLARS = [
  { label: "Any size", value: "" },
  { label: ">= $100k", value: "100000" },
  { label: ">= $500k", value: "500000" },
  { label: ">= $1m", value: "1000000" },
];

function ToggleChip({ active, children, onClick }: { active: boolean; children: React.ReactNode; onClick: () => void }) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={[
        "rounded-xl border px-4 py-2 text-sm transition",
        active
          ? "border-purple-500/40 bg-purple-500/15 text-purple-700 dark:text-purple-300"
          : "border-zinc-200/80 bg-white/60 text-zinc-700 hover:border-zinc-300 dark:border-zinc-800/60 dark:bg-black/25 dark:text-zinc-300 dark:hover:border-zinc-700",
      ].join(" ")}
    >
      {children}
    </button>
  );
}

export function TickerDetailPage() {
  const params = useParams<{ ticker: string }>();
  const ticker = (params?.ticker || "").toString().toUpperCase();

  const { user } = useAuth();
  const isAdmin = user?.role === "admin";

  const [events, setEvents] = React.useState<InsiderEventRow[]>([]);
  const [issuer, setIssuer] = React.useState<EventsResponse["issuer"]>(null);
  const [marketCap, setMarketCap] = React.useState<EventsResponse["market_cap"]>(null);
  const [nextOffset, setNextOffset] = React.useState<number | null>(0);
  const [loading, setLoading] = React.useState(true);
  const [loadingMore, setLoadingMore] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);

  const [clusterOnly, setClusterOnly] = React.useState(false);
  const [aiOnly, setAiOnly] = React.useState(false);
  const [side, setSide] = React.useState<"both" | "buy" | "sell">("both");
  const [officerOnly, setOfficerOnly] = React.useState(false);
  const [directorOnly, setDirectorOnly] = React.useState(false);
  const [tenPercentOnly, setTenPercentOnly] = React.useState(false);
  const [minDollars, setMinDollars] = React.useState<string>("");
  const [sortBy, setSortBy] = React.useState<"filing_date_desc" | "ai_best_desc">("filing_date_desc");
  const [showAllEvents, setShowAllEvents] = React.useState(false);

  const queryString = React.useMemo(() => {
    const sp = new URLSearchParams();
    sp.set("limit", "36");
    sp.set("offset", "0");
    sp.set("sort_by", sortBy);
    sp.set("side", side);
    sp.set("cluster_only", clusterOnly ? "true" : "false");
    sp.set("ai_only", aiOnly ? "true" : "false");
    sp.set("officer_only", officerOnly ? "true" : "false");
    sp.set("director_only", directorOnly ? "true" : "false");
    sp.set("ten_percent_only", tenPercentOnly ? "true" : "false");
    if (minDollars) {
      sp.set("min_dollars", minDollars);
      sp.set("dollars_side", "either");
    }
    if (isAdmin && showAllEvents) {
      sp.set("open_market_only", "false");
    }
    return sp.toString();
  }, [aiOnly, clusterOnly, directorOnly, isAdmin, minDollars, officerOnly, showAllEvents, side, sortBy, tenPercentOnly]);

  async function fetchPage(offset: number, mode: "replace" | "append") {
    const sp = new URLSearchParams(queryString);
    sp.set("offset", String(offset));

    const res = await apiFetch(`/ticker/${encodeURIComponent(ticker)}/events?${sp.toString()}`, { cache: "no-store" });
    if (!res.ok) throw new Error(await res.text());
    const data = (await res.json()) as EventsResponse;

    setIssuer(data.issuer ?? null);
    setMarketCap(data.market_cap ?? null);
    setNextOffset(data.next_offset ?? null);
    if (mode === "replace") {
      setEvents(data.events ?? []);
    } else {
      setEvents((prev) => [...prev, ...(data.events ?? [])]);
    }
  }

  React.useEffect(() => {
    let cancelled = false;
    (async () => {
      setLoading(true);
      setError(null);
      try {
        await fetchPage(0, "replace");
      } catch (e: any) {
        if (!cancelled) setError(e?.message || "Failed to load events");
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ticker, queryString]);

  const loadMore = async () => {
    if (nextOffset === null) return;
    setLoadingMore(true);
    setError(null);
    try {
      await fetchPage(nextOffset, "append");
    } catch (e: any) {
      setError(e?.message || "Failed to load more events");
    } finally {
      setLoadingMore(false);
    }
  };

  const title = issuer?.issuer_name ? `${ticker} — ${issuer.issuer_name}` : ticker;

  return (
    <div className="space-y-6">
      <div data-tour="ticker-header" className="glass-panel p-6">
        <div className="flex flex-col gap-4 xl:flex-row xl:items-end xl:justify-between">
          <div className="max-w-3xl">
            <div className="text-xs font-semibold uppercase tracking-[0.18em] muted">Ticker detail</div>
            <h1 className="mt-2 text-3xl font-semibold text-zinc-900 dark:text-zinc-100">{title}</h1>
            <p className="mt-2 text-sm muted">
              Filter this issuer’s insider activity and scan it in the same compact card format used across the event feed.
            </p>
          </div>

          <div className="grid gap-3 sm:grid-cols-3 xl:w-[520px]">
            <div className="rounded-2xl border border-zinc-200/70 bg-white/50 p-4 dark:border-zinc-800/60 dark:bg-black/20">
              <div className="text-xs uppercase tracking-[0.16em] muted">Ticker</div>
              <div className="mt-2 text-xl font-semibold">{ticker}</div>
            </div>
            <div className="rounded-2xl border border-zinc-200/70 bg-white/50 p-4 dark:border-zinc-800/60 dark:bg-black/20">
              <div className="text-xs uppercase tracking-[0.16em] muted">CIK</div>
              <div className="mt-2 text-xl font-semibold">{issuer?.issuer_cik || "—"}</div>
            </div>
            <div className="rounded-2xl border border-zinc-200/70 bg-white/50 p-4 dark:border-zinc-800/60 dark:bg-black/20">
              <div className="text-xs uppercase tracking-[0.16em] muted">Cap bucket</div>
              <div className="mt-2 text-xl font-semibold">{marketCap?.market_cap_bucket || "—"}</div>
            </div>
          </div>
        </div>

        <div className="mt-6 grid gap-4 lg:grid-cols-[220px_220px_200px] xl:grid-cols-[220px_220px_200px_auto]">
          <select value={sortBy} onChange={(e) => setSortBy(e.target.value as any)} className="input h-12">
            <option value="filing_date_desc">Most recent</option>
            <option value="ai_best_desc">Best event AI</option>
          </select>
          <select value={side} onChange={(e) => setSide(e.target.value as any)} className="input h-12">
            <option value="both">Both sides</option>
            <option value="buy">Buys only</option>
            <option value="sell">Sells only</option>
          </select>
          <select value={minDollars} onChange={(e) => setMinDollars(e.target.value)} className="input h-12">
            {QUICK_DOLLARS.map((option) => (
              <option key={option.label} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>
          <div className="flex flex-wrap gap-2">
            <ToggleChip active={clusterOnly} onClick={() => setClusterOnly((value) => !value)}>Cluster only</ToggleChip>
            <ToggleChip active={aiOnly} onClick={() => setAiOnly((value) => !value)}>AI only</ToggleChip>
            <ToggleChip active={officerOnly} onClick={() => setOfficerOnly((value) => !value)}>Officer</ToggleChip>
            <ToggleChip active={directorOnly} onClick={() => setDirectorOnly((value) => !value)}>Director</ToggleChip>
            <ToggleChip active={tenPercentOnly} onClick={() => setTenPercentOnly((value) => !value)}>10% owner</ToggleChip>
            {isAdmin ? <ToggleChip active={showAllEvents} onClick={() => setShowAllEvents((value) => !value)}>Admin: all</ToggleChip> : null}
          </div>
        </div>
      </div>

      {error ? <div className="rounded-2xl border border-red-500/30 bg-red-500/10 px-4 py-3 text-sm text-red-700 dark:text-red-300">{error}</div> : null}

      {loading ? (
        <div className="glass-card p-6 text-sm muted">Loading ticker events…</div>
      ) : (
        <>
          <div className="text-sm muted">Showing {fmtInt(events.length)} event(s)</div>

          {events.length === 0 ? (
            <div className="glass-panel p-10 text-center">
              <div className="text-lg font-semibold text-zinc-900 dark:text-zinc-100">No events matched</div>
              <div className="mt-2 text-sm muted">Try widening the side or size filters for this ticker.</div>
            </div>
          ) : (
            <div className="grid grid-cols-1 gap-4 xl:grid-cols-2 2xl:grid-cols-3">
              {events.map((event) => (
                <EventCard key={`${event.issuer_cik}|${event.owner_key}|${event.accession_number}`} event={event} />
              ))}
            </div>
          )}

          {nextOffset !== null ? (
            <div className="flex justify-center pt-2">
              <button type="button" onClick={loadMore} disabled={loadingMore} className="btn-secondary h-10 px-4">
                {loadingMore ? "Loading…" : "Load more"}
              </button>
            </div>
          ) : null}
        </>
      )}
    </div>
  );
}
