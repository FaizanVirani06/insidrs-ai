"use client";

import * as React from "react";

import type { InsiderEventRow } from "@/lib/types";
import { apiFetch } from "@/lib/api";
import { EventCard } from "@/components/event-card";

const LOOKBACK_OPTIONS: { label: string; value: number }[] = [
  { label: "7 days", value: 7 },
  { label: "30 days", value: 30 },
  { label: "90 days", value: 90 },
  { label: "180 days", value: 180 },
  { label: "365 days", value: 365 },
  { label: "2 years", value: 730 },
];

type EventsResponse = {
  days?: number;
  limit?: number;
  offset?: number;
  sort_by?: string;
  side?: string;
  events: InsiderEventRow[];
};

function FilterChip({
  active,
  onClick,
  children,
}: {
  active: boolean;
  onClick: () => void;
  children: React.ReactNode;
}) {
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

export function EventsPage() {
  const [days, setDays] = React.useState<number>(30);
  const [side, setSide] = React.useState<"both" | "buy" | "sell">("both");
  const [sortBy, setSortBy] = React.useState<"filing_date_desc" | "ai_best_desc" | "sector_asc">("filing_date_desc");
  const [searchQuery, setSearchQuery] = React.useState<string>("");

  const [loading, setLoading] = React.useState<boolean>(true);
  const [error, setError] = React.useState<string | null>(null);
  const [data, setData] = React.useState<EventsResponse | null>(null);
  const [refreshKey, setRefreshKey] = React.useState(0);

  const aiOnly = sortBy === "ai_best_desc";

  async function load() {
    setLoading(true);
    setError(null);
    try {
      const url = new URL("/api/backend/events", window.location.origin);
      url.searchParams.set("days", String(days));
      url.searchParams.set("side", side);
      url.searchParams.set("sort_by", sortBy);
      url.searchParams.set("ai_only", aiOnly ? "true" : "false");
      url.searchParams.set("open_market_only", "true");
      url.searchParams.set("limit", "120");

      const res = await apiFetch(url.pathname + url.search, { cache: "no-store" });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const json = (await res.json()) as EventsResponse;
      setData(json);
    } catch (e: any) {
      setError(e?.message ?? "Failed to load events");
    } finally {
      setLoading(false);
    }
  }

  React.useEffect(() => {
    void load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [days, side, sortBy, refreshKey]);

  const events = React.useMemo(() => {
    const list = (data?.events ?? []) as InsiderEventRow[];
    const q = searchQuery.trim().toLowerCase();
    if (!q) return list;
    return list.filter((event) => {
      const ticker = String((event as any).ticker ?? "").toLowerCase();
      const issuer = String((event as any).issuer_name ?? "").toLowerCase();
      const sector = String((event as any).sector ?? "").toLowerCase();
      const owner = String((event as any).owner_name_display ?? (event as any).owner_key ?? "").toLowerCase();
      return ticker.includes(q) || issuer.includes(q) || sector.includes(q) || owner.includes(q);
    });
  }, [data, searchQuery]);

  return (
    <div className="space-y-6">
      <div data-tour="events-feed" className="glass-panel p-6">
        <div className="flex flex-col gap-4 xl:flex-row xl:items-end xl:justify-between">
          <div className="max-w-3xl">
            <div className="text-xs font-semibold uppercase tracking-[0.18em] muted">Insider activity</div>
            <h1 className="mt-2 text-3xl font-semibold text-zinc-900 dark:text-zinc-100">Event feed</h1>
            <p className="mt-2 text-sm muted">
              Browse recent insider buys and sells in a compact signal grid. Cards only surface the side-specific data that actually exists for each filing.
            </p>
          </div>

          <div className="grid gap-3 sm:grid-cols-3 xl:w-[520px]">
            <div className="rounded-2xl border border-zinc-200/70 bg-white/50 p-4 dark:border-zinc-800/60 dark:bg-black/20">
              <div className="text-xs uppercase tracking-[0.16em] muted">Window</div>
              <div className="mt-2 text-xl font-semibold">{days}d</div>
            </div>
            <div className="rounded-2xl border border-zinc-200/70 bg-white/50 p-4 dark:border-zinc-800/60 dark:bg-black/20">
              <div className="text-xs uppercase tracking-[0.16em] muted">Results</div>
              <div className="mt-2 text-xl font-semibold">{loading ? "…" : events.length.toLocaleString()}</div>
            </div>
            <div className="rounded-2xl border border-zinc-200/70 bg-white/50 p-4 dark:border-zinc-800/60 dark:bg-black/20">
              <div className="text-xs uppercase tracking-[0.16em] muted">Sort</div>
              <div className="mt-2 text-xl font-semibold">{sortBy === "ai_best_desc" ? "Best AI" : sortBy === "sector_asc" ? "Sector" : "Newest"}</div>
            </div>
          </div>
        </div>

        <div className="mt-6 grid gap-4 lg:grid-cols-[minmax(0,1fr)_auto_auto]">
          <input
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            placeholder="Search ticker, company, sector, or insider…"
            className="input h-12"
          />
          <select className="input h-12 min-w-[170px]" value={sortBy} onChange={(e) => setSortBy(e.target.value as any)}>
            <option value="filing_date_desc">Most recent</option>
            <option value="ai_best_desc">Best event AI</option>
            <option value="sector_asc">Sector (A–Z)</option>
          </select>
          <select className="input h-12 min-w-[150px]" value={days} onChange={(e) => setDays(parseInt(e.target.value, 10))}>
            {LOOKBACK_OPTIONS.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>
        </div>

        <div className="mt-4 flex flex-wrap items-center gap-2">
          <FilterChip active={side === "both"} onClick={() => setSide("both")}>All trades</FilterChip>
          <FilterChip active={side === "buy"} onClick={() => setSide("buy")}>Buys</FilterChip>
          <FilterChip active={side === "sell"} onClick={() => setSide("sell")}>Sells</FilterChip>
          <button type="button" className="btn-secondary h-10 px-4" onClick={() => setRefreshKey((value) => value + 1)}>
            Refresh
          </button>
        </div>
      </div>

      {error ? (
        <div className="rounded-2xl border border-red-500/30 bg-red-500/10 px-4 py-3 text-sm text-red-700 dark:text-red-300">{error}</div>
      ) : null}

      {loading ? (
        <div className="glass-card p-6 text-sm muted">Loading events…</div>
      ) : events.length === 0 ? (
        <div className="glass-panel p-10 text-center">
          <div className="text-lg font-semibold text-zinc-900 dark:text-zinc-100">No events found</div>
          <div className="mt-2 text-sm muted">Try broadening your search, switching sides, or extending the lookback window.</div>
        </div>
      ) : (
        <div className="grid grid-cols-1 gap-4 lg:grid-cols-2 2xl:grid-cols-3">
          {events.map((event) => (
            <EventCard key={`${event.issuer_cik}|${event.owner_key}|${event.accession_number}`} event={event} />
          ))}
        </div>
      )}
    </div>
  );
}
