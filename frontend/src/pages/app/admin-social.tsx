import { useAuth } from "@/components/auth-provider";
import { XPostChartRenderer } from "@/components/x-post-chart";
import { XPostPreview } from "@/components/x-post-preview";
import { apiFetch } from "@/lib/api";
import { fmtDate, fmtUsd } from "@/lib/format";
import type { XPostChartPayload } from "@/lib/types";
import * as React from "react";
import { useSearchParams } from "react-router-dom";

type Mode = "new_signal" | "best_performing";
type SocialCandidate = Record<string, any> & {
  signal_id: string;
  ticker?: string;
  issuer_name?: string;
  filing_date?: string;
  insider_name?: string;
  insider_names?: string[];
  insider_count?: number;
  signal_side?: string;
  signal_score?: number;
  percent_return?: number;
  latest_price?: number;
  transaction_dollar_value?: number;
  is_posted?: boolean;
  social_status?: string | null;
  social_tweet_url?: string | null;
};

function fmtReturn(value: unknown): string {
  const n = Number(value);
  if (!Number.isFinite(n)) return "-";
  return `${n > 0 ? "+" : ""}${n.toFixed(1)}%`;
}

function candidateSubtitle(candidate: SocialCandidate, mode: Mode): string {
  const names = Array.isArray(candidate.insider_names) ? candidate.insider_names.filter(Boolean) : [];
  if (mode === "best_performing" && Number(candidate.insider_count || 0) > 1) {
    const shown = names.slice(0, 2).join(", ");
    const suffix = Number(candidate.insider_count) > 2 ? ` + ${Number(candidate.insider_count) - 2} more` : "";
    return `${candidate.insider_count} insiders: ${shown}${suffix}`;
  }
  return `${candidate.insider_name || "Insider"} filed ${fmtDate(candidate.filing_date)}`;
}

function statusBadge(candidate: SocialCandidate) {
  if (candidate.is_posted) {
    return <span className="rounded-full border border-emerald-500/30 bg-emerald-500/10 px-2 py-0.5 text-xs font-medium text-emerald-300">Posted</span>;
  }
  if (candidate.social_status) {
    return <span className="rounded-full border border-amber-500/30 bg-amber-500/10 px-2 py-0.5 text-xs font-medium text-amber-300">{candidate.social_status}</span>;
  }
  return <span className="rounded-full border border-zinc-700 bg-zinc-900/70 px-2 py-0.5 text-xs text-zinc-400">Not posted</span>;
}

export function AdminSocialPage() {
  const { user } = useAuth();
  if (user?.role !== "admin") return <div className="text-sm muted">Admin only.</div>;

  const [sp] = useSearchParams();
  const [mode, setMode] = React.useState<Mode>("new_signal");
  const [content, setContent] = React.useState("");
  const [linkUrl, setLinkUrl] = React.useState("https://insidrsai.com/pricing");
  const [sourceSignalId, setSourceSignalId] = React.useState(sp.get("signal_id") || "");
  const [candidates, setCandidates] = React.useState<SocialCandidate[]>([]);
  const [candidatesLoading, setCandidatesLoading] = React.useState(false);
  const [selectedCandidate, setSelectedCandidate] = React.useState<SocialCandidate | null>(null);
  const [preview, setPreview] = React.useState("");
  const [posts, setPosts] = React.useState<any[]>([]);
  const [chartPayload, setChartPayload] = React.useState<XPostChartPayload | null>(null);
  const [chartImageDataUrl, setChartImageDataUrl] = React.useState<string | null>(null);
  const [chartRendering, setChartRendering] = React.useState(false);
  const [isGenerating, setIsGenerating] = React.useState(false);
  const [isPosting, setIsPosting] = React.useState(false);
  const [notice, setNotice] = React.useState<string>("");
  const [error, setError] = React.useState<string>("");

  const load = () =>
    apiFetch("/admin/social/posts")
      .then((r) => (r.ok ? r.json() : { posts: [] }))
      .then((j) => setPosts(j.posts || []));

  React.useEffect(() => {
    load();
  }, []);

  const loadCandidates = React.useCallback(() => {
    setCandidatesLoading(true);
    apiFetch(`/admin/social/x/candidates?mode=${mode}&limit=${mode === "best_performing" ? 20 : 30}`)
      .then((r) => (r.ok ? r.json() : { candidates: [] }))
      .then((j) => {
        const next = Array.isArray(j?.candidates) ? j.candidates : [];
        setCandidates(next);
        setSelectedCandidate((current) => {
          if (!current) return null;
          return next.find((candidate: SocialCandidate) => candidate.signal_id === current.signal_id) || null;
        });
      })
      .catch(() => setCandidates([]))
      .finally(() => setCandidatesLoading(false));
  }, [mode]);

  React.useEffect(() => {
    setSelectedCandidate(null);
    setSourceSignalId("");
    clearGeneratedChart();
    setContent("");
    loadCandidates();
  }, [loadCandidates]);

  const handleChartImageReady = React.useCallback((dataUrl: string | null) => {
    setChartImageDataUrl(dataUrl);
    setChartRendering(false);
  }, []);

  const clearGeneratedChart = () => {
    setChartPayload(null);
    setChartImageDataUrl(null);
    setChartRendering(false);
    setPreview("");
  };

  const selectCandidate = (candidate: SocialCandidate) => {
    setSelectedCandidate(candidate);
    setSourceSignalId(candidate.signal_id);
    setContent("");
    clearGeneratedChart();
    setNotice("");
    setError("");
  };

  const generateTemplate = async () => {
    setNotice("");
    setError("");
    setIsGenerating(true);
    setChartPayload(null);
    setChartImageDataUrl(null);
    setChartRendering(false);
    try {
      const r = await apiFetch("/admin/social/x/template", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ mode, source_signal_id: sourceSignalId }),
      });
      const j = await r.json();
      if (!r.ok) throw new Error(typeof j?.detail === "string" ? j.detail : "Failed to generate template");
      const nextContent = j.content || "";
      const nextChart = (j.chart || null) as XPostChartPayload | null;
      setContent(nextContent);
      setPreview(nextContent);
      setChartPayload(nextChart);
      setChartRendering(Boolean(nextChart));
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to generate template");
    } finally {
      setIsGenerating(false);
    }
  };

  const doPreview = async () => {
    const r = await apiFetch("/admin/social/x/preview", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ content, source_signal_id: sourceSignalId, chart_image_data_url: chartImageDataUrl }),
    });
    const j = await r.json();
    setPreview(j.content || "");
  };

  const doPost = async () => {
    setNotice("");
    setError("");
    setIsPosting(true);
    try {
      const res = await apiFetch("/admin/social/x/post", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ content, link_url: linkUrl, source_signal_id: sourceSignalId, chart_image_data_url: chartImageDataUrl }),
      });
      const body = await res.json().catch(() => ({}));
      if (!res.ok) {
        const detail = (body as any)?.detail;
        const msg =
          typeof detail === "string"
            ? detail
            : typeof detail?.error === "string"
              ? detail.error
              : "Failed to post to X";
        setError(msg);
        return;
      }
      const status = String((body as any)?.post?.status || "");
      if (status === "dry_run") {
        setNotice("Dry-run mode: chart + post were prepared but not published. Set X_POSTING_ENABLED=1 for live posting.");
      } else if (status === "posted") {
        setNotice("Posted to X successfully, including chart attachment when available.");
      } else {
        setNotice(`Post finished with status: ${status || "unknown"}`);
      }
      load();
      loadCandidates();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to post to X");
    } finally {
      setIsPosting(false);
    }
  };

  return (
    <div className="space-y-4">
      <h1 className="text-2xl font-semibold">Admin Social Posting</h1>

      <div className="flex flex-wrap gap-2">
        <button className={mode === "new_signal" ? "btn-primary" : "btn-secondary"} onClick={() => setMode("new_signal")}>New signals</button>
        <button className={mode === "best_performing" ? "btn-primary" : "btn-secondary"} onClick={() => setMode("best_performing")}>Best performers</button>
        <button className="btn-secondary" onClick={loadCandidates} disabled={candidatesLoading}>Refresh list</button>
      </div>

      <div className="glass-panel overflow-hidden">
        <div className="flex items-center justify-between border-b border-zinc-800/70 px-4 py-3">
          <div>
            <div className="text-sm font-semibold">{mode === "best_performing" ? "Best performers to post" : "New signals to post"}</div>
            <div className="text-xs muted">Pick one, generate a template, then post to X.</div>
          </div>
          <div className="text-xs muted">{candidatesLoading ? "Loading..." : `${candidates.length} loaded`}</div>
        </div>
        {candidatesLoading ? (
          <div className="p-4 text-sm muted">Loading candidates...</div>
        ) : candidates.length === 0 ? (
          <div className="p-4 text-sm muted">No candidates found.</div>
        ) : (
          <div className="max-h-[420px] divide-y divide-zinc-800/70 overflow-y-auto">
            {candidates.map((candidate) => {
              const selected = candidate.signal_id === sourceSignalId;
              return (
                <button
                  type="button"
                  key={candidate.signal_id}
                  onClick={() => selectCandidate(candidate)}
                  className={[
                    "grid w-full grid-cols-[minmax(0,1fr)_auto] gap-3 px-4 py-3 text-left transition hover:bg-white/5",
                    selected ? "bg-purple-500/10" : "",
                  ].join(" ")}
                >
                  <div className="min-w-0">
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="font-semibold text-zinc-100">${String(candidate.ticker || "").toUpperCase()}</span>
                      <span className="truncate text-sm text-zinc-400">{candidate.issuer_name || "Insider signal"}</span>
                      {statusBadge(candidate)}
                    </div>
                    <div className="mt-1 truncate text-xs muted">{candidateSubtitle(candidate, mode)}</div>
                  </div>
                  <div className="text-right text-sm">
                    {mode === "best_performing" ? (
                      <>
                        <div className="font-semibold text-emerald-300">{fmtReturn(candidate.percent_return)}</div>
                        <div className="text-xs muted">{fmtUsd(Number(candidate.latest_price))}</div>
                      </>
                    ) : (
                      <>
                        <div className="font-semibold text-zinc-100">{candidate.signal_side || "SIGNAL"}</div>
                        <div className="text-xs muted">
                          {Number(candidate.signal_score) >= 0 ? `${Number(candidate.signal_score).toFixed(1)}/10` : fmtUsd(Number(candidate.transaction_dollar_value), { digits: 0 })}
                        </div>
                      </>
                    )}
                  </div>
                </button>
              );
            })}
          </div>
        )}
      </div>

      <input className="input" readOnly placeholder="Selected signal id" value={sourceSignalId} />
      <div className="flex gap-2">
        <button className="btn-secondary" onClick={generateTemplate} disabled={isGenerating || !sourceSignalId.trim()}>
          {isGenerating ? "Generating..." : "Generate template"}
        </button>
      </div>

      <textarea
        className="input min-h-[180px] w-full"
        value={content}
        onChange={(e) => {
          setContent(e.target.value);
          setPreview("");
        }}
      />
      <div className="text-xs muted">{content.length}/280</div>
      <input className="input" placeholder="Promo/free-trial link" value={linkUrl} onChange={(e) => setLinkUrl(e.target.value)} />
      <div className="flex gap-2">
        <button className="btn-secondary" onClick={doPreview}>Refresh preview</button>
        <button className="btn-primary" onClick={doPost} disabled={isPosting || chartRendering || (!!chartPayload && !chartImageDataUrl)}>
          {isPosting ? "Posting..." : chartRendering ? "Rendering chart..." : "Post to X"}
        </button>
      </div>
      {notice ? <div className="rounded-md border border-emerald-500/30 bg-emerald-500/10 px-3 py-2 text-sm text-emerald-300">{notice}</div> : null}
      {error ? <div className="rounded-md border border-red-500/30 bg-red-500/10 px-3 py-2 text-sm text-red-300">{error}</div> : null}

      <XPostChartRenderer payload={chartPayload} onImageReady={handleChartImageReady} />

      {chartPayload && chartRendering ? (
        <div className="rounded-md border border-cyan-500/30 bg-cyan-500/10 px-3 py-2 text-sm text-cyan-200">
          Rendering the X chart attachment...
        </div>
      ) : null}

      <div className="space-y-2">
        <div className="text-sm font-semibold">X preview</div>
        <XPostPreview content={preview || content} chartImageDataUrl={chartImageDataUrl} />
      </div>

      <div className="space-y-2">
        {posts.map((p: any) => (
          <div key={p.post_id} className="glass-card p-3 text-sm">
            <div>
              {p.status} {p.x_tweet_url ? <a className="link" href={p.x_tweet_url}>Open</a> : null}
            </div>
            <div>{p.content}</div>
            {p.error_message ? <div className="text-red-500">{p.error_message}</div> : null}
          </div>
        ))}
      </div>
    </div>
  );
}
