import * as React from "react";

import { fmtAiRating, fmtDate, fmtDollars, fmtInt, fmtNumber, fmtUsd } from "@/lib/format";

type AdminAiInputsPanelProps = {
  input: any;
};

type DisplayRow = [string, string | null];

function filterRows(rows: DisplayRow[]): DisplayRow[] {
  return rows.filter((row) => row[1] !== null);
}

function hasRows(rows: DisplayRow[]): boolean {
  return rows.some((row) => row[1] !== null);
}

function toNumber(value: unknown): number | null {
  if (value === null || value === undefined || value === "") return null;
  const n = Number(value);
  return Number.isFinite(n) ? n : null;
}

function toText(value: unknown): string | null {
  if (value === null || value === undefined) return null;
  const text = String(value).trim();
  return text || null;
}

function boolText(value: unknown): string | null {
  if (value === null || value === undefined) return null;
  return value ? "Yes" : "No";
}

function formatPercentAuto(value: unknown, digits = 1): string | null {
  const n = toNumber(value);
  if (n === null) return null;
  if (Math.abs(n) <= 1) return `${(n * 100).toFixed(digits)}%`;
  return `${n.toFixed(digits)}%`;
}

function formatPercentFraction(value: unknown, digits = 1): string | null {
  const n = toNumber(value);
  if (n === null) return null;
  return `${(n * 100).toFixed(digits)}%`;
}

function formatUsdExact(value: unknown, digits = 2): string | null {
  const n = toNumber(value);
  if (n === null) return null;
  return fmtUsd(n, { digits });
}

function formatCompactUsd(value: unknown): string | null {
  const n = toNumber(value);
  if (n === null) return null;
  return fmtDollars(n);
}

function formatIntValue(value: unknown): string | null {
  const n = toNumber(value);
  if (n === null) return null;
  return fmtInt(n);
}

function formatDecimal(value: unknown, digits = 2): string | null {
  const n = toNumber(value);
  if (n === null) return null;
  return fmtNumber(n, { digits });
}

function hasContent(value: unknown): boolean {
  if (value === null || value === undefined) return false;
  if (typeof value === "string") return value.trim().length > 0;
  if (typeof value === "number") return Number.isFinite(value);
  if (typeof value === "boolean") return true;
  if (Array.isArray(value)) return value.length > 0;
  if (typeof value === "object") return Object.values(value as Record<string, unknown>).some(hasContent);
  return false;
}

function DataRow({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="flex items-start justify-between gap-4 border-b border-zinc-200/60 py-2 text-sm last:border-b-0 dark:border-zinc-800/60">
      <div className="muted">{label}</div>
      <div className="text-right font-medium text-zinc-100">{value}</div>
    </div>
  );
}

function MiniStat({
  label,
  value,
  helper,
}: {
  label: string;
  value: React.ReactNode;
  helper?: React.ReactNode;
}) {
  return (
    <div className="rounded-2xl border border-zinc-800/60 bg-black/20 p-4">
      <div className="text-[11px] font-semibold uppercase tracking-[0.18em] muted">{label}</div>
      <div className="mt-2 text-lg font-semibold text-zinc-100">{value}</div>
      {helper ? <div className="mt-1 text-xs muted">{helper}</div> : null}
    </div>
  );
}

function BadgeList({
  items,
  tone = "zinc",
}: {
  items: string[];
  tone?: "zinc" | "purple" | "cyan" | "emerald" | "amber";
}) {
  const toneClass =
    tone === "purple"
      ? "border-purple-500/30 bg-purple-500/10 text-purple-300"
      : tone === "cyan"
        ? "border-cyan-500/30 bg-cyan-500/10 text-cyan-300"
        : tone === "emerald"
          ? "border-emerald-500/30 bg-emerald-500/10 text-emerald-300"
          : tone === "amber"
            ? "border-amber-500/30 bg-amber-500/10 text-amber-300"
            : "border-zinc-700 bg-zinc-900/70 text-zinc-300";

  if (items.length === 0) return null;

  return (
    <div className="mt-3 flex flex-wrap gap-2">
      {items.map((item) => (
        <span
          key={item}
          className={["inline-flex rounded-full border px-2.5 py-1 text-xs font-medium", toneClass].join(" ")}
        >
          {item}
        </span>
      ))}
    </div>
  );
}

function SectionCard({
  title,
  subtitle,
  children,
}: {
  title: string;
  subtitle?: string;
  children: React.ReactNode;
}) {
  return (
    <section className="glass-card p-5">
      <div className="flex flex-col gap-1">
        <h3 className="text-base font-semibold text-zinc-100">{title}</h3>
        {subtitle ? <p className="text-sm muted">{subtitle}</p> : null}
      </div>
      <div className="mt-4">{children}</div>
    </section>
  );
}

function TradeLegCard({ side, leg }: { side: "buy" | "sell"; leg: any }) {
  const label = side === "buy" ? "Buy leg" : "Sell leg";
  const toneClass =
    side === "buy"
      ? "border-emerald-500/25 bg-emerald-500/8"
      : "border-amber-500/25 bg-amber-500/8";

  const rows: DisplayRow[] = [
    ["Trade date", toText(leg?.trade_date)],
    ["Value", formatCompactUsd(leg?.dollars)],
    ["Shares", formatIntValue(leg?.shares)],
    ["Average price", formatUsdExact(leg?.vwap_price)],
    ["Holding change", formatPercentAuto(leg?.holdings_change_pct)],
    ["Holding multiple", formatDecimal(leg?.holdings_change_multiple)],
    ["Owned before", formatIntValue(leg?.shares_owned_before_estimate)],
    ["Owned after", formatIntValue(leg?.shares_owned_after)],
    ["Filing delay", toNumber(leg?.filing_delay_days) === null ? null : `${fmtInt(Number(leg.filing_delay_days))} day(s)`],
    ["Value vs market cap", formatPercentFraction(leg?.trade_value_pct_market_cap)],
  ];
  const filteredRows = filterRows(rows);

  if (filteredRows.length === 0) return null;

  return (
    <div className={["rounded-2xl border p-4", toneClass].join(" ")}>
      <div className="text-sm font-semibold text-zinc-100">{label}</div>
      <div className="mt-3">
        {filteredRows.map(([labelText, value]) => (
          <DataRow key={labelText} label={labelText} value={value} />
        ))}
      </div>
    </div>
  );
}

function BaselineSignalCard({ side, signal }: { side: "buy" | "sell"; signal: any }) {
  const rating = toNumber(signal?.rating);
  const confidence = toNumber(signal?.confidence);
  const reasons = Array.isArray(signal?.reasons) ? signal.reasons.map((value: unknown) => String(value)) : [];

  if (rating === null && confidence === null && reasons.length === 0) return null;

  return (
    <div className="rounded-2xl border border-zinc-800/60 bg-black/20 p-4">
      <div className="flex items-center justify-between gap-3">
        <div className="text-sm font-semibold text-zinc-100">{side === "buy" ? "Buy baseline" : "Sell baseline"}</div>
        {rating !== null ? <span className="badge">AI {fmtAiRating(rating)}</span> : null}
      </div>

      <div className="mt-3 grid gap-3 sm:grid-cols-2">
        <MiniStat label="Confidence" value={confidence === null ? "—" : formatPercentFraction(confidence) || "—"} />
        <MiniStat label="Rating" value={rating === null ? "—" : fmtAiRating(rating)} />
      </div>

      <BadgeList items={reasons} tone={side === "buy" ? "emerald" : "amber"} />
    </div>
  );
}

function ClusterCard({ side, cluster }: { side: "buy" | "sell"; cluster: any }) {
  if (!hasContent(cluster)) return null;

  const rows: DisplayRow[] = [
    ["Cluster flag", boolText(cluster?.cluster_flag)],
    ["Cluster ID", toText(cluster?.cluster_id)],
    ["Window", toNumber(cluster?.window_days) === null ? null : `${fmtInt(Number(cluster.window_days))} days`],
    ["Unique insiders", formatIntValue(cluster?.unique_insiders)],
    ["Executives involved", boolText(cluster?.execs_involved)],
    ["Total dollars", formatCompactUsd(cluster?.total_dollars)],
    ["Largest holding change", formatPercentAuto(cluster?.max_pct_holdings_change)],
  ];
  const filteredRows = filterRows(rows);

  if (filteredRows.length === 0) return null;

  return (
    <div className="rounded-2xl border border-zinc-800/60 bg-black/20 p-4">
      <div className="text-sm font-semibold text-zinc-100">{side === "buy" ? "Buy cluster" : "Sell cluster"}</div>
      <div className="mt-3">
        {filteredRows.map(([label, value]) => (
          <DataRow key={label} label={label} value={value} />
        ))}
      </div>
    </div>
  );
}

function StatCard({ title, rows }: { title: string; rows: Array<[string, string | null]> }) {
  const filtered = filterRows(rows);
  if (filtered.length === 0) return null;

  return (
    <div className="rounded-2xl border border-zinc-800/60 bg-black/20 p-4">
      <div className="text-sm font-semibold text-zinc-100">{title}</div>
      <div className="mt-3">
        {filtered.map(([label, value]) => (
          <DataRow key={label} label={label} value={value} />
        ))}
      </div>
    </div>
  );
}

export function AdminAiInputsPanel({ input }: AdminAiInputsPanelProps) {
  const snapshotRows: DisplayRow[] = [
    ["As of", toText(input?.asof_utc)],
    ["Schema version", toText(input?.schema_version)],
    ["Benchmark", toText(input?.benchmark?.symbol)],
  ];
  const filteredSnapshotRows = filterRows(snapshotRows);

  const event = input?.event ?? {};
  const issuerContext = input?.issuer_context ?? {};
  const fundamentals = issuerContext?.fundamentals ?? {};
  const filingIndicators = input?.filing_context?.indicators ?? {};
  const newsItems = Array.isArray(issuerContext?.news) ? issuerContext.news : [];

  const baselineCards = [
    <BaselineSignalCard key="buy" side="buy" signal={input?.baseline?.buy} />,
    <BaselineSignalCard key="sell" side="sell" signal={input?.baseline?.sell} />,
  ].filter(Boolean);

  const clusterCards = [
    <ClusterCard key="buy" side="buy" cluster={input?.cluster_context?.buy_cluster} />,
    <ClusterCard key="sell" side="sell" cluster={input?.cluster_context?.sell_cluster} />,
  ].filter(Boolean);

  const filingFlags = Object.entries(filingIndicators)
    .filter(([, value]) => value !== null && value !== undefined)
    .map(([key, value]) => `${key.replace(/_/g, " ")}: ${value ? "yes" : "no"}`);

  const fundamentalsRows: DisplayRow[] = [
    ["Ticker", toText(issuerContext?.ticker)],
    ["Market cap bucket", toText(issuerContext?.market_cap_bucket)],
    ["Market cap", formatCompactUsd(issuerContext?.market_cap ?? fundamentals?.market_cap)],
    ["Sector", toText(fundamentals?.sector)],
    ["Beta", formatDecimal(fundamentals?.beta, 2)],
    ["EPS", formatDecimal(fundamentals?.eps, 2)],
    ["P/E ratio", formatDecimal(fundamentals?.pe_ratio, 2)],
    ["Shares outstanding", formatIntValue(issuerContext?.shares_outstanding ?? fundamentals?.shares_outstanding)],
    ["Shares reported (SEC filed)", toText(issuerContext?.market_cap_as_of)],
    ["Updated", toText(fundamentals?.updated_at ?? issuerContext?.market_cap_updated_at)],
  ];

  const recentActivityRows: DisplayRow[] = [
    ["Window", toNumber(input?.issuer_recent_activity?.window_days) === null ? null : `${fmtInt(Number(input.issuer_recent_activity.window_days))} days`],
    ["Total events", formatIntValue(input?.issuer_recent_activity?.events_total)],
    ["Buy events", formatIntValue(input?.issuer_recent_activity?.buy_events)],
    ["Sell events", formatIntValue(input?.issuer_recent_activity?.sell_events)],
    ["Unique insiders", formatIntValue(input?.issuer_recent_activity?.unique_insiders)],
  ];

  const trendRows: DisplayRow[] = [
    ["Trade date", toText(input?.trend_context?.price_reference?.trade_date)],
    ["Nearest trading date", toText(input?.trend_context?.price_reference?.nearest_trading_date)],
    ["Reference close", formatUsdExact(input?.trend_context?.price_reference?.close, 4)],
    ["20d pre-return", formatPercentAuto(input?.trend_context?.pre_returns?.ret_20d)],
    ["60d pre-return", formatPercentAuto(input?.trend_context?.pre_returns?.ret_60d)],
    ["Above 50-day SMA", boolText(input?.trend_context?.moving_averages?.above_sma_50)],
    ["Above 200-day SMA", boolText(input?.trend_context?.moving_averages?.above_sma_200)],
    ["Distance to 52w high", formatPercentAuto(input?.trend_context?.range_position?.dist_52w_high)],
    ["Distance to 52w low", formatPercentAuto(input?.trend_context?.range_position?.dist_52w_low)],
  ];

  const historyRows: DisplayRow[] = [
    ["History scope", toText(input?.insider_history?.history_scope)],
    ["Last buy filing", toText(input?.insider_history?.last_buy_filing_date)],
    ["Last sell filing", toText(input?.insider_history?.last_sell_filing_date)],
    ["Prior buy events (12m)", formatIntValue(input?.insider_history?.prior_buy_events_12m)],
    ["Prior sell events (12m)", formatIntValue(input?.insider_history?.prior_sell_events_12m)],
    ["Prior buy events (total)", formatIntValue(input?.insider_history?.prior_buy_events_total)],
    ["Prior sell events (total)", formatIntValue(input?.insider_history?.prior_sell_events_total)],
    ["Window years", formatDecimal(input?.insider_history?.window_years, 1)],
  ];

  const buyStatsRows: DisplayRow[] = [
    ["As of", toText(input?.insider_stats?.buy?.as_of_date)],
    ["Eligible 60d sample", formatIntValue(input?.insider_stats?.buy?.eligible_n_60d)],
    ["Eligible 180d sample", formatIntValue(input?.insider_stats?.buy?.eligible_n_180d)],
    ["Avg return 60d", formatPercentAuto(input?.insider_stats?.buy?.avg_return_60d)],
    ["Avg return 180d", formatPercentAuto(input?.insider_stats?.buy?.avg_return_180d)],
    ["Win rate 60d", formatPercentAuto(input?.insider_stats?.buy?.win_rate_60d)],
    ["Win rate 180d", formatPercentAuto(input?.insider_stats?.buy?.win_rate_180d)],
  ];

  const sellStatsRows: DisplayRow[] = [
    ["As of", toText(input?.insider_stats?.sell?.as_of_date)],
    ["Eligible 60d sample", formatIntValue(input?.insider_stats?.sell?.eligible_n_60d)],
    ["Eligible 180d sample", formatIntValue(input?.insider_stats?.sell?.eligible_n_180d)],
    ["Avg return 60d", formatPercentAuto(input?.insider_stats?.sell?.avg_return_60d)],
    ["Avg return 180d", formatPercentAuto(input?.insider_stats?.sell?.avg_return_180d)],
    ["Win rate 60d", formatPercentAuto(input?.insider_stats?.sell?.win_rate_60d)],
    ["Win rate 180d", formatPercentAuto(input?.insider_stats?.sell?.win_rate_180d)],
  ];

  const qualityRows: DisplayRow[] = [
    ["Buy VWAP partial", boolText(input?.data_quality?.buy_vwap_is_partial)],
    ["Sell VWAP partial", boolText(input?.data_quality?.sell_vwap_is_partial)],
    ["Trend missing", boolText(input?.data_quality?.trend_missing)],
    ["Trend missing reason", toText(input?.data_quality?.trend_missing_reason)],
    ["Market cap staleness", toNumber(input?.data_quality?.market_cap_staleness_days) === null ? null : `${fmtInt(Number(input.data_quality.market_cap_staleness_days))} days`],
    ["Buy holding change missing", boolText(input?.data_quality?.pct_holdings_change_missing?.buy)],
    ["Sell holding change missing", boolText(input?.data_quality?.pct_holdings_change_missing?.sell)],
  ];

  const eventSummaryStats = [
    <MiniStat key="ticker" label="Ticker" value={toText(event?.ticker) || "—"} helper={toText(event?.issuer_cik) || undefined} />,
    <MiniStat
      key="insider"
      label="Insider"
      value={toText(event?.owner_name) || "—"}
      helper={toText(event?.owner_title) || undefined}
    />,
    <MiniStat key="filing" label="Filing date" value={fmtDate(toText(event?.filing_date))} helper={toText(event?.accession_number) || undefined} />,
    <MiniStat key="trade" label="Trade date" value={fmtDate(toText(event?.event_trade_date))} helper={toText(event?.owner_key) || undefined} />,
    <MiniStat key="officer" label="Officer" value={boolText(event?.is_officer) || "—"} helper="Reporting owner role" />,
    <MiniStat key="director" label="Director / 10%" value={`${boolText(event?.is_director) || "—"} / ${boolText(event?.is_ten_percent_owner) || "—"}`} />,
  ];

  const eventLegCards = [
    event?.buy?.has_buy ? <TradeLegCard key="buy" side="buy" leg={event.buy} /> : null,
    event?.sell?.has_sell ? <TradeLegCard key="sell" side="sell" leg={event.sell} /> : null,
  ].filter(Boolean);

  return (
    <div className="space-y-4">
      <SectionCard title="Model input snapshot" subtitle="Structured data package sent to the AI system for this event.">
        <div className="grid gap-3 sm:grid-cols-3">
          {filteredSnapshotRows.map(([label, value]) => (
            <MiniStat key={label} label={label} value={value || "—"} />
          ))}
        </div>
      </SectionCard>

      <SectionCard title="Event profile" subtitle="Core filing details and side-specific trade information.">
        <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">{eventSummaryStats}</div>

        {eventLegCards.length > 0 ? <div className="mt-4 grid gap-4 xl:grid-cols-2">{eventLegCards}</div> : null}

        {toText(input?.filing_context?.notes) ? (
          <div className="mt-4 rounded-2xl border border-zinc-800/60 bg-black/20 p-4 text-sm muted">
            {toText(input?.filing_context?.notes)}
          </div>
        ) : null}
      </SectionCard>

      {baselineCards.length > 0 ? (
        <SectionCard title="Baseline scoring" subtitle="First-pass rating inputs before the narrative layer is generated.">
          <div className="grid gap-4 xl:grid-cols-2">{baselineCards}</div>
        </SectionCard>
      ) : null}

      {clusterCards.length > 0 ? (
        <SectionCard title="Cluster context" subtitle="Whether multiple insiders were active around the same time.">
          <div className="grid gap-4 xl:grid-cols-2">{clusterCards}</div>
        </SectionCard>
      ) : null}

      {hasRows(fundamentalsRows) || hasRows(recentActivityRows) ? (
        <SectionCard title="Issuer context" subtitle="Company fundamentals and recent insider activity used by the model.">
          <div className="grid gap-4 xl:grid-cols-2">
            <StatCard title="Fundamentals" rows={fundamentalsRows} />
            <StatCard title="Recent issuer activity" rows={recentActivityRows} />
          </div>
        </SectionCard>
      ) : null}

      {hasRows(trendRows) ? (
        <SectionCard title="Trend context" subtitle="Price, momentum, and range data surrounding the event date.">
          <div className="grid gap-4 xl:grid-cols-2">
            <StatCard title="Technical reference" rows={trendRows.slice(0, 5)} />
            <StatCard title="Trend structure" rows={trendRows.slice(5)} />
          </div>
        </SectionCard>
      ) : null}

      {filingFlags.length > 0 || toText(input?.filing_context?.notes) ? (
        <SectionCard title="Filing indicators" subtitle="Signals extracted from filing footnotes and disclosures.">
          <BadgeList items={filingFlags} tone="purple" />
          {Array.isArray(input?.filing_context?.footnotes) && input.filing_context.footnotes.length > 0 ? (
            <div className="mt-4 rounded-2xl border border-zinc-800/60 bg-black/20 p-4">
              <div className="text-sm font-semibold text-zinc-100">Footnotes</div>
              <ul className="mt-3 list-disc space-y-2 pl-5 text-sm muted">
                {input.filing_context.footnotes.slice(0, 8).map((note: unknown, index: number) => (
                  <li key={index}>{String(note)}</li>
                ))}
              </ul>
            </div>
          ) : null}
        </SectionCard>
      ) : null}

      {hasRows(historyRows) || hasRows(buyStatsRows) || hasRows(sellStatsRows) ? (
        <SectionCard title="Insider history" subtitle="Historical behavior and measured performance for this insider.">
          <div className="grid gap-4 xl:grid-cols-3">
            <StatCard title="History" rows={historyRows} />
            <StatCard title="Buy-side stats" rows={buyStatsRows} />
            <StatCard title="Sell-side stats" rows={sellStatsRows} />
          </div>
          {toText(input?.insider_stats?.notes) ? (
            <div className="mt-4 rounded-2xl border border-zinc-800/60 bg-black/20 p-4 text-sm muted">
              {toText(input?.insider_stats?.notes)}
            </div>
          ) : null}
        </SectionCard>
      ) : null}

      {hasRows(qualityRows) ? (
        <SectionCard title="Data quality" subtitle="Flags that help explain missing or partial values inside the AI input.">
          <div className="grid gap-4 xl:grid-cols-2">
            <StatCard title="Quality checks" rows={qualityRows} />
            {toText(event?.other_activity_summary?.notes) || hasContent(event?.other_activity_summary?.derivative_row_count) || hasContent(event?.other_activity_summary?.non_open_market_row_count) ? (
              <StatCard
                title="Other filing activity"
                rows={[
                  ["Derivative rows", formatIntValue(event?.other_activity_summary?.derivative_row_count)],
                  ["Non-open-market rows", formatIntValue(event?.other_activity_summary?.non_open_market_row_count)],
                  ["Notes", toText(event?.other_activity_summary?.notes)],
                ]}
              />
            ) : null}
          </div>
        </SectionCard>
      ) : null}

      {newsItems.length > 0 ? (
        <SectionCard title="Recent news context" subtitle="Recent issuer headlines included for additional context.">
          <div className="space-y-3">
            {newsItems.slice(0, 6).map((item: any, index: number) => {
              const title = toText(item?.title);
              if (!title) return null;
              const sentiment = formatPercentAuto(item?.sentiment);
              return (
                <div key={`${title}-${index}`} className="rounded-2xl border border-zinc-800/60 bg-black/20 p-4">
                  <div className="flex flex-col gap-2 md:flex-row md:items-start md:justify-between">
                    <div>
                      <div className="text-sm font-semibold text-zinc-100">{title}</div>
                      <div className="mt-1 text-xs muted">
                        {toText(item?.published_at) || "—"}
                        {item?.source ? ` • ${item.source}` : ""}
                        {sentiment ? ` • sentiment ${sentiment}` : ""}
                      </div>
                    </div>
                    {item?.url ? (
                      <a
                        href={String(item.url)}
                        target="_blank"
                        rel="noreferrer"
                        className="link text-sm"
                      >
                        Open source
                      </a>
                    ) : null}
                  </div>
                </div>
              );
            })}
          </div>
        </SectionCard>
      ) : null}
    </div>
  );
}
