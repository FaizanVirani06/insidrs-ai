import * as React from "react";
import { matchPath, useLocation } from "react-router-dom";

import { buildSiteDocumentTitle, resolveSiteFaviconSrc, useSiteBranding } from "@/lib/site-branding";

type RouteTitleResolver = string | ((params: Record<string, string | undefined>) => string);

type RouteTitleRule = {
  path: string;
  title: RouteTitleResolver;
};

const ROUTE_TITLE_RULES: RouteTitleRule[] = [
  { path: "/", title: "Home" },
  { path: "/pricing", title: "Pricing" },
  { path: "/recruiters", title: "For recruiters" },
  { path: "/legal", title: "Privacy & Terms" },
  { path: "/login", title: "Log in" },
  { path: "/signup", title: "Create account" },
  { path: "/app", title: "App" },
  { path: "/app/for-you", title: "For you" },
  { path: "/app/recommendations", title: "For you" },
  { path: "/app/profile", title: "Profile" },
  { path: "/app/account", title: "Account" },
  { path: "/app/tickers", title: "Tickers" },
  {
    path: "/app/ticker/:ticker",
    title: (params) => `${String(params.ticker || "Ticker").toUpperCase()} ticker`,
  },
  { path: "/app/events", title: "Events" },
  { path: "/app/event/:issuer_cik/:owner_key/:accession_number", title: "Event details" },
  { path: "/app/feedback", title: "Feedback" },
  { path: "/app/admin/users", title: "Admin users" },
  { path: "/app/admin/monitoring", title: "Admin monitoring" },
  { path: "/app/admin/jobs", title: "Admin jobs" },
  { path: "/app/admin/feedback", title: "Admin feedback" },
  { path: "/app/admin/support", title: "Admin support" },
  { path: "/app/admin/settings", title: "Site settings" },
];

function humanizeSegment(segment: string): string {
  const cleaned = String(segment || "")
    .replace(/[-_]+/g, " ")
    .replace(/\s+/g, " ")
    .trim();
  if (!cleaned) return "InsidrsAI";
  return cleaned.charAt(0).toUpperCase() + cleaned.slice(1);
}

function getPageLabel(pathname: string): string {
  for (const rule of ROUTE_TITLE_RULES) {
    const match = matchPath({ path: rule.path, end: true }, pathname);
    if (!match) continue;
    return typeof rule.title === "function" ? rule.title(match.params) : rule.title;
  }

  if (pathname === "/404") return "Page not found";

  const segments = pathname.split("/").filter(Boolean);
  if (segments.length === 0) return "Home";

  const last = segments[segments.length - 1] || "";
  return humanizeSegment(last);
}

function upsertHeadLink(id: string, rel: string, href: string) {
  if (typeof document === "undefined") return;
  let link = document.getElementById(id) as HTMLLinkElement | null;
  if (!link) {
    link = document.createElement("link");
    link.id = id;
    link.rel = rel;
    document.head.appendChild(link);
  }
  link.rel = rel;
  link.href = href;
}

export function DocumentMetaManager() {
  const location = useLocation();
  const branding = useSiteBranding();

  React.useEffect(() => {
    const pageLabel = getPageLabel(location.pathname);
    document.title = buildSiteDocumentTitle(pageLabel, branding);

    const faviconSrc = resolveSiteFaviconSrc(branding);
    upsertHeadLink("site-favicon", "icon", faviconSrc);
    upsertHeadLink("site-shortcut-icon", "shortcut icon", faviconSrc);
    upsertHeadLink("site-apple-touch-icon", "apple-touch-icon", faviconSrc);
  }, [branding, location.pathname]);

  return null;
}
