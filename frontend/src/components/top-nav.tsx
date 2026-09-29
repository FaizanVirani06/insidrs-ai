import * as React from "react";
import { Link, useLocation } from "react-router-dom";

import { useAuth } from "@/components/auth-provider";
import { DemoButton } from "@/components/demo-button";
import { SiteBrandMark } from "@/components/site-brand-mark";
import { useSiteStatus } from "@/lib/site-status";

function HeaderLink({ to, children }: { to: string; children: React.ReactNode }) {
  const loc = useLocation();
  const active = loc.pathname === to || (to === "/app" && loc.pathname.startsWith("/app"));

  return (
    <Link
      to={to}
      className={
        active
          ? "text-white"
          : "text-zinc-400 transition-colors hover:text-white"
      }
    >
      {children}
    </Link>
  );
}

export function TopNav() {
  const { user, logout } = useAuth();
  const { showcase_mode } = useSiteStatus();
  const loc = useLocation();
  const isApp = loc.pathname.startsWith("/app");

  return (
    <header className="sticky top-0 z-50 border-b border-zinc-800/50 bg-black/40 backdrop-blur-xl">
      <div
        className={
          isApp
            ? "mx-auto flex h-16 max-w-screen-2xl items-center justify-between px-4"
            : "container mx-auto flex h-16 items-center justify-between px-4"
        }
      >
        <Link to="/" className="flex items-center gap-3">
          <SiteBrandMark textClassName="text-lg font-bold tracking-tight" imageClassName="h-8" />
          <span className="badge hidden sm:inline-flex">{showcase_mode ? "Portfolio project" : "Beta"}</span>
        </Link>

        <nav className="hidden items-center gap-6 text-sm md:flex">
          {showcase_mode ? (
            <Link
              to="/recruiters"
              className={
                loc.pathname === "/recruiters"
                  ? "font-medium text-cyan-200"
                  : "font-medium text-cyan-300 transition-colors hover:text-cyan-200"
              }
            >
              For recruiters
            </Link>
          ) : null}
          <HeaderLink to="/pricing">Pricing</HeaderLink>
          <HeaderLink to="/app">App</HeaderLink>
        </nav>

        <div className="flex items-center gap-2">
          {!user && showcase_mode ? (
            <DemoButton className="btn-secondary h-9 px-3 text-xs">Open demo</DemoButton>
          ) : null}
          {user ? (
            <button type="button" onClick={() => void logout()} className="btn-ghost">
              Logout
            </button>
          ) : null}
        </div>
      </div>
    </header>
  );
}
