import * as React from "react";
import { Link } from "react-router-dom";
import {
  ResponsiveContainer,
  LineChart,
  Line,
  XAxis,
  YAxis,
  Tooltip,
  CartesianGrid,
  Legend,
} from "recharts";

import { apiFetch } from "@/lib/api";

type JobTypeCount = { job_type: string; count: number };

type ThroughputPoint = {
  hour: string; // ISO hour bucket
  success: number;
  error: number;
};

type LatencyRow = {
  job_type: string;
  n: number;
  avg_sec: number | null;
  p50_sec?: number | null;
  p95_sec?: number | null;
};

type BackfillCount = { status: string; count: number };

type RecentError = {
  job_id: number;
  job_type: string;
  status: string;
  dedupe_key: string;
  attempts: number;
  last_error?: string | null;
  created_at: string;
  updated_at: string;
};

type TableCounts = {
  issuer_master?: number;
  insider_events?: number;
  ai_outputs?: number;
  users?: number;
};

type MonitoringResponse = {
  now: string;
  window_hours: number;
  dialect: string;
  status_counts: Record<string, number>;
  oldest_pending_age_sec: number | null;
  pending_by_type: JobTypeCount[];
  error_by_type: JobTypeCount[];
  throughput_hourly: ThroughputPoint[];
  latency_by_type: LatencyRow[];
  backfill_counts: BackfillCount[];
  table_counts: TableCounts;
  recent_errors: RecentError[];
};

function fmtSeconds(sec: number | null | undefined): string {
  if (sec == null || Number.isNaN(sec)) return "—";
  if (sec < 60) return `${sec.toFixed(1)}s`;
  const m = sec / 60;
  if (m < 60) return `${m.toFixed(1)}m`;
  const h = m / 60;
  return `${h.toFixed(1)}h`;
}

function fmtHourLabel(iso: string): string {
  // show HH:mm (or date if needed)
  try {
    const d = new Date(iso);
    return d.toLocaleString(undefined, { month: "short", day: "2-digit", hour: "2-digit", minute: "2-digit" });
  } catch {
    return iso;
  }
}

export function AdminMonitoringPage() {
  const [windowHours, setWindowHours] = React.useState(24);
  const [data, setData] = React.useState<MonitoringResponse | null>(null);
  const [loading, setLoading] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);
  const [refreshKey, setRefreshKey] = React.useState(0);
  const [selectedError, setSelectedError] = React.useState<RecentError | null>(null);

  React.useEffect(() => {
    let cancelled = false;
    (async () => {
      setLoading(true);
      setError(null);
      try {
        const url = new URL("/api/backend/admin/monitoring", window.location.origin);
        url.searchParams.set("window_hours", String(windowHours));
        const res = await apiFetch(url.pathname + url.search, { cache: "no-store" });
        if (!res.ok) throw new Error(await res.text());
        const json = (await res.json()) as MonitoringResponse;
        if (!cancelled) setData(json);
      } catch (e: any) {
        if (!cancelled) setError(e?.message || "Failed to load monitoring");
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();

    return () => {
      cancelled = true;
    };
  }, [windowHours, refreshKey]);

  const status = data?.status_counts || {};
  const pending = status["pending"] || 0;
  const running = status["running"] || 0;
  const success = status["success"] || 0;
  const err = status["error"] || 0;

  const backlogNote = (() => {
    const age = data?.oldest_pending_age_sec;
    if (pending === 0) return "No backlog.";
    if (age == null) return "Backlog present.";
    if (age < 5 * 60) return "Backlog is shallow (oldest pending < 5m).";
    if (age < 60 * 60) return "Backlog is moderate (oldest pending < 1h).";
    return "Backlog is heavy (oldest pending > 1h) — consider more workers.";
  })();

  return (
    <div className="space-y-6">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <h1 className="text-2xl font-semibold">Monitoring</h1>
          <p className="mt-1 text-sm muted">
            Aggregate pipeline health for admins. For raw rows, see{" "}
            <Link className="link" to="/app/admin/jobs">
              Jobs
            </Link>
            .
          </p>
        </div>

        <div className="flex flex-wrap items-center gap-2">
          <select
            className="input h-9 w-[180px]"
            value={windowHours}
            onChange={(e) => setWindowHours(Number(e.target.value))}
          >
            <option value={6}>Last 6 hours</option>
            <option value={24}>Last 24 hours</option>
            <option value={72}>Last 3 days</option>
            <option value={168}>Last 7 days</option>
          </select>
          <button type="button" className="btn-secondary" onClick={() => setRefreshKey((x) => x + 1)}>
            Refresh
          </button>
        </div>
      </div>

      {error && (
        <div className="rounded-md border border-red-500/30 bg-red-500/10 px-3 py-2 text-sm text-red-700 dark:text-red-300">
          {error}
        </div>
      )}

      {/* Summary cards */}
      <div data-tour="monitoring-overview" className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <div className="glass-card p-4">
          <div className="text-xs uppercase tracking-wide muted">Pending</div>
          <div className="mt-1 text-2xl font-semibold">{pending.toLocaleString()}</div>
          <div className="mt-1 text-xs muted">{backlogNote}</div>
        </div>
        <div className="glass-card p-4">
          <div className="text-xs uppercase tracking-wide muted">Running</div>
          <div className="mt-1 text-2xl font-semibold">{running.toLocaleString()}</div>
          <div className="mt-1 text-xs muted">Currently claimed by workers</div>
        </div>
        <div className="glass-card p-4">
          <div className="text-xs uppercase tracking-wide muted">Errors</div>
          <div className="mt-1 text-2xl font-semibold">{err.toLocaleString()}</div>
          <div className="mt-1 text-xs muted">Total (historical)</div>
        </div>
        <div className="glass-card p-4">
          <div className="text-xs uppercase tracking-wide muted">Success</div>
          <div className="mt-1 text-2xl font-semibold">{success.toLocaleString()}</div>
          <div className="mt-1 text-xs muted">Total (historical)</div>
        </div>
      </div>

      {/* Throughput */}
      <div className="glass-card p-4">
        <div className="flex flex-wrap items-end justify-between gap-2">
          <div>
            <div className="text-sm font-semibold">Throughput</div>
            <div className="text-xs muted">Jobs completed per hour (success vs error)</div>
          </div>
          <div className="text-xs muted">Window: {windowHours}h • Now: {data?.now || "—"}</div>
        </div>

        <div className="mt-4 h-64 w-full">
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={(data?.throughput_hourly || []).map((p) => ({ ...p, label: fmtHourLabel(p.hour) }))}>
              <CartesianGrid strokeDasharray="3 3" />
              <XAxis dataKey="label" tick={{ fontSize: 10 }} minTickGap={24} />
              <YAxis tick={{ fontSize: 10 }} />
              <Tooltip />
              <Legend />
              <Line type="monotone" dataKey="success" dot={false} />
              <Line type="monotone" dataKey="error" dot={false} />
            </LineChart>
          </ResponsiveContainer>
        </div>
      </div>

      <div className="grid gap-6 lg:grid-cols-2">
        {/* Pending breakdown */}
        <div className="glass-card p-4">
          <div className="text-sm font-semibold">Pending by job type</div>
          <div className="mt-1 text-xs muted">Top categories by queue depth</div>
          <div className="mt-4 overflow-hidden rounded-lg border border-zinc-200/60 dark:border-zinc-800/60">
            <table className="min-w-full text-sm">
              <thead className="text-left text-xs uppercase tracking-wide text-zinc-500">
                <tr className="border-b border-zinc-200/60 dark:border-zinc-800/60">
                  <th className="px-3 py-2">job_type</th>
                  <th className="px-3 py-2 text-right">pending</th>
                </tr>
              </thead>
              <tbody>
                {(data?.pending_by_type || []).map((r) => (
                  <tr key={r.job_type} className="border-b border-zinc-200/40 dark:border-zinc-800/50">
                    <td className="px-3 py-2 font-mono text-xs">{r.job_type}</td>
                    <td className="px-3 py-2 text-right font-mono text-xs">{r.count.toLocaleString()}</td>
                  </tr>
                ))}
                {!loading && (data?.pending_by_type || []).length === 0 && (
                  <tr>
                    <td className="px-3 py-3 muted" colSpan={2}>
                      No pending jobs.
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </div>

        {/* Error breakdown */}
        <div className="glass-card p-4">
          <div className="text-sm font-semibold">Errors by job type</div>
          <div className="mt-1 text-xs muted">Top categories by historical error count</div>

          <div className="mt-4 overflow-hidden rounded-lg border border-zinc-200/60 dark:border-zinc-800/60">
            <table className="min-w-full text-sm">
              <thead className="text-left text-xs uppercase tracking-wide text-zinc-500">
                <tr className="border-b border-zinc-200/60 dark:border-zinc-800/60">
                  <th className="px-3 py-2">job_type</th>
                  <th className="px-3 py-2 text-right">errors</th>
                </tr>
              </thead>
              <tbody>
                {(data?.error_by_type || []).map((r) => (
                  <tr key={r.job_type} className="border-b border-zinc-200/40 dark:border-zinc-800/50">
                    <td className="px-3 py-2 font-mono text-xs">{r.job_type}</td>
                    <td className="px-3 py-2 text-right font-mono text-xs">{r.count.toLocaleString()}</td>
                  </tr>
                ))}
                {!loading && (data?.error_by_type || []).length === 0 && (
                  <tr>
                    <td className="px-3 py-3 muted" colSpan={2}>
                      No errors.
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </div>

        {/* Latency breakdown */}
        <div className="glass-card p-4">
          <div className="text-sm font-semibold">Latency by job type</div>
          <div className="mt-1 text-xs muted">End-to-end time (enqueue → completed) for successful jobs in window</div>

          <div className="mt-4 overflow-hidden rounded-lg border border-zinc-200/60 dark:border-zinc-800/60">
            <table className="min-w-full text-sm">
              <thead className="text-left text-xs uppercase tracking-wide text-zinc-500">
                <tr className="border-b border-zinc-200/60 dark:border-zinc-800/60">
                  <th className="px-3 py-2">job_type</th>
                  <th className="px-3 py-2 text-right">n</th>
                  <th className="px-3 py-2 text-right">avg</th>
                  <th className="px-3 py-2 text-right">p95</th>
                </tr>
              </thead>
              <tbody>
                {(data?.latency_by_type || []).map((r) => (
                  <tr key={r.job_type} className="border-b border-zinc-200/40 dark:border-zinc-800/50">
                    <td className="px-3 py-2 font-mono text-xs">{r.job_type}</td>
                    <td className="px-3 py-2 text-right font-mono text-xs">{r.n.toLocaleString()}</td>
                    <td className="px-3 py-2 text-right font-mono text-xs">{fmtSeconds(r.avg_sec)}</td>
                    <td className="px-3 py-2 text-right font-mono text-xs">{fmtSeconds(r.p95_sec ?? null)}</td>
                  </tr>
                ))}
                {!loading && (data?.latency_by_type || []).length === 0 && (
                  <tr>
                    <td className="px-3 py-3 muted" colSpan={4}>
                      No successful jobs in this window.
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </div>
      </div>

      {/* Backfill queue + table counts */}
      <div className="grid gap-6 lg:grid-cols-2">
        <div className="glass-card p-4">
          <div className="text-sm font-semibold">Backfill queue</div>
          <div className="mt-1 text-xs muted">Status counts from backfill_queue</div>

          <div className="mt-4 flex flex-wrap gap-2">
            {(data?.backfill_counts || []).map((r) => (
              <span key={r.status} className="badge">
                {r.status}: {r.count.toLocaleString()}
              </span>
            ))}
            {!loading && (data?.backfill_counts || []).length === 0 && <span className="muted">—</span>}
          </div>
        </div>

        <div className="glass-card p-4">
          <div className="text-sm font-semibold">Database snapshot</div>
          <div className="mt-1 text-xs muted">Lightweight row counts (approx health check)</div>
          <div className="mt-4 grid grid-cols-2 gap-3 text-sm">
            <div className="glass-card p-3">
              <div className="text-xs uppercase tracking-wide muted">issuers</div>
              <div className="mt-1 text-lg font-semibold">{(data?.table_counts?.issuer_master ?? 0).toLocaleString()}</div>
            </div>
            <div className="glass-card p-3">
              <div className="text-xs uppercase tracking-wide muted">events</div>
              <div className="mt-1 text-lg font-semibold">{(data?.table_counts?.insider_events ?? 0).toLocaleString()}</div>
            </div>
            <div className="glass-card p-3">
              <div className="text-xs uppercase tracking-wide muted">ai_outputs</div>
              <div className="mt-1 text-lg font-semibold">{(data?.table_counts?.ai_outputs ?? 0).toLocaleString()}</div>
            </div>
            <div className="glass-card p-3">
              <div className="text-xs uppercase tracking-wide muted">users</div>
              <div className="mt-1 text-lg font-semibold">{(data?.table_counts?.users ?? 0).toLocaleString()}</div>
            </div>
          </div>
        </div>
      </div>

      {/* Recent errors */}
      <div className="glass-card p-4">
        <div className="flex flex-wrap items-end justify-between gap-2">
          <div>
            <div className="text-sm font-semibold">Recent errors</div>
            <div className="text-xs muted">Latest jobs with status=error</div>
          </div>
          <Link to="/app/admin/jobs" className="link text-xs">
            View in Jobs →
          </Link>
        </div>

        <div className="mt-4 overflow-hidden rounded-lg border border-zinc-200/60 dark:border-zinc-800/60">
          <table className="min-w-full text-sm">
            <thead className="text-left text-xs uppercase tracking-wide text-zinc-500">
              <tr className="border-b border-zinc-200/60 dark:border-zinc-800/60">
                <th className="px-3 py-2">when</th>
                <th className="px-3 py-2">type</th>
                <th className="px-3 py-2">dedupe</th>
                <th className="px-3 py-2">error</th>
                <th className="px-3 py-2 text-right">attempts</th>
              </tr>
            </thead>
            <tbody>
              {(data?.recent_errors || []).map((j) => (
                <tr key={j.job_id} className="border-b border-zinc-200/40 dark:border-zinc-800/50">
                  <td className="px-3 py-2 font-mono text-xs">{j.updated_at}</td>
                  <td className="px-3 py-2 font-mono text-xs">{j.job_type}</td>
                  <td className="px-3 py-2 font-mono text-xs">{j.dedupe_key}</td>
                  <td className="px-3 py-2">
                    {j.last_error ? (
                      <button
                        type="button"
                        className="link text-left text-xs font-mono"
                        onClick={() => setSelectedError(j)}
                        title="View full error"
                      >
                        {String(j.last_error).slice(0, 120)}
                        {String(j.last_error).length > 120 ? "…" : ""}
                      </button>
                    ) : (
                      <span className="muted">—</span>
                    )}
                  </td>
                  <td className="px-3 py-2 text-right font-mono text-xs">{j.attempts}</td>
                </tr>
              ))}
              {!loading && (data?.recent_errors || []).length === 0 && (
                <tr>
                  <td className="px-3 py-3 muted" colSpan={5}>
                    No recent errors.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>

        {(data?.recent_errors || []).length > 0 && (
          <div className="mt-3 text-xs muted">
            Tip: the worker logs usually contain the full traceback. For schema-related errors, run migrations (or re-run init_db after updating schema).
          </div>
        )}
      </div>

      {/* Error modal */}
      {selectedError && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 px-4 py-8" role="dialog" aria-modal>
          <div className="glass-card w-full max-w-3xl p-4">
            <div className="flex items-start justify-between gap-4">
              <div>
                <div className="text-sm font-semibold">Error details</div>
                <div className="mt-1 text-xs muted">
                  job_id {selectedError.job_id} • {selectedError.job_type} • attempts {selectedError.attempts}
                </div>
              </div>
              <button type="button" className="btn-secondary" onClick={() => setSelectedError(null)}>
                Close
              </button>
            </div>

            <pre className="mt-3 max-h-[60vh] overflow-auto rounded bg-black/5 p-3 text-xs leading-relaxed dark:bg-white/5">
              {String(selectedError.last_error || "(no error text)")}
            </pre>
          </div>
        </div>
      )}
    </div>
  );
}
