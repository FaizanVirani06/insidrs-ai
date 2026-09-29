import * as React from "react";
import { useNavigate } from "react-router-dom";

import type { User } from "@/lib/types";
import { apiFetch } from "@/lib/api";

type AuthContextValue = {
  user: User | null;
  loading: boolean;
  refresh: () => Promise<void>;
  logout: () => Promise<void>;
  /** Sign in as the read-only showcase account (showcase mode only). Returns the user. */
  loginAsDemo: () => Promise<User>;
  setUser: (u: User | null) => void;
};

const AuthContext = React.createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const navigate = useNavigate();

  const [user, _setUser] = React.useState<User | null>(null);
  const [loading, setLoading] = React.useState<boolean>(true);

  // Prevent duplicate concurrent /me calls (common source of flapping)
  const inFlightRef = React.useRef<Promise<void> | null>(null);

  // Avoid setState after unmount
  const mountedRef = React.useRef(true);
  React.useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
    };
  }, []);

  const setUser = React.useCallback((u: User | null) => {
    if (!mountedRef.current) return;
    _setUser(u);
  }, []);

  const refresh = React.useCallback(async () => {
    // Dedupe: if a refresh is already running, await it instead of starting another.
    if (inFlightRef.current) {
      return inFlightRef.current;
    }

    const p = (async () => {
      if (mountedRef.current) setLoading(true);

      try {
        const res = await apiFetch("/auth/me", {
          headers: { "cache-control": "no-cache" },
        });

        if (!mountedRef.current) return;

        if (!res.ok) {
          // Not authenticated (401) or backend down.
          setUser(null);
          return;
        }

        const data = await res.json().catch(() => null);
        setUser((data?.user ?? null) as User | null);
      } catch {
        if (!mountedRef.current) return;
        setUser(null);
      } finally {
        if (!mountedRef.current) return;
        setLoading(false);
      }
    })();

    inFlightRef.current = p;
    try {
      await p;
    } finally {
      inFlightRef.current = null;
    }
  }, [setUser]);

  const logout = React.useCallback(async () => {
    try {
      await apiFetch("/auth/logout", {
        method: "POST",
        headers: { "cache-control": "no-cache" },
      });
    } catch {
      // ignore
    } finally {
      // Ensure local state clears even if network fails
      if (mountedRef.current) {
        setUser(null);
        setLoading(false);
      }
      navigate("/login", { replace: true });
    }
  }, [navigate, setUser]);

  const loginAsDemo = React.useCallback(async () => {
    const res = await apiFetch("/auth/demo-login", {
      method: "POST",
      headers: { "cache-control": "no-cache" },
    });
    if (!res.ok) {
      throw new Error(res.status === 404 ? "The demo account is not enabled." : "Could not start the demo. Please try again.");
    }
    const data = await res.json();
    const u = data?.user as User;
    setUser(u);
    return u;
  }, [setUser]);

  // Initial load: check once
  React.useEffect(() => {
    refresh();
  }, [refresh]);

  // OPTIONAL: background refresh, off by default.
  React.useEffect(() => {
    const msRaw = (import.meta as any)?.env?.VITE_AUTH_REFRESH_MS;
    const ms = msRaw ? Number(msRaw) : 0;
    if (!ms || !Number.isFinite(ms) || ms < 60_000) return; // minimum 1 minute

    const id = window.setInterval(() => {
      if (document.visibilityState === "visible") {
        refresh();
      }
    }, ms);

    return () => window.clearInterval(id);
  }, [refresh]);

  const value = React.useMemo<AuthContextValue>(
    () => ({ user, loading, refresh, logout, loginAsDemo, setUser }),
    [user, loading, refresh, logout, loginAsDemo, setUser]
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
  const ctx = React.useContext(AuthContext);
  if (!ctx) {
    throw new Error("useAuth must be used within <AuthProvider>");
  }
  return ctx;
}
