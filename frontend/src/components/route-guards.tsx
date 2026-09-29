import * as React from "react";
import { Navigate, Outlet, useLocation } from "react-router-dom";

import { useAuth } from "@/components/auth-provider";
import { SubscriptionRequired } from "@/components/subscription-required";
import { useSiteStatus } from "@/lib/site-status";

function LoadingScreen() {
  return (
    <div className="py-16 text-center text-sm muted">Loading…</div>
  );
}

export function RequireAuth({ children }: { children?: React.ReactNode }) {
  const { user, loading } = useAuth();
  const location = useLocation();

  if (loading) return <LoadingScreen />;
  if (!user) {
    const next = encodeURIComponent(location.pathname + location.search);
    return <Navigate to={`/login?next=${next}`} replace />;
  }

  return <>{children ?? <Outlet />}</>;
}

export function RequireAdminViewer({ children }: { children?: React.ReactNode }) {
  const { user, loading } = useAuth();

  if (loading) return <LoadingScreen />;
  if (!user) return <Navigate to="/login" replace />;
  if (!(user.can_view_admin || user.role === "admin" || user.role === "showcase")) {
    return (
      <div className="mx-auto max-w-3xl py-20">
        <div className="glass-card p-8">
          <div className="text-xl font-semibold">Admin view only</div>
          <div className="mt-2 text-sm muted">You do not have permission to view this page.</div>
        </div>
      </div>
    );
  }

  return <>{children ?? <Outlet />}</>;
}

export function RequireSubscription({ children }: { children?: React.ReactNode }) {
  const { user, loading } = useAuth();
  const { showcase_mode } = useSiteStatus();

  if (loading) return <LoadingScreen />;
  if (!user) return <Navigate to="/login" replace />;

  // Admins and showcase viewers are always allowed.
  if (user.role === "admin" || user.role === "showcase") return <>{children ?? <Outlet />}</>;

  // Paid users allowed; showcase mode turns the paywall off for everyone.
  if ((user as any)?.is_paid || showcase_mode) return <>{children ?? <Outlet />}</>;

  return <SubscriptionRequired />;
}
