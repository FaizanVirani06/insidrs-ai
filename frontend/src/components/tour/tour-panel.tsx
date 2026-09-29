import * as React from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";

import { useTour } from "@/components/tour/tour-provider";
import { TOUR_STEPS } from "@/components/tour/tour-steps";
import { OWNER } from "@/lib/showcase";

const HIGHLIGHT_CLASS = "tour-target";

function samePath(a: string, b: string): boolean {
  const norm = (p: string) => {
    try {
      return decodeURIComponent(p).replace(/\/+$/, "") || "/";
    } catch {
      return p;
    }
  };
  return norm(a) === norm(b);
}

/** Outline the step's `data-tour` element once it renders (pages load data async) and scroll to it. */
function useHighlight(target: string | undefined, enabled: boolean) {
  React.useEffect(() => {
    if (!enabled || !target) return;
    let el: HTMLElement | null = null;
    let tries = 0;
    const timer = window.setInterval(() => {
      el = document.querySelector<HTMLElement>(`[data-tour="${target}"]`);
      tries += 1;
      if (el) {
        window.clearInterval(timer);
        el.classList.add(HIGHLIGHT_CLASS);
        const tall = el.getBoundingClientRect().height > window.innerHeight * 0.6;
        el.scrollIntoView({ behavior: "smooth", block: tall ? "start" : "center" });
      } else if (tries > 40) {
        window.clearInterval(timer);
      }
    }, 200);
    return () => {
      window.clearInterval(timer);
      el?.classList.remove(HIGHLIGHT_CLASS);
    };
  }, [target, enabled]);
}

export function TourPanel() {
  const tour = useTour();
  const location = useLocation();
  const navigate = useNavigate();

  const step = TOUR_STEPS[tour.step];
  const stepPath = step ? step.path(tour.featured) : "/";
  const onStepPage = samePath(location.pathname, stepPath);
  const isFirst = tour.step === 0;
  const isLast = tour.step === TOUR_STEPS.length - 1;

  useHighlight(step?.target, tour.active && onStepPage);

  const next = React.useCallback(() => {
    if (isLast) tour.end();
    else tour.goTo(tour.step + 1);
  }, [isLast, tour]);

  const back = React.useCallback(() => {
    if (!isFirst) tour.goTo(tour.step - 1);
  }, [isFirst, tour]);

  React.useEffect(() => {
    if (!tour.active || tour.minimized) return;
    const onKey = (e: KeyboardEvent) => {
      const t = e.target as HTMLElement | null;
      if (t && (t.isContentEditable || ["INPUT", "TEXTAREA", "SELECT"].includes(t.tagName))) return;
      if (e.key === "ArrowRight") next();
      else if (e.key === "ArrowLeft") back();
      else if (e.key === "Escape") tour.setMinimized(true);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [tour, next, back]);

  if (!tour.active || !step) return null;

  const progress = ((tour.step + 1) / TOUR_STEPS.length) * 100;

  if (tour.minimized) {
    return (
      <button
        type="button"
        onClick={() => tour.setMinimized(false)}
        className="fixed bottom-4 right-4 z-[70] inline-flex items-center gap-2 rounded-full border border-cyan-500/40 bg-zinc-950/90 px-4 py-2.5 text-sm font-medium text-cyan-100 shadow-2xl shadow-cyan-500/20 backdrop-blur-xl transition hover:border-cyan-400/70"
        aria-label="Resume guided tour"
      >
        <span className="h-2 w-2 animate-pulse rounded-full bg-cyan-400" />
        Guided tour · {tour.step + 1}/{TOUR_STEPS.length}
      </button>
    );
  }

  return (
    <aside
      role="dialog"
      aria-label="Guided tour"
      className="fixed inset-x-3 bottom-3 z-[70] flex max-h-[60vh] flex-col overflow-hidden rounded-2xl border border-cyan-500/30 bg-zinc-950/95 text-zinc-100 shadow-2xl shadow-cyan-500/15 backdrop-blur-xl sm:inset-x-auto sm:bottom-5 sm:right-5 sm:max-h-[calc(100vh-7rem)] sm:w-[400px]"
    >
      <div className="h-1 w-full bg-zinc-800">
        <div className="h-full bg-gradient-to-r from-purple-500 to-cyan-400 transition-all duration-300" style={{ width: `${progress}%` }} />
      </div>

      <div className="flex items-center justify-between gap-3 px-5 pt-4">
        <div className="text-[11px] font-semibold uppercase tracking-[0.18em] text-cyan-300">
          {tour.step + 1} of {TOUR_STEPS.length} · {step.eyebrow}
        </div>
        <div className="flex items-center gap-1">
          <button
            type="button"
            onClick={() => tour.setMinimized(true)}
            className="rounded-md px-2 py-1 text-xs text-zinc-400 transition hover:bg-white/5 hover:text-zinc-100"
            aria-label="Minimize tour"
            title="Minimize (Esc)"
          >
            Hide
          </button>
          <button
            type="button"
            onClick={tour.end}
            className="rounded-md px-2 py-1 text-xs text-zinc-400 transition hover:bg-white/5 hover:text-zinc-100"
            aria-label="Exit tour"
          >
            Exit
          </button>
        </div>
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto px-5 pb-4 pt-2">
        <h2 className="text-lg font-semibold leading-snug text-zinc-50">{step.title}</h2>
        <p className="mt-2 text-sm leading-6 text-zinc-300">{step.body}</p>

        {!onStepPage ? (
          <button
            type="button"
            onClick={() => navigate(stepPath)}
            className="mt-3 inline-flex items-center gap-1 rounded-full border border-amber-500/30 bg-amber-500/10 px-3 py-1 text-xs font-medium text-amber-200 transition hover:bg-amber-500/20"
          >
            You wandered off. Back to this stop →
          </button>
        ) : null}

        {step.details.length > 0 ? (
          <div className="mt-4 rounded-xl border border-zinc-800 bg-black/40 p-3">
            <div className="text-[11px] font-semibold uppercase tracking-[0.16em] text-zinc-500">Under the hood</div>
            <ul className="mt-2 space-y-2 text-[13px] leading-5 text-zinc-300">
              {step.details.map((d) => (
                <li key={d} className="flex gap-2">
                  <span className="mt-[7px] h-1 w-1 shrink-0 rounded-full bg-cyan-400" />
                  <span>{d}</span>
                </li>
              ))}
            </ul>
          </div>
        ) : null}

        {isLast ? (
          <div className="mt-4 flex flex-wrap gap-2">
            <a href={OWNER.repo} target="_blank" rel="noreferrer" className="btn-secondary h-9 px-3 text-xs">
              Source on GitHub
            </a>
            <a href={OWNER.linkedin} target="_blank" rel="noreferrer" className="btn-secondary h-9 px-3 text-xs">
              LinkedIn
            </a>
            <a href={`mailto:${OWNER.email}`} className="btn-secondary h-9 px-3 text-xs">
              Email me
            </a>
          </div>
        ) : null}
      </div>

      <div className="flex items-center justify-between gap-3 border-t border-zinc-800 px-5 py-3">
        <button type="button" onClick={back} disabled={isFirst} className="btn-ghost h-9 px-3">
          ← Back
        </button>
        <div className="hidden text-[11px] text-zinc-500 sm:block">← → to navigate</div>
        {isLast ? (
          <Link to="/app/events" onClick={tour.end} className="btn-primary h-9 px-4">
            Explore on my own
          </Link>
        ) : (
          <button type="button" onClick={next} className="btn-primary h-9 px-4">
            Next →
          </button>
        )}
      </div>
    </aside>
  );
}
