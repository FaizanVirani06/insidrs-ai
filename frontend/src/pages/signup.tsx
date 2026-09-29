import * as React from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";

import { apiFetch } from "@/lib/api";
import { useAuth } from "@/components/auth-provider";
import { DemoButton } from "@/components/demo-button";
import { useSiteStatus } from "@/lib/site-status";

export function SignupPage() {
  const navigate = useNavigate();
  const [sp] = useSearchParams();
  const { setUser } = useAuth();
  const { showcase_mode: showcase } = useSiteStatus();

  const [email, setEmail] = React.useState("");
  const [password, setPassword] = React.useState("");
  const [confirm, setConfirm] = React.useState("");
  const [error, setError] = React.useState<string | null>(null);
  const [loading, setLoading] = React.useState(false);

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);

    const u = (email || "").trim();
    if (u.length < 3) {
      setError("Please enter a valid email.");
      return;
    }
    if (password.length < 8) {
      setError("Password must be at least 8 characters.");
      return;
    }
    if (password !== confirm) {
      setError("Passwords do not match.");
      return;
    }

    setLoading(true);
    try {
      const res = await apiFetch("/auth/register", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ username: u, password }),
      });

      if (!res.ok) {
        const msg = await res.text().catch(() => "Sign up failed");
        setError(msg || "Sign up failed");
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
      setError("Sign up failed");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="mx-auto mt-16 max-w-md">
      {showcase ? (
        <div className="mb-4 rounded-2xl border border-cyan-500/30 bg-cyan-500/10 p-5 text-sm">
          <div className="font-semibold text-zinc-50">No sign-up needed</div>
          <p className="mt-1 text-zinc-300">
            InsidrsAI is a portfolio project now. The read-only demo account opens the whole app.
          </p>
          <div className="mt-3 flex flex-wrap gap-2">
            <DemoButton className="btn-primary h-9 px-4">Use the demo account</DemoButton>
            <Link to="/recruiters" className="btn-ghost h-9 px-3">
              Recruiter tour
            </Link>
          </div>
        </div>
      ) : null}
      <div className="glass-card p-6">
        <h1 className="text-xl font-semibold">Create your account</h1>
        <p className="mt-1 text-sm muted">
          {showcase ? "You can still create a personal account if you want to save preferences." : "Sign up, then subscribe to unlock the insiders dashboard."}
        </p>

        <form onSubmit={onSubmit} className="mt-6 space-y-4">
          <div>
            <label className="block text-sm font-medium">Email</label>
            <input
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              className="input mt-1"
              autoComplete="email"
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
              autoComplete="new-password"
            />
            <div className="mt-1 text-xs muted">Minimum 8 characters.</div>
          </div>

          <div>
            <label className="block text-sm font-medium">Confirm password</label>
            <input
              type="password"
              value={confirm}
              onChange={(e) => setConfirm(e.target.value)}
              className="input mt-1"
              autoComplete="new-password"
            />
          </div>

          {error && (
            <div className="rounded-md border border-red-500/30 bg-red-500/10 px-3 py-2 text-sm text-red-700 dark:text-red-300">
              {error}
            </div>
          )}

          <button type="submit" disabled={loading} className="btn-primary w-full">
            {loading ? "Creating account…" : "Create account"}
          </button>

          <div className="text-xs muted">
            Already have an account?{" "}
            <Link className="link" to="/login">
              Sign in
            </Link>
          </div>
        </form>
      </div>
    </div>
  );
}
