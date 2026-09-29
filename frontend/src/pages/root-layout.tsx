import * as React from "react";
import { Link, Outlet, useLocation } from "react-router-dom";

import { AnimatedBackground } from "@/components/animated-background";
import { DocumentMetaManager } from "@/components/document-meta-manager";
import { useAuth } from "@/components/auth-provider";
import { ShowcaseBanner } from "@/components/showcase-banner";
import { SiteBrandMark } from "@/components/site-brand-mark";
import { TopNav } from "@/components/top-nav";
import { SupportChatWidget } from "@/components/support-chat";
import { TourPanel } from "@/components/tour/tour-panel";
import { useTour } from "@/components/tour/tour-provider";
import { OWNER } from "@/lib/showcase";
import { useSiteStatus } from "@/lib/site-status";

export function RootLayout() {
  const location = useLocation();
  const { user } = useAuth();
  const tour = useTour();
  const { showcase_mode } = useSiteStatus();
  const isApp = location.pathname.startsWith("/app");
  const isShowcase = user?.role === "showcase";

  return (
    <div className="relative min-h-screen bg-background text-foreground">
      <AnimatedBackground />
      <DocumentMetaManager />
      <TopNav />
      <ShowcaseBanner />

      <main
        className={[
          isApp ? "mx-auto w-full max-w-screen-2xl px-4 py-8" : "container mx-auto px-4 py-10",
          // On wide screens, keep page content out from under the docked tour panel.
          tour.active && !tour.minimized ? "xl:pr-[436px]" : "",
        ].join(" ")}
      >
        <Outlet />
      </main>

      {isShowcase && !tour.active ? (
        <div className="pointer-events-none fixed bottom-4 left-4 z-[60] hidden max-w-sm rounded-2xl border border-cyan-500/30 bg-black/80 px-4 py-3 text-sm text-cyan-100 shadow-2xl shadow-cyan-500/10 backdrop-blur-xl sm:block">
          <div className="font-semibold uppercase tracking-[0.18em] text-[11px] text-cyan-300">Read-only demo</div>
          <div className="mt-1 text-xs leading-relaxed text-cyan-50/90">
            You are signed in with the showcase account. Changes are disabled and customer details are masked.
          </div>
        </div>
      ) : null}

      {!showcase_mode ? <SupportChatWidget /> : null}
      <TourPanel />

      <footer className="border-t border-zinc-800/70 bg-black/30 backdrop-blur-xl">
        <div className="container mx-auto flex flex-col gap-3 px-4 py-6 text-sm sm:flex-row sm:items-center sm:justify-between">
          <div className="flex items-center gap-3">
            <SiteBrandMark textClassName="text-base" imageClassName="h-7" />
            <span className="muted">© {new Date().getFullYear()}</span>
          </div>

          <div className="flex flex-wrap items-center gap-4">
            {showcase_mode ? (
              <>
                <span className="muted">
                  Built by{" "}
                  <a href={OWNER.linkedin} target="_blank" rel="noreferrer" className="link">
                    {OWNER.name}
                  </a>
                </span>
                <Link to="/recruiters" className="link">
                  For recruiters
                </Link>
                <a href={OWNER.repo} target="_blank" rel="noreferrer" className="link">
                  Source
                </a>
              </>
            ) : null}
            <Link to="/legal" className="link">
              Privacy &amp; Terms
            </Link>
          </div>
        </div>
      </footer>
    </div>
  );
}
