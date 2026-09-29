import * as React from "react";

import { useAuth } from "@/components/auth-provider";
import { apiFetch } from "@/lib/api";

type SupportThreadRow = {
  thread_id: number;
  user_id: number;
  username: string;
  status: "open" | "closed";
  created_at: string;
  updated_at: string;
  last_message_at?: string | null;
  last_message?: string | null;
  last_sender_role?: "user" | "admin" | null;
  message_count?: number | null;
};

type SupportMessage = {
  message_id: number;
  thread_id: number;
  sender_role: "user" | "admin";
  sender_user_id?: number | null;
  sender_username?: string | null;
  message: string;
  created_at: string;
};

type ThreadDetailResponse = {
  thread: SupportThreadRow;
  messages: SupportMessage[];
};

function fmtTime(iso: string | null | undefined): string {
  if (!iso) return "";
  try {
    const d = new Date(iso);
    return d.toLocaleString(undefined, { month: "short", day: "2-digit", hour: "2-digit", minute: "2-digit" });
  } catch {
    return iso;
  }
}

export function AdminSupportPage() {
  const { user } = useAuth();
  const isShowcase = user?.role === "showcase";
  const [status, setStatus] = React.useState<"open" | "closed" | "all">("open");
  const [threads, setThreads] = React.useState<SupportThreadRow[]>([]);
  const [loadingThreads, setLoadingThreads] = React.useState(false);
  const [threadsError, setThreadsError] = React.useState<string | null>(null);

  const [selectedThreadId, setSelectedThreadId] = React.useState<number | null>(null);
  const [detail, setDetail] = React.useState<ThreadDetailResponse | null>(null);
  const [loadingDetail, setLoadingDetail] = React.useState(false);
  const [detailError, setDetailError] = React.useState<string | null>(null);

  const [draft, setDraft] = React.useState("");
  const [sending, setSending] = React.useState(false);
  const [closeOnSend, setCloseOnSend] = React.useState(false);
  const scrollRef = React.useRef<HTMLDivElement | null>(null);

  async function loadThreads() {
    setLoadingThreads(true);
    setThreadsError(null);
    try {
      const url = new URL("/api/backend/admin/support/threads", window.location.origin);
      if (status !== "all") url.searchParams.set("status", status);
      url.searchParams.set("limit", "100");
      const res = await apiFetch(url.pathname + url.search, { cache: "no-store" });
      if (!res.ok) throw new Error(await res.text());
      const json = await res.json();
      const rows = (json?.threads ?? []) as SupportThreadRow[];
      setThreads(rows);
      if (rows.length > 0 && selectedThreadId == null) {
        setSelectedThreadId(rows[0].thread_id);
      }
    } catch (e: any) {
      setThreadsError(e?.message || "Failed to load threads");
    } finally {
      setLoadingThreads(false);
    }
  }

  async function loadDetail(tid: number) {
    setLoadingDetail(true);
    setDetailError(null);
    try {
      const res = await apiFetch(`/admin/support/thread/${tid}`, { cache: "no-store" });
      if (!res.ok) throw new Error(await res.text());
      const json = (await res.json()) as ThreadDetailResponse;
      setDetail(json);
    } catch (e: any) {
      setDetailError(e?.message || "Failed to load thread");
      setDetail(null);
    } finally {
      setLoadingDetail(false);
    }
  }

  async function send() {
    if (!selectedThreadId) return;
    const msg = draft.trim();
    if (!msg) return;
    setSending(true);
    setDetailError(null);
    try {
      const res = await apiFetch(`/admin/support/thread/${selectedThreadId}/message`, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ message: msg, close_thread: closeOnSend ? true : undefined }),
      });
      if (!res.ok) throw new Error(await res.text());
      setDraft("");
      setCloseOnSend(false);
      await Promise.all([loadDetail(selectedThreadId), loadThreads()]);
    } catch (e: any) {
      setDetailError(e?.message || "Failed to send");
    } finally {
      setSending(false);
    }
  }

  React.useEffect(() => {
    void loadThreads();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [status]);

  React.useEffect(() => {
    if (selectedThreadId == null) {
      setDetail(null);
      return;
    }
    void loadDetail(selectedThreadId);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedThreadId]);

  React.useEffect(() => {
    const el = scrollRef.current;
    if (!el) return;
    el.scrollTop = el.scrollHeight;
  }, [detail?.messages?.length]);

  return (
    <div className="space-y-6">
      <div className="flex items-end justify-between gap-4 flex-wrap">
        <div>
          <h1 className="text-2xl font-semibold">Support inbox</h1>
          <p className="mt-1 text-sm muted">View and respond to in-app support chats.</p>
        </div>

        <div className="flex items-center gap-2">
          <label className="text-sm muted" htmlFor="status">
            Status
          </label>
          <select id="status" className="input h-9 w-[160px]" value={status} onChange={(e) => setStatus(e.target.value as any)}>
            <option value="open">Open</option>
            <option value="closed">Closed</option>
            <option value="all">All</option>
          </select>
          <button type="button" className="btn-secondary h-9 px-3" onClick={() => void loadThreads()} disabled={loadingThreads}>
            Refresh
          </button>
        </div>
      </div>

      {isShowcase ? (
        <div className="rounded-2xl border border-cyan-500/30 bg-cyan-500/10 px-4 py-3 text-sm text-cyan-700 dark:text-cyan-300">
          Read-only demo: customer emails and phone numbers are masked, and replying is disabled.
        </div>
      ) : null}

      <div className="grid gap-4 lg:grid-cols-[360px_1fr]">
        <div className="glass-card overflow-hidden">
          <div className="border-b border-zinc-200/60 px-4 py-3 dark:border-zinc-800/60">
            <div className="text-sm font-semibold">Threads</div>
            <div className="text-xs muted">{threads.length} total</div>
          </div>

          {threadsError && <div className="p-4 text-sm text-red-700 dark:text-red-300">{threadsError}</div>}

          <div className="max-h-[70vh] overflow-auto">
            {loadingThreads && threads.length === 0 ? <div className="p-4 text-sm muted">Loading…</div> : null}
            {threads.map((t) => (
              <button
                key={t.thread_id}
                type="button"
                onClick={() => setSelectedThreadId(t.thread_id)}
                className={
                  "w-full border-b border-zinc-200/60 px-4 py-3 text-left dark:border-zinc-800/60 " +
                  (selectedThreadId === t.thread_id ? "bg-black/5 dark:bg-white/10" : "hover:bg-black/5 dark:hover:bg-white/5")
                }
              >
                <div className="flex items-center justify-between gap-3">
                  <div className="text-sm font-semibold">{t.username}</div>
                  <span className="badge">{t.status}</span>
                </div>
                <div className="mt-1 text-xs muted">
                  #{t.thread_id} • {fmtTime(t.last_message_at || t.updated_at)}
                  {typeof t.message_count === "number" ? ` • ${t.message_count} msgs` : ""}
                </div>
                {t.last_message && <div className="mt-2 text-xs muted line-clamp-2">{t.last_message}</div>}
              </button>
            ))}
            {!loadingThreads && threads.length === 0 && <div className="p-4 text-sm muted">No threads.</div>}
          </div>
        </div>

        <div className="glass-card overflow-hidden">
          <div className="border-b border-zinc-200/60 px-4 py-3 dark:border-zinc-800/60">
            <div className="text-sm font-semibold">Conversation</div>
            {detail?.thread ? (
              <div className="mt-1 text-xs muted">
                Thread #{detail.thread.thread_id} • {detail.thread.username} • {detail.thread.status}
              </div>
            ) : (
              <div className="mt-1 text-xs muted">Select a thread to view.</div>
            )}
          </div>

          {detailError && <div className="p-4 text-sm text-red-700 dark:text-red-300">{detailError}</div>}

          <div ref={scrollRef} className="max-h-[58vh] overflow-auto p-4">
            {loadingDetail ? <div className="text-sm muted">Loading…</div> : null}
            {!loadingDetail && detail?.messages?.length === 0 ? <div className="text-sm muted">No messages.</div> : null}

            <div className="space-y-2">
              {(detail?.messages ?? []).map((m) => (
                <div key={m.message_id} className={m.sender_role === "admin" ? "flex justify-end" : "flex justify-start"}>
                  <div
                    className={
                      m.sender_role === "admin"
                        ? "max-w-[85%] rounded-lg bg-black/90 px-3 py-2 text-sm text-white dark:bg-white/90 dark:text-black"
                        : "max-w-[85%] rounded-lg bg-black/5 px-3 py-2 text-sm dark:bg-white/10"
                    }
                  >
                    <div className="whitespace-pre-wrap break-words">{m.message}</div>
                    <div className="mt-1 text-[10px] opacity-70">
                      {m.sender_role === "admin" ? "admin" : m.sender_username || "user"} • {fmtTime(m.created_at)}
                    </div>
                  </div>
                </div>
              ))}
            </div>
          </div>

          <div className="border-t border-zinc-200/60 p-3 dark:border-zinc-800/60">
            <div className="flex items-start gap-2">
              <textarea
                className="input min-h-[44px] flex-1 resize-none"
                placeholder="Write a reply…"
                value={draft}
                onChange={(e) => setDraft(e.target.value)}
                rows={2}
                disabled={isShowcase || !selectedThreadId || sending}
                onKeyDown={(e) => {
                  if (e.key === "Enter" && !e.shiftKey) {
                    e.preventDefault();
                    void send();
                  }
                }}
              />
              <button type="button" className="btn-primary h-11 px-4" onClick={() => void send()} disabled={isShowcase || !selectedThreadId || sending}>
                {isShowcase ? "Read only" : sending ? "Sending…" : "Send"}
              </button>
            </div>

            <div className="mt-2 flex items-center justify-between gap-3 flex-wrap">
              <label className="flex items-center gap-2 text-xs muted">
                <input type="checkbox" checked={closeOnSend} onChange={(e) => setCloseOnSend(e.target.checked)} disabled={isShowcase} />
                Close thread after sending
              </label>
              <div className="text-[11px] muted">Press Enter to send • Shift+Enter for newline</div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
