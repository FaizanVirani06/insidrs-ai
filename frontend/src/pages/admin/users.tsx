import * as React from "react";

import { useAuth } from "@/components/auth-provider";
import { apiFetch } from "@/lib/api";


type AdminUserRow = {
  user_id: number;
  username: string;
  role: "admin" | "showcase" | "user";
  is_active: number;
  created_at: string;
  updated_at: string;
  last_login_at: string | null;
  subscription_status: string | null;
  current_period_end: string | null;
  cancel_at_period_end: number;
  stripe_customer_id: string | null;
  stripe_subscription_id: string | null;
  stripe_price_id: string | null;
  full_name?: string | null;
  contact_email?: string | null;
  contact_phone?: string | null;
};

type AdminUsersResponse = {
  users: AdminUserRow[];
  total: number;
  limit: number;
  offset: number;
  next_offset: number | null;
  query: string;
  include_inactive: boolean;
};

function fmtDateTime(value: string | null | undefined): string {
  if (!value) return "—";
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return value;
  return d.toLocaleString();
}

function statusLabel(status: string | null | undefined): string {
  const normalized = (status || "").trim().toLowerCase();
  if (!normalized) return "—";
  return normalized;
}

function SummaryCard({ label, value, helper }: { label: string; value: string; helper?: string }) {
  return (
    <div className="rounded-2xl border border-zinc-200/70 bg-white/50 p-4 dark:border-zinc-800/60 dark:bg-black/20">
      <div className="text-xs font-semibold uppercase tracking-[0.16em] muted">{label}</div>
      <div className="mt-2 text-lg font-semibold text-zinc-900 dark:text-zinc-100">{value}</div>
      {helper ? <div className="mt-1 text-sm muted">{helper}</div> : null}
    </div>
  );
}

async function getErrorMessage(res: Response): Promise<string> {
  try {
    const data = await res.json();
    const detail = typeof data?.detail === "string" ? data.detail : JSON.stringify(data);
    switch (detail) {
      case "cannot_remove_current_user":
        return "You cannot remove your own access from this page.";
      case "cannot_remove_last_admin":
        return "At least one active admin must remain.";
      case "user_not_found":
        return "That user could not be found.";
      default:
        return detail || `HTTP ${res.status}`;
    }
  } catch {
    const txt = await res.text().catch(() => "");
    return txt || `HTTP ${res.status}`;
  }
}

export function AdminUsersPage() {
  const { user } = useAuth();
  const isShowcase = user?.role === "showcase";

  const [q, setQ] = React.useState("");
  const [includeInactive, setIncludeInactive] = React.useState(false);
  const [loading, setLoading] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);
  const [data, setData] = React.useState<AdminUsersResponse | null>(null);
  const [removingUserId, setRemovingUserId] = React.useState<number | null>(null);

  const load = React.useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const url = new URL("/admin/users", window.location.origin);
      url.searchParams.set("limit", "200");
      if (q.trim()) url.searchParams.set("q", q.trim());
      if (includeInactive) url.searchParams.set("include_inactive", "true");

      const res = await apiFetch(url.pathname + url.search, { cache: "no-store" });
      if (!res.ok) throw new Error(await getErrorMessage(res));
      const json = (await res.json()) as AdminUsersResponse;
      setData(json);
    } catch (e: any) {
      setError(e?.message || "Failed to load users.");
    } finally {
      setLoading(false);
    }
  }, [includeInactive, q]);

  React.useEffect(() => {
    const id = window.setTimeout(() => {
      void load();
    }, 220);
    return () => window.clearTimeout(id);
  }, [load]);

  async function removeAccess(target: AdminUserRow) {
    const confirmed = window.confirm(
      `Remove access for ${target.username}?\n\nThis deactivates login and clears subscription state, but keeps historical records like feedback and support conversations.`
    );
    if (!confirmed) return;

    setRemovingUserId(target.user_id);
    setError(null);
    try {
      const res = await apiFetch(`/admin/users/${target.user_id}`, { method: "DELETE" });
      if (!res.ok) throw new Error(await getErrorMessage(res));
      await load();
    } catch (e: any) {
      setError(e?.message || "Failed to remove access.");
    } finally {
      setRemovingUserId(null);
    }
  }

  const users = data?.users ?? [];
  const activeCount = users.filter((row) => Number(row.is_active || 0) === 1).length;
  const adminCount = users.filter((row) => row.role === "admin" && Number(row.is_active || 0) === 1).length;
  const paidCount = users.filter((row) => ["active", "trialing"].includes((row.subscription_status || "").toLowerCase())).length;

  return (
    <div className="space-y-6">
      <div className="glass-panel p-6">
        <div className="flex flex-col gap-4 xl:flex-row xl:items-start xl:justify-between">
          <div className="max-w-3xl">
            <div className="text-xs font-semibold uppercase tracking-[0.18em] muted">Admin controls</div>
            <h1 className="mt-2 text-3xl font-semibold text-zinc-900 dark:text-zinc-100">Users</h1>
            <p className="mt-2 text-sm muted">
              View everyone with platform access, inspect basic account details, and remove access when needed.
            </p>
          </div>

          <button type="button" className="btn-secondary h-10 px-4" onClick={() => void load()} disabled={loading}>
            {loading ? "Reloading…" : "Reload"}
          </button>
        </div>

        <div className="mt-6 grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
          <SummaryCard label="Loaded users" value={users.length.toLocaleString()} helper={`Total matching: ${(data?.total ?? users.length).toLocaleString()}`} />
          <SummaryCard label="Active" value={activeCount.toLocaleString()} helper={includeInactive ? "Includes inactive view" : "Only active users shown"} />
          <SummaryCard label="Active admins" value={adminCount.toLocaleString()} helper="Admin seats currently enabled" />
          <SummaryCard label="Paid / trialing" value={paidCount.toLocaleString()} helper="Users with subscription access" />
        </div>
      </div>

      {isShowcase ? (
        <div className="rounded-2xl border border-cyan-500/30 bg-cyan-500/10 px-4 py-3 text-sm text-cyan-700 dark:text-cyan-300">
          Read-only demo: customer names, emails, and phone numbers are masked, search is off, and access changes are disabled.
        </div>
      ) : null}

      <div className="glass-panel p-5">
        <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_auto] lg:items-center">
          <input
            className="input h-11"
            value={q}
            onChange={(e) => setQ(e.target.value)}
            disabled={isShowcase}
            placeholder={isShowcase ? "Search is disabled in the demo" : "Search by login email, name, contact email, or phone…"}
          />

          <label className="flex items-center gap-3 rounded-2xl border border-zinc-200/70 bg-white/50 px-4 py-3 text-sm dark:border-zinc-800/60 dark:bg-black/20">
            <input
              type="checkbox"
              checked={includeInactive}
              onChange={(e) => setIncludeInactive(e.target.checked)}
              className="h-4 w-4 cursor-pointer rounded border-zinc-400 text-purple-500 focus:ring-purple-500/40"
            />
            Include inactive users
          </label>
        </div>

        <div className="mt-4 rounded-2xl border border-zinc-200/70 bg-white/50 px-4 py-3 text-sm muted dark:border-zinc-800/60 dark:bg-black/20">
          Removing access deactivates login and clears billing state, but keeps the user’s historical records for auditing and support.
        </div>
      </div>

      {error ? <div className="rounded-2xl border border-red-500/30 bg-red-500/10 px-4 py-3 text-sm text-red-700 dark:text-red-300">{error}</div> : null}

      <div className="glass-panel overflow-hidden">
        <div className="overflow-x-auto">
          <table className="min-w-[1100px] w-full text-sm">
            <thead className="border-b border-zinc-200/70 dark:border-zinc-800/60">
              <tr className="text-left">
                <th className="px-5 py-4 font-medium muted">User</th>
                <th className="px-5 py-4 font-medium muted">Role</th>
                <th className="px-5 py-4 font-medium muted">Access</th>
                <th className="px-5 py-4 font-medium muted">Subscription</th>
                <th className="px-5 py-4 font-medium muted">Created</th>
                <th className="px-5 py-4 font-medium muted">Last login</th>
                <th className="px-5 py-4 font-medium muted"></th>
              </tr>
            </thead>
            <tbody>
              {loading && !data ? (
                <tr>
                  <td className="px-5 py-8 text-sm muted" colSpan={7}>
                    Loading users…
                  </td>
                </tr>
              ) : null}

              {!loading && users.length === 0 ? (
                <tr>
                  <td className="px-5 py-8 text-sm muted" colSpan={7}>
                    No users matched the current filters.
                  </td>
                </tr>
              ) : null}

              {users.map((row) => {
                const isActive = Number(row.is_active || 0) === 1;
                const isCurrentUser = Number(user?.user_id || 0) === row.user_id;
                const status = statusLabel(row.subscription_status);
                const periodEnd = row.current_period_end ? `Ends ${fmtDateTime(row.current_period_end)}` : "No renewal date";
                return (
                  <tr key={row.user_id} className="border-b border-zinc-200/60 align-top last:border-b-0 dark:border-zinc-800/60">
                    <td className="px-5 py-4">
                      <div className="flex flex-wrap items-center gap-2">
                        <div className="font-semibold text-zinc-900 dark:text-zinc-100">{row.full_name || row.username}</div>
                        {isCurrentUser ? <span className="badge">You</span> : null}
                        {row.role === "admin" ? <span className="badge">Admin</span> : row.role === "showcase" ? <span className="badge">Showcase</span> : null}
                      </div>
                      <div className="mt-1 text-sm muted">Login: {row.username}</div>
                      {row.contact_email ? <div className="mt-1 text-sm muted">Contact: {row.contact_email}</div> : null}
                      {row.contact_phone ? <div className="mt-1 text-sm muted">Phone: {row.contact_phone}</div> : null}
                      <div className="mt-2 text-xs muted">User ID {row.user_id}</div>
                    </td>

                    <td className="px-5 py-4">
                      <div className="font-medium capitalize text-zinc-900 dark:text-zinc-100">{row.role}</div>
                      <div className="mt-1 text-xs muted">Updated {fmtDateTime(row.updated_at)}</div>
                    </td>

                    <td className="px-5 py-4">
                      {isActive ? (
                        <span className="inline-flex rounded-full border border-emerald-500/30 bg-emerald-500/10 px-2.5 py-1 text-xs font-medium text-emerald-700 dark:text-emerald-300">
                          Active
                        </span>
                      ) : (
                        <span className="inline-flex rounded-full border border-zinc-400/30 bg-zinc-500/10 px-2.5 py-1 text-xs font-medium text-zinc-700 dark:text-zinc-300">
                          Inactive
                        </span>
                      )}
                      <div className="mt-2 text-xs muted">{isActive ? "Can currently sign in" : "Sign-in disabled"}</div>
                    </td>

                    <td className="px-5 py-4">
                      <div className="font-medium capitalize text-zinc-900 dark:text-zinc-100">{status}</div>
                      <div className="mt-1 text-xs muted">{periodEnd}</div>
                      {Number(row.cancel_at_period_end || 0) === 1 ? <div className="mt-1 text-xs text-amber-600 dark:text-amber-300">Cancels at period end</div> : null}
                    </td>

                    <td className="px-5 py-4 text-sm text-zinc-900 dark:text-zinc-100">{fmtDateTime(row.created_at)}</td>
                    <td className="px-5 py-4 text-sm text-zinc-900 dark:text-zinc-100">{fmtDateTime(row.last_login_at)}</td>
                    <td className="px-5 py-4 text-right">
                      <button
                        type="button"
                        className="btn-secondary h-9 px-3"
                        disabled={isShowcase || !isActive || isCurrentUser || removingUserId === row.user_id}
                        onClick={() => void removeAccess(row)}
                      >
                        {isShowcase ? "Read only" : removingUserId === row.user_id ? "Removing…" : "Remove access"}
                      </button>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
