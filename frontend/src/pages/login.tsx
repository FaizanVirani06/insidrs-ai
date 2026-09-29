import * as React from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";

import { apiFetch } from "@/lib/api";
import { useAuth } from "@/components/auth-provider";
import { DemoButton } from "@/components/demo-button";
import { useSiteStatus } from "@/lib/site-status";

export function LoginPage() {
  const navigate = useNavigate();
  const [sp] = useSearchParams();
  const { setUser } = useAuth();
  const { showcase_mode: showcase } = useSiteStatus();

  const [username, setUsername] = React.useState("");
  const [password, setPassword] = React.useState("");
  const [error, setError] = React.useState<string | null>(null);
  const [loading, setLoading] = React.useState(false);

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    setLoading(true);
    setError(null);

    try {
      const res = await apiFetch("/auth/login", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ username, password }),
      });

      if (!res.ok) {
        const msg = await res.text().catch(() => "Login failed");
        setError(msg || "Login failed");
        return;
      }

      const data = await res.json().catch(() => ({} as any));
      const user = (data?.user ?? null) as any;
      setUser(user);

      const isPaid = showcase || Boolean(user?.is_paid) || user?.role === "admin" || user?.role === "showcase";
      const next = sp.get("next");

      if (next) {
        navigate(next, { replace: true });
      } else if (isPaid) {
        navigate("/app/tickers", { replace: true });
      } else {
        navigate("/pricing", { replace: true });
      }
    } catch {
      setError("Login failed");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="mx-auto mt-16 max-w-md">
      <div className="glass-card p-6">
        <h1 className="text-xl font-semibold">Sign in</h1>
        <p className="mt-1 text-sm muted">
          Use your platform credentials. If you don't have an account yet, sign up.
        </p>

        <form onSubmit={onSubmit} className="mt-6 space-y-4">
          <div>
            <label className="block text-sm font-medium">Email</label>
            <input
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              className="input mt-1"
              autoComplete="username"
              placeholder="you@example.com"
            />
          </div>

          <div>
            <label className="block text-sm font-medium">Password</label>
            <input
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              className="input mt-1"
              autoComplete="current-password"
            />
          </div>

          {error && (
            <div className="rounded-md border border-red-500/30 bg-red-500/10 px-3 py-2 text-sm text-red-700 dark:text-red-300">
              {error}
            </div>
          )}

          <button type="submit" disabled={loading} className="btn-primary w-full">
            {loading ? "Signing in…" : "Sign in"}
          </button>

          <div className="flex items-center justify-between text-xs muted">
            <span>
              New here?{" "}
              <Link className="link" to="/signup">
                Create an account
              </Link>
            </span>
          </div>
        </form>
      </div>

      {showcase ? (
        <div className="mt-4 glass-card p-5 text-sm">
          <div className="font-medium text-zinc-100">Just looking around?</div>
          <p className="mt-1 muted">Use the read-only demo account. No password needed.</p>
          <div className="mt-3 flex flex-wrap gap-2">
            <DemoButton className="btn-secondary h-9 px-4">Use the demo account</DemoButton>
            <Link to="/recruiters" className="btn-ghost h-9 px-3">
              Recruiter tour
            </Link>
          </div>
        </div>
      ) : null}
    </div>
  );
}
