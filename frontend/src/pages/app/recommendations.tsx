import * as React from "react";
import { Link } from "react-router-dom";

import { EventCard } from "@/components/event-card";
import { apiFetch } from "@/lib/api";
import { dedupeEventsByFiling } from "@/lib/event-utils";
import type { InsiderEventRow, UserProfileRecord, UserProfilePreferences } from "@/lib/types";


type RecommendationsResponse = {
  days: number;
  limit: number;
  offset: number;
  next_offset: number | null;
  applied: UserProfilePreferences;
  profile?: UserProfileRecord;
  events: InsiderEventRow[];
};

function prettyDetail(detail: string | null | undefined): string {
  switch ((detail || "").trim()) {
    case "subscription_required":
      return "An active subscription is required to view this page.";
    default:
      return detail || "Failed to load recommendations.";
  }
}

async function getErrorMessage(res: Response): Promise<string> {
  try {
    const data = await res.json();
    return prettyDetail(typeof data?.detail === "string" ? data.detail : JSON.stringify(data));
  } catch {
    const txt = await res.text().catch(() => "");
    return prettyDetail(txt || `HTTP ${res.status}`);
  }
}

function SummaryCard({ label, value, helper }: { label: string; value: string; helper?: string }) {
  return (
    <div className="rounded-2xl border border-zinc-200/70 bg-white/50 p-4 dark:border-zinc-800/60 dark:bg-black/20">
      <div className="text-xs font-semibold uppercase tracking-[0.16em] muted">{label}</div>
      <div className="mt-2 text-lg font-semibold text-zinc-900 dark:text-zinc-100">{value}</div>
      {helper ? <div className="mt-1 text-sm muted">{helper}</div> : null}
    </div>
  );
}

function FilterChip({ children }: { children: React.ReactNode }) {
  return <span className="badge px-3 py-1 text-xs">{children}</span>;
}

export function RecommendationsPage() {
  const [days, setDays] = React.useState<number>(30);
  const [searchQuery, setSearchQuery] = React.useState("");
  const [loading, setLoading] = React.useState(true);
  const [loadingMore, setLoadingMore] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);

  const [applied, setApplied] = React.useState<UserProfilePreferences | null>(null);
  const [profile, setProfile] = React.useState<UserProfileRecord | null>(null);
  const [rawEvents, setRawEvents] = React.useState<InsiderEventRow[]>([]);
  const [nextOffset, setNextOffset] = React.useState<number | null>(null);

  const loadRecommendations = React.useCallback(
    async (mode: "replace" | "append") => {
      const offset = mode === "append" ? nextOffset ?? 0 : 0;
      if (mode === "append" && nextOffset === null) return;

      if (mode === "replace") {
        setLoading(true);
      } else {
        setLoadingMore(true);
      }
      setError(null);

      try {
        const url = new URL("/recommendations", window.location.origin);
        url.searchParams.set("days", String(days));
        url.searchParams.set("limit", "60");
        url.searchParams.set("offset", String(offset));

        const res = await apiFetch(url.pathname + url.search, { cache: "no-store" });
        if (!res.ok) throw new Error(await getErrorMessage(res));

        const json = (await res.json()) as RecommendationsResponse;
        setApplied(json.applied ?? null);
        setProfile((json.profile as UserProfileRecord) ?? null);
        setNextOffset(json.next_offset ?? null);
        setRawEvents((prev) => (mode === "append" ? [...prev, ...(json.events || [])] : json.events || []));
      } catch (e: any) {
        setError(e?.message || "Failed to load recommendations.");
      } finally {
        if (mode === "replace") {
          setLoading(false);
        } else {
          setLoadingMore(false);
        }
      }
    },
    [days, nextOffset]
  );

  React.useEffect(() => {
    void loadRecommendations("replace");
  }, [loadRecommendations]);

  const dedupedEvents = React.useMemo(() => dedupeEventsByFiling(rawEvents), [rawEvents]);

  const filteredEvents = React.useMemo(() => {
    const q = searchQuery.trim().toLowerCase();
    if (!q) return dedupedEvents;
    return dedupedEvents.filter((event) => {
      const ticker = String((event as any).ticker || "").toLowerCase();
      const issuer = String((event as any).issuer_name || "").toLowerCase();
      const owner = String((event as any).owner_name_display || "").toLowerCase();
      const sector = String((event as any).sector || "").toLowerCase();
      return ticker.includes(q) || issuer.includes(q) || owner.includes(q) || sector.includes(q);
    });
  }, [dedupedEvents, searchQuery]);

  const sectors = applied?.preferred_sectors ?? [];
  const sideLabel = applied?.trade_side === "both" ? "Buys + sells" : applied?.trade_side === "sell" ? "Sells only" : "Buys only";
  const minAi = typeof applied?.min_ai_rating === "number" ? applied.min_ai_rating.toFixed(1) : "7.0";
  const betaLabel = applied?.max_beta === null || applied?.max_beta === undefined ? "No cap" : String(applied.max_beta);
  const updatedAt = profile?.updated_at || profile?.created_at || null;

  return (
    <div className="space-y-6">
      <div className="glass-panel p-6">
        <div className="flex flex-col gap-4 xl:flex-row xl:items-start xl:justify-between">
          <div className="max-w-3xl">
            <div className="text-xs font-semibold uppercase tracking-[0.18em] muted">Personalized feed</div>
            <h1 className="mt-2 text-3xl font-semibold text-zinc-900 dark:text-zinc-100">
              <span className="bg-gradient-to-r from-purple-500 via-cyan-500 to-blue-500 bg-clip-text text-transparent">For you</span>
            </h1>
            <p className="mt-2 text-sm muted">
              The platform’s strongest recent insider events, filtered through your saved profile settings.
            </p>
            {updatedAt ? <div className="mt-3 text-xs muted">Using profile updated {updatedAt}</div> : null}
          </div>

          <div className="flex flex-wrap gap-3">
            <Link to="/app/profile" className="btn-secondary h-10 px-4">
              Edit profile
            </Link>
            <button type="button" className="btn-primary h-10 px-4" onClick={() => void loadRecommendations("replace")} disabled={loading}>
              {loading ? "Refreshing…" : "Refresh feed"}
            </button>
          </div>
        </div>

        <div data-tour="for-you-summary" className="mt-6 grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
          <SummaryCard label="Visible signals" value={filteredEvents.length.toLocaleString()} helper={`${dedupedEvents.length.toLocaleString()} loaded`} />
          <SummaryCard label="Trade side" value={sideLabel} helper={`Lookback ${days} days`} />
          <SummaryCard label="Minimum AI" value={`${minAi} / 10`} helper="Saved in your profile" />
          <SummaryCard label="Beta + sectors" value={sectors.length === 0 ? "All sectors" : `${sectors.length} selected`} helper={`Max beta: ${betaLabel}`} />
        </div>
      </div>

      <div className="glass-panel p-5">
        <div className="grid gap-4 lg:grid-cols-[220px_minmax(0,1fr)]">
          <div>
            <label className="text-sm font-medium text-zinc-900 dark:text-zinc-100">Lookback window</label>
            <select className="input mt-2 h-11" value={days} onChange={(e) => setDays(Number(e.target.value))}>
              <option value={7}>7 days</option>
              <option value={14}>14 days</option>
              <option value={30}>30 days</option>
              <option value={60}>60 days</option>
              <option value={90}>90 days</option>
              <option value={180}>180 days</option>
            </select>
          </div>

          <div>
            <label className="text-sm font-medium text-zinc-900 dark:text-zinc-100">Search within your feed</label>
            <input
              className="input mt-2 h-11"
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              placeholder="Search by ticker, company, sector, or insider name…"
            />
          </div>
        </div>

        <div className="mt-4 flex flex-wrap items-center gap-2">
          <FilterChip>{sideLabel}</FilterChip>
          <FilterChip>AI ≥ {minAi}</FilterChip>
          <FilterChip>{applied?.max_beta === null || applied?.max_beta === undefined ? "Any beta" : `Beta ≤ ${applied.max_beta}`}</FilterChip>
          {sectors.length === 0 ? <FilterChip>All sectors</FilterChip> : null}
          {sectors.slice(0, 8).map((sector) => (
            <FilterChip key={sector}>{sector}</FilterChip>
          ))}
          {sectors.length > 8 ? <span className="text-xs muted">+{sectors.length - 8} more</span> : null}
        </div>
      </div>

      {error ? <div className="rounded-2xl border border-red-500/30 bg-red-500/10 px-4 py-3 text-sm text-red-700 dark:text-red-300">{error}</div> : null}

      {loading ? (
        <div className="glass-panel p-10 text-center">
          <div className="text-lg font-semibold text-zinc-900 dark:text-zinc-100">Building your feed…</div>
          <div className="mt-2 text-sm muted">Scanning recent filings that match your saved preferences.</div>
        </div>
      ) : filteredEvents.length === 0 ? (
        <div className="glass-panel p-10 text-center">
          <div className="text-lg font-semibold text-zinc-900 dark:text-zinc-100">No recommendations right now</div>
          <div className="mt-2 text-sm muted">
            Try lowering your minimum AI threshold, broadening your sectors, or expanding the lookback window.
          </div>
          <div className="mt-5 flex justify-center">
            <Link to="/app/profile" className="btn-primary h-10 px-4">
              Update profile settings
            </Link>
          </div>
        </div>
      ) : (
        <>
          <div className="flex items-center justify-between gap-3">
            <div className="text-sm muted">
              Showing {filteredEvents.length.toLocaleString()} personalized event{filteredEvents.length === 1 ? "" : "s"}
            </div>
            <Link to="/app/events" className="link text-sm">
              Browse the full event feed
            </Link>
          </div>

          <div className="grid grid-cols-1 gap-4 xl:grid-cols-2 2xl:grid-cols-3">
            {filteredEvents.map((event) => (
              <EventCard key={`${event.issuer_cik}|${event.owner_key}|${event.accession_number}`} event={event} />
            ))}
          </div>

          {nextOffset !== null ? (
            <div className="flex justify-center pt-2">
              <button type="button" onClick={() => void loadRecommendations("append")} disabled={loadingMore} className="btn-secondary h-10 px-4">
                {loadingMore ? "Loading…" : "Load more"}
              </button>
            </div>
          ) : null}
        </>
      )}
    </div>
  );
}
