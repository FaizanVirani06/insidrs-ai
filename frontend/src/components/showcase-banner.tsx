import { Link, useLocation } from "react-router-dom";

import { fmtLongDate, useSiteStatus } from "@/lib/site-status";

export function ShowcaseBanner() {
  const { showcase_mode, market_data_as_of, ai_classification_enabled } = useSiteStatus();
  const location = useLocation();
  const aiPaused = !ai_classification_enabled;
  if (!showcase_mode && !aiPaused) return null;

  const onRecruiters = location.pathname === "/recruiters";

  return (
    <div className="border-b border-cyan-500/20 bg-gradient-to-r from-purple-500/10 via-black/60 to-cyan-500/10 backdrop-blur-xl">
      <div className="container mx-auto flex flex-col gap-1 px-4 py-2 text-xs text-zinc-300 sm:flex-row sm:items-center sm:justify-between sm:gap-4">
        <div>
          {showcase_mode ? (
            <>
              <span className="font-semibold text-cyan-200">Portfolio project.</span> InsidrsAI is no longer taking
              subscribers, and market data is frozen
              {market_data_as_of ? <> as of {fmtLongDate(market_data_as_of)}</> : null}.{" "}
            </>
          ) : null}
          {aiPaused ? (
            <span className="text-amber-200">AI classification is paused due to a temporary halt in development.</span>
          ) : null}
        </div>
        {showcase_mode && !onRecruiters ? (
          <Link to="/recruiters" className="shrink-0 font-semibold text-cyan-300 hover:text-cyan-200">
            Recruiter? Take the 3-minute guided tour →
          </Link>
        ) : null}
      </div>
    </div>
  );
}
