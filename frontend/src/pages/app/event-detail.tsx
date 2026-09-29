import * as React from "react";
import { Link, useParams } from "react-router-dom";

import { AdminAiInputsPanel } from "@/components/admin-ai-inputs-panel";
import { PriceChart } from "@/components/price-chart";
import { RegenerateAIButton } from "@/components/regenerate-ai-button";
import { useAuth } from "@/components/auth-provider";
import { apiFetch } from "@/lib/api";
import { getBestEventAiRating, getEventDisplaySides, getEventSideSummaries, type EventSide } from "@/lib/event-utils";
import { addDays, fmtAiRating, fmtDate, fmtDollars, fmtNumber, fmtPercent, fmtUsd, minIsoDate } from "@/lib/format";
import type { EventDetail, PricePoint } from "@/lib/types";

function toNumber(value: unknown): number | null {
  if (value === null || value === undefined || value === "") return null;
  const n = Number(value);
  return Number.isFinite(n) ? n : null;
}

function hasText(value: unknown): boolean {
  return typeof value === "string" && value.trim().length > 0;
}

function confidenceText(value: unknown): string | null {
  const n = toNumber(value);
  if (n === null) return null;
  return `${Math.round(n * 100)}%`;
}

function signalHasContent(signal: any): boolean {
  if (!signal || typeof signal !== "object") return false;
  return (
    hasText(signal.status) ||
    hasText(signal.summary) ||
    toNumber(signal.rating) !== null ||
    toNumber(signal.confidence) !== null
  );
}

function narrativeItems(value: unknown): string[] {
  return Array.isArray(value)
    ? value
        .map((item) => String(item ?? "").trim())
        .filter(Boolean)
        .slice(0, 8)
    : [];
}

function tradePlanHasUsefulContent(plan: any): boolean {
  if (!plan) return false;
  if (!plan.eligible) return hasText(plan.reason);
  const trims = Array.isArray(plan.trims) ? plan.trims.filter((item: any) => item && toNumber(item?.price) !== null) : [];
  return Boolean(
    toNumber(plan.entry?.price) !== null ||
      toNumber(plan.stop_loss?.price) !== null ||
      toNumber(plan.take_profit?.price) !== null ||
      trims.length > 0 ||
      (Array.isArray(plan.notes) && plan.notes.some((note: unknown) => String(note ?? "").trim()))
  );
}

export function EventDetailPage() {
  const params = useParams<{ issuer_cik: string; owner_key: string; accession_number: string }>();
  const { user } = useAuth();
  const isAdmin = user?.role === "admin";
  // The read-only showcase account may inspect model metadata and the exact AI input package.
  const canViewAiInternals = isAdmin || user?.role === "showcase";

  const issuerCik = decodeURIComponent(String(params?.issuer_cik ?? ""));
  const ownerKey = decodeURIComponent(String(params?.owner_key ?? ""));
  const accession = decodeURIComponent(String(params?.accession_number ?? ""));

  const [detail, setDetail] = React.useState<EventDetail | null>(null);
  const [prices, setPrices] = React.useState<PricePoint[]>([]);
  const [loading, setLoading] = React.useState(true);
  const [error, setError] = React.useState<string | null>(null);

  React.useEffect(() => {
    let cancelled = false;

    (async () => {
      setLoading(true);
      setError(null);

      try {
        const res = await apiFetch(
          `/event/${encodeURIComponent(issuerCik)}/${encodeURIComponent(ownerKey)}/${encodeURIComponent(accession)}`,
          { cache: "no-store" }
        );
        if (!res.ok) throw new Error(await res.text());

        const data = (await res.json()) as EventDetail;
        if (cancelled) return;
        setDetail(data);

        const event = data.event;
        const anchor = (event.event_trade_date || event.filing_date || "").slice(0, 10);
        const today = new Date().toISOString().slice(0, 10);

        if (event.ticker && anchor) {
          const start = addDays(anchor, -365);
          const end = minIsoDate(addDays(anchor, 365), today);
          const priceRes = await apiFetch(
            `/ticker/${encodeURIComponent(event.ticker)}/prices?start=${encodeURIComponent(start)}&end=${encodeURIComponent(end)}&limit=5000`,
            { cache: "no-store" }
          );
          if (priceRes.ok) {
            const json = await priceRes.json();
            if (!cancelled) setPrices((json?.prices ?? []) as PricePoint[]);
          }
        }
      } catch (e: any) {
        if (!cancelled) setError(e?.message || "Failed to load event.");
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();

    return () => {
      cancelled = true;
    };
  }, [issuerCik, ownerKey, accession]);

  if (loading) {
    return <div className="text-sm muted">Loading…</div>;
  }

  if (error) {
    return (
      <div className="rounded-md border border-red-500/30 bg-red-500/10 px-3 py-2 text-sm text-red-700 dark:text-red-300">
        {error}
      </div>
    );
  }

  if (!detail) {
    return <div className="text-sm muted">No data.</div>;
  }

  const event = detail.event;
  const bestEventAi = getBestEventAiRating(event);
  const sideSummaries = getEventSideSummaries(event);
  const eventSides = getEventDisplaySides(event);
  const visibleSides: EventSide[] = eventSides.length > 0 ? eventSides : (["buy", "sell"] as EventSide[]);
  const aiOutput = detail.ai_latest?.output ?? null;
  const verdict = aiOutput?.verdict ?? null;
  const tradePlan = (detail as any).trade_plan as any | null | undefined;
  const showTradePlan = tradePlanHasUsefulContent(tradePlan);

  const filteredOutcomes = Array.isArray(detail.outcomes)
    ? detail.outcomes.filter((item: any) => {
        const side = String(item?.side || "").toLowerCase();
        const horizon = toNumber(item?.horizon_days);
        const returnValue = toNumber(item?.return);
        return (
          Boolean(side) &&
          visibleSides.includes(side as EventSide) &&
          horizon !== null &&
          returnValue !== null
        );
      })
    : [];

  const signalCards = verdict
    ? visibleSides
        .map((side) => {
          const signal = side === "buy" ? verdict.buy_signal : verdict.sell_signal;
          if (!signalHasContent(signal)) return null;
          return { side, signal };
        })
        .filter(Boolean) as Array<{ side: EventSide; signal: any }>
    : [];

  const narrativeSections = [
    { title: "Thesis", items: narrativeItems(aiOutput?.narrative?.thesis_bullets) },
    { title: "Context", items: narrativeItems(aiOutput?.narrative?.context_bullets) },
    { title: "Counterpoints", items: narrativeItems(aiOutput?.narrative?.counterpoints_bullets) },
  ].filter((section) => section.items.length > 0);

  const showAiExplanation = signalCards.length > 0 || narrativeSections.length > 0;

  const summaryCards: React.ReactNode[] = [];

  if (sideSummaries.length > 0) {
    for (const summary of sideSummaries) {
      summaryCards.push(
        <div
          key={summary.side}
          className={[
            "glass-card p-4",
            summary.side === "buy" ? "border-emerald-500/20 bg-emerald-500/5" : "border-amber-500/20 bg-amber-500/5",
          ].join(" ")}
        >
          <div className="flex items-center justify-between gap-3">
            <div className="text-xs muted">{summary.label} summary</div>
            {summary.clusterFlag ? <span className="badge">Cluster</span> : null}
          </div>

          <div className="mt-3 space-y-2 text-sm">
            {summary.dollars !== null ? (
              <div className="flex justify-between gap-3">
                <span className="muted">Value</span>
                <span className="font-medium">{fmtDollars(summary.dollars)}</span>
              </div>
            ) : null}
            {summary.shares !== null ? (
              <div className="flex justify-between gap-3">
                <span className="muted">Shares</span>
                <span className="font-medium">{fmtNumber(summary.shares, { digits: 0 })}</span>
              </div>
            ) : null}
            {summary.vwap !== null ? (
              <div className="flex justify-between gap-3">
                <span className="muted">Average price</span>
                <span className="font-medium">{fmtUsd(summary.vwap)}</span>
              </div>
            ) : null}
            {summary.pctHoldingsChange !== null ? (
              <div className="flex justify-between gap-3">
                <span className="muted">Holding change</span>
                <span className="font-medium">{summary.pctHoldingsChange.toFixed(1)}%</span>
              </div>
            ) : null}
            {summary.aiRating !== null ? (
              <div className="flex justify-between gap-3">
                <span className="muted">AI score</span>
                <span className="font-medium">{fmtAiRating(summary.aiRating)}</span>
              </div>
            ) : null}
            {summary.tradeDate ? <div className="pt-1 text-xs muted">Trade date {fmtDate(summary.tradeDate)}</div> : null}
          </div>
        </div>
      );
    }
  } else {
    summaryCards.push(
      <div key="overview" className="glass-card p-4">
        <div className="text-xs muted">Event overview</div>
        <div className="mt-2 text-2xl font-semibold">{fmtAiRating(bestEventAi)}</div>
        <div className="mt-1 text-xs muted">
          Best event AI
          {confidenceText(event.ai_confidence) ? ` • confidence ${confidenceText(event.ai_confidence)}` : ""}
        </div>
      </div>
    );
  }

  if (filteredOutcomes.length > 0) {
    summaryCards.push(
      <div key="outcomes" className="glass-card p-4">
        <div className="text-xs muted">Outcomes</div>
        <div className="mt-3 space-y-2 text-sm">
          {filteredOutcomes.map((item: any) => (
            <div key={`${item.side}-${item.horizon_days}`} className="flex justify-between gap-3">
              <div className="muted">
                {String(item.side).toUpperCase()} +{Math.round(Number(item.horizon_days))}d
              </div>
              <div className="font-medium">{fmtPercent(Number(item.return), { digits: 1 })}</div>
            </div>
          ))}
        </div>
      </div>
    );
  }

  const tradePlanCards: React.ReactNode[] = [];
  const trimTargets = Array.isArray(tradePlan?.trims)
    ? tradePlan.trims.filter((target: any) => target && toNumber(target?.price) !== null).slice(0, 4)
    : [];

  if (toNumber(tradePlan?.entry?.price) !== null) {
    tradePlanCards.push(
      <div key="entry" className="glass-card p-3">
        <div className="text-xs muted">Entry</div>
        <div className="mt-1 text-sm">
          <span className="font-medium">{fmtDollars(tradePlan.entry.price)}</span>
          {tradePlan.entry?.date ? <span className="muted"> • {fmtDate(tradePlan.entry.date)}</span> : null}
        </div>
        {tradePlan.entry?.source ? <div className="mt-1 text-xs muted">Source: {tradePlan.entry.source}</div> : null}
      </div>
    );
  }

  if (toNumber(tradePlan?.stop_loss?.price) !== null) {
    tradePlanCards.push(
      <div key="stop" className="glass-card p-3">
        <div className="text-xs muted">Stop loss</div>
        <div className="mt-1 text-sm">
          <span className="font-medium">{fmtDollars(tradePlan.stop_loss.price)}</span>
          {toNumber(tradePlan?.risk?.pct) !== null ? (
            <span className="muted"> • risk {tradePlan.risk.pct}%</span>
          ) : null}
        </div>
        {tradePlan.stop_loss?.basis ? <div className="mt-1 text-xs muted">Basis: {tradePlan.stop_loss.basis}</div> : null}
      </div>
    );
  }

  if (trimTargets.length > 0) {
    tradePlanCards.push(
      <div key="trims" className="glass-card p-3">
        <div className="text-xs muted">Trim targets</div>
        <div className="mt-2 space-y-1 text-sm">
          {trimTargets.map((target: any, index: number) => (
            <div key={index} className="flex items-center justify-between gap-3">
              <div className="font-medium">{fmtDollars(target.price)}</div>
              <div className="text-xs muted">{target.basis || "—"}</div>
            </div>
          ))}
        </div>
      </div>
    );
  }

  if (toNumber(tradePlan?.take_profit?.price) !== null) {
    tradePlanCards.push(
      <div key="take-profit" className="glass-card p-3">
        <div className="text-xs muted">Take profit</div>
        <div className="mt-1 text-sm">
          <span className="font-medium">{fmtDollars(tradePlan.take_profit.price)}</span>
        </div>
        {tradePlan.take_profit?.basis ? (
          <div className="mt-1 text-xs muted">Basis: {tradePlan.take_profit.basis}</div>
        ) : null}
      </div>
    );
  }

  const tradePlanNotes = Array.isArray(tradePlan?.notes)
    ? tradePlan.notes.map((note: unknown) => String(note ?? "").trim()).filter(Boolean).slice(0, 8)
    : [];

  return (
    <div className="space-y-4">
      <div className="flex items-start justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold">Event</h1>
          <div className="mt-1 text-sm muted">
            {event.ticker ? `${event.ticker} • ` : ""}
            {event.owner_name_display || ownerKey}
            <span className="mx-2">•</span>
            Filing {fmtDate(event.filing_date)}
            {event.event_trade_date ? (
              <>
                <span className="mx-2">•</span>
                Trade {fmtDate(event.event_trade_date)}
              </>
            ) : null}
          </div>
        </div>

        <Link to={`/app/ticker/${encodeURIComponent(event.ticker || "")}`} className="btn-secondary">
          Back to ticker
        </Link>
      </div>

      <div className="glass-card p-4">
        <div className="flex items-center justify-between">
          <div className="text-sm font-semibold">Price chart</div>
          <div className="text-xs muted">Adj close</div>
        </div>
        <div className="mt-3">
          <PriceChart data={prices} tradeDate={event.event_trade_date} filingDate={event.filing_date} />
        </div>
      </div>

      <div
        data-tour="event-summary"
        className={[
          "grid grid-cols-1 gap-3",
          summaryCards.length >= 3 ? "xl:grid-cols-3" : summaryCards.length === 2 ? "md:grid-cols-2" : "grid-cols-1",
        ].join(" ")}
      >
        {summaryCards}
      </div>

      {showTradePlan ? (
        <div className="glass-card p-4">
          <div className="flex items-start justify-between gap-3">
            <div>
              <div className="text-sm font-semibold">Trade plan</div>
              <div className="text-xs muted">
                {tradePlan?.eligible
                  ? "Technicals-based levels: stop, trims, and take-profit."
                  : "Automatic trade plan status."}
              </div>
            </div>
            <span className="badge">{tradePlan?.eligible ? "Technicals" : "Not generated"}</span>
          </div>

          {tradePlan?.eligible ? (
            <div className="mt-4 grid gap-3 md:grid-cols-2">{tradePlanCards}</div>
          ) : (
            <div className="mt-4 rounded-md border border-amber-500/30 bg-amber-500/10 px-3 py-2 text-sm text-amber-300">
              {String(tradePlan?.reason || "Trade plan was not generated.")}
            </div>
          )}

          {tradePlan?.eligible && tradePlanNotes.length > 0 ? (
            <div className="mt-3 glass-card p-3">
              <div className="text-xs font-semibold muted">Notes</div>
              <ul className="mt-2 list-disc space-y-1 pl-5 text-sm muted">
                {tradePlanNotes.map((note: string) => (
                  <li key={note}>{note}</li>
                ))}
              </ul>
            </div>
          ) : null}
        </div>
      ) : null}

      {showAiExplanation ? (
        <div data-tour="ai-explanation" className="glass-card p-4">
          <div className="flex items-start justify-between gap-3">
            <div>
              <div className="text-sm font-semibold">AI explanation</div>
              <div className="text-xs muted">
                {canViewAiInternals && detail.ai_latest?.model_id
                  ? `${detail.ai_latest.model_id}${detail.ai_latest.prompt_version ? ` • ${detail.ai_latest.prompt_version}` : ""}`
                  : "Event-level AI summary"}
              </div>
            </div>

            <RegenerateAIButton issuer_cik={issuerCik} owner_key={ownerKey} accession_number={accession} />
          </div>

          <div className="mt-3 grid grid-cols-1 gap-3 md:grid-cols-2">
            {signalCards.map(({ side, signal }) => (
              <div key={side} className="glass-card p-3">
                <div className="text-sm font-semibold">{side === "buy" ? "Buy signal" : "Sell signal"}</div>

                {hasText(signal?.status) ? (
                  <div className="mt-2 text-sm">
                    Status: <span className="font-medium">{String(signal.status)}</span>
                  </div>
                ) : null}

                {toNumber(signal?.rating) !== null || toNumber(signal?.confidence) !== null ? (
                  <div className="mt-1 text-sm">
                    {toNumber(signal?.rating) !== null ? (
                      <>
                        Score: <span className="font-medium">{fmtAiRating(signal.rating)}</span>
                      </>
                    ) : null}
                    {confidenceText(signal?.confidence) ? (
                      <span className="muted">
                        {toNumber(signal?.rating) !== null ? " • " : ""}
                        confidence {confidenceText(signal.confidence)}
                      </span>
                    ) : null}
                  </div>
                ) : null}

                {hasText(signal?.summary) ? <div className="mt-2 text-sm">{String(signal.summary)}</div> : null}
              </div>
            ))}

            {narrativeSections.length > 0 ? (
              <div className="glass-card p-3 md:col-span-2">
                <div className="text-sm font-semibold">Narrative</div>
                <div
                  className={[
                    "mt-3 grid gap-4",
                    narrativeSections.length === 1 ? "grid-cols-1" : narrativeSections.length === 2 ? "md:grid-cols-2" : "md:grid-cols-3",
                  ].join(" ")}
                >
                  {narrativeSections.map((section) => (
                    <div key={section.title}>
                      <div className="text-xs font-semibold muted">{section.title}</div>
                      <ul className="mt-1 list-disc space-y-1 pl-5 text-sm muted">
                        {section.items.map((item) => (
                          <li key={item}>{item}</li>
                        ))}
                      </ul>
                    </div>
                  ))}
                </div>
              </div>
            ) : null}
          </div>
        </div>
      ) : null}

      {canViewAiInternals && detail.ai_latest?.input ? (
        <div className="glass-card p-4">
          <div className="mb-4">
            <div className="text-sm font-semibold">AI inputs</div>
            <div className="text-xs muted">Structured view of the exact data package the model received for this run (admin and demo only).</div>
          </div>
          <AdminAiInputsPanel input={detail.ai_latest.input} />
        </div>
      ) : null}

      {Array.isArray(detail.rows) && detail.rows.length > 0 ? (
        <div className="glass-card p-4">
          <div className="text-sm font-semibold">Raw Form 4 rows ({detail.rows.length})</div>
          <div className="mt-3 overflow-x-auto">
            <table className="min-w-full border-collapse text-xs">
              <thead>
                <tr className="text-left text-black/50 dark:text-white/50">
                  <th className="border-b p-2">Date</th>
                  <th className="border-b p-2">Code</th>
                  <th className="border-b p-2">Derivative</th>
                  <th className="border-b p-2">Shares</th>
                  <th className="border-b p-2">Price</th>
                  <th className="border-b p-2">Shares owned after</th>
                  <th className="border-b p-2">Warnings</th>
                </tr>
              </thead>
              <tbody>
                {detail.rows.map((row: any, index: number) => {
                  const warnings = (() => {
                    try {
                      const parsed =
                        typeof row.parser_warnings_json === "string"
                          ? JSON.parse(row.parser_warnings_json)
                          : row.parser_warnings_json;
                      return Array.isArray(parsed) ? parsed.join("; ") : "";
                    } catch {
                      return String(row.parser_warnings_json ?? "");
                    }
                  })();

                  return (
                    <tr key={index} className="border-b last:border-b-0">
                      <td className="p-2 whitespace-nowrap">{row.transaction_date ?? "—"}</td>
                      <td className="p-2 whitespace-nowrap">{row.transaction_code ?? "—"}</td>
                      <td className="p-2 whitespace-nowrap">{row.is_derivative ? "Yes" : "No"}</td>
                      <td className="p-2 whitespace-nowrap">
                        {typeof row.shares_abs === "number" ? fmtNumber(row.shares_abs) : "—"}
                      </td>
                      <td className="p-2 whitespace-nowrap">
                        {typeof row.price === "number" ? fmtDollars(row.price) : "—"}
                      </td>
                      <td className="p-2 whitespace-nowrap">
                        {typeof row.shares_owned_following === "number" ? fmtNumber(row.shares_owned_following) : "—"}
                      </td>
                      <td className="p-2">{warnings || "—"}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>
      ) : null}

      <div className="glass-card p-4 text-xs muted">
        <div>
          <span className="font-medium">issuer_cik</span>: {issuerCik}
        </div>
        <div>
          <span className="font-medium">owner_key</span>: {ownerKey}
        </div>
        <div>
          <span className="font-medium">accession</span>: {accession}
        </div>
      </div>
    </div>
  );
}
