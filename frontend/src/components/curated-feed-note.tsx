import { useAuth } from "@/components/auth-provider";
import { fmtLongDate, useSiteStatus } from "@/lib/site-status";

/** Explains, in showcase mode, why feeds stop at the data freeze. Admins see every filing, so no note. */
export function CuratedFeedNote() {
  const { user } = useAuth();
  const { showcase_mode, market_data_as_of } = useSiteStatus();
  if (!showcase_mode || user?.role === "admin") return null;

  return (
    <div className="mt-3 inline-flex rounded-full border border-cyan-500/30 bg-cyan-500/10 px-3 py-1 text-xs text-cyan-200">
      Showing fully analyzed filings (prices, outcomes, and AI rating)
      {market_data_as_of ? ` through ${fmtLongDate(market_data_as_of)}` : ""}. Lookback windows count back from that
      date.
    </div>
  );
}
