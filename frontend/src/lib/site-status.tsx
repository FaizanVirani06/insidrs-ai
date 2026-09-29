import * as React from "react";

import { apiFetch } from "@/lib/api";

export type SiteStats = {
  filings: number;
  first_filing_date: string | null;
  last_filing_date: string | null;
  insider_events: number;
  issuers: number;
  ai_ratings: number;
};

export type SiteStatus = {
  showcase_mode: boolean;
  demo_login_available: boolean;
  market_data_as_of: string | null;
  stats: SiteStats | null;
  loaded: boolean;
};

// Showcase mode is the backend default, so assume it until /public/site-status answers.
// That avoids flashing paid-product copy (pricing CTAs, paywalls) on first paint.
const DEFAULT_STATUS: SiteStatus = {
  showcase_mode: true,
  demo_login_available: true,
  market_data_as_of: null,
  stats: null,
  loaded: false,
};

const SiteStatusContext = React.createContext<SiteStatus>(DEFAULT_STATUS);

export function SiteStatusProvider({ children }: { children: React.ReactNode }) {
  const [status, setStatus] = React.useState<SiteStatus>(DEFAULT_STATUS);

  React.useEffect(() => {
    let cancelled = false;
    apiFetch("/public/site-status")
      .then((r) => (r.ok ? r.json() : null))
      .then((data) => {
        if (cancelled) return;
        setStatus({
          showcase_mode: data ? Boolean(data.showcase_mode) : DEFAULT_STATUS.showcase_mode,
          demo_login_available: data ? Boolean(data.demo_login_available) : DEFAULT_STATUS.demo_login_available,
          market_data_as_of: typeof data?.market_data_as_of === "string" ? data.market_data_as_of : null,
          stats: data?.stats ?? null,
          loaded: true,
        });
      })
      .catch(() => {
        if (!cancelled) setStatus((prev) => ({ ...prev, loaded: true }));
      });
    return () => {
      cancelled = true;
    };
  }, []);

  return <SiteStatusContext.Provider value={status}>{children}</SiteStatusContext.Provider>;
}

export function useSiteStatus(): SiteStatus {
  return React.useContext(SiteStatusContext);
}

/** "2026-06-12" -> "Jun 12, 2026" (falls back to the raw string). */
export function fmtLongDate(iso: string | null | undefined): string {
  if (!iso) return "—";
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(iso);
  if (!m) return iso;
  const d = new Date(Date.UTC(Number(m[1]), Number(m[2]) - 1, Number(m[3])));
  return d.toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric", timeZone: "UTC" });
}
