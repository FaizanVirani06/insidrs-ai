import * as React from "react";
import { useNavigate } from "react-router-dom";

import { useAuth } from "@/components/auth-provider";
import { TOUR_STEPS, type TourFeatured } from "@/components/tour/tour-steps";
import { apiFetch } from "@/lib/api";

type TourState = {
  active: boolean;
  step: number;
  minimized: boolean;
  featured: TourFeatured;
};

type TourContextValue = TourState & {
  starting: boolean;
  error: string | null;
  start: (step?: number) => Promise<void>;
  goTo: (step: number) => void;
  setMinimized: (minimized: boolean) => void;
  end: () => void;
};

const STORAGE_KEY = "insidrs.tour.v1";
const EMPTY_FEATURED: TourFeatured = { eventPath: null, ticker: null };
const INITIAL_STATE: TourState = { active: false, step: 0, minimized: false, featured: EMPTY_FEATURED };

function readStoredState(): TourState {
  try {
    const raw = window.sessionStorage.getItem(STORAGE_KEY);
    if (!raw) return INITIAL_STATE;
    const parsed = JSON.parse(raw);
    const step = Number(parsed?.step);
    return {
      active: Boolean(parsed?.active),
      step: Number.isInteger(step) ? Math.max(0, Math.min(TOUR_STEPS.length - 1, step)) : 0,
      minimized: Boolean(parsed?.minimized),
      featured: {
        eventPath: typeof parsed?.featured?.eventPath === "string" ? parsed.featured.eventPath : null,
        ticker: typeof parsed?.featured?.ticker === "string" ? parsed.featured.ticker : null,
      },
    };
  } catch {
    return INITIAL_STATE;
  }
}

/** Pick a leaderboard row with a real AI rating (ideally a buy) to use as the tour's example signal. */
async function loadFeaturedSignal(): Promise<TourFeatured> {
  try {
    const res = await apiFetch("/public/signals/best-performing?days=60&limit=20");
    if (!res.ok) return EMPTY_FEATURED;
    const data = await res.json();
    const rows: any[] = Array.isArray(data?.results) ? data.results : [];
    const rated = (row: any) => Number(row?.signal_score) > 0;
    const pick =
      rows.find((row) => rated(row) && row?.transaction_code === "P") ?? rows.find(rated) ?? rows[0] ?? null;
    if (!pick?.issuer_cik || !pick?.owner_key || !pick?.accession_number) return EMPTY_FEATURED;
    return {
      eventPath: `/app/event/${encodeURIComponent(pick.issuer_cik)}/${encodeURIComponent(pick.owner_key)}/${encodeURIComponent(pick.accession_number)}`,
      ticker: pick.ticker ? String(pick.ticker).toUpperCase() : null,
    };
  } catch {
    return EMPTY_FEATURED;
  }
}

const TourContext = React.createContext<TourContextValue | null>(null);

export function TourProvider({ children }: { children: React.ReactNode }) {
  const navigate = useNavigate();
  const { user, loginAsDemo } = useAuth();

  const [state, setState] = React.useState<TourState>(readStoredState);
  const [starting, setStarting] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);

  React.useEffect(() => {
    try {
      window.sessionStorage.setItem(STORAGE_KEY, JSON.stringify(state));
    } catch {
      // Private mode / blocked storage: the tour still works, it just won't survive a reload.
    }
  }, [state]);

  const goTo = React.useCallback(
    (index: number) => {
      const step = Math.max(0, Math.min(TOUR_STEPS.length - 1, index));
      setState((prev) => ({ ...prev, active: true, step, minimized: false }));
      navigate(TOUR_STEPS[step].path(state.featured));
    },
    [navigate, state.featured]
  );

  const start = React.useCallback(
    async (index = 0) => {
      setStarting(true);
      setError(null);
      try {
        // Admin pages are part of the tour, so regular accounts switch to the read-only demo.
        const canSeeEverything = user?.role === "admin" || user?.role === "showcase";
        if (!canSeeEverything) await loginAsDemo();

        const featured = await loadFeaturedSignal();
        const step = Math.max(0, Math.min(TOUR_STEPS.length - 1, index));
        setState({ active: true, step, minimized: false, featured });
        navigate(TOUR_STEPS[step].path(featured));
      } catch (e: any) {
        setError(e?.message || "Could not start the tour.");
      } finally {
        setStarting(false);
      }
    },
    [loginAsDemo, navigate, user?.role]
  );

  // Logging out mid-tour ends it; otherwise the next stop would bounce to the login page.
  const hadUserRef = React.useRef(Boolean(user));
  React.useEffect(() => {
    if (hadUserRef.current && !user) {
      setState((prev) => (prev.active ? { ...prev, active: false, minimized: false } : prev));
    }
    hadUserRef.current = Boolean(user);
  }, [user]);

  const setMinimized = React.useCallback((minimized: boolean) => {
    setState((prev) => ({ ...prev, minimized }));
  }, []);

  const end = React.useCallback(() => {
    setState((prev) => ({ ...prev, active: false, minimized: false }));
  }, []);

  const value = React.useMemo<TourContextValue>(
    () => ({ ...state, starting, error, start, goTo, setMinimized, end }),
    [state, starting, error, start, goTo, setMinimized, end]
  );

  return <TourContext.Provider value={value}>{children}</TourContext.Provider>;
}

export function useTour(): TourContextValue {
  const ctx = React.useContext(TourContext);
  if (!ctx) throw new Error("useTour must be used within <TourProvider>");
  return ctx;
}
