import * as React from "react";
import { Link, useNavigate } from "react-router-dom";

import { DemoButton } from "@/components/demo-button";
import { apiFetch } from "@/lib/api";
import { useSiteStatus } from "@/lib/site-status";

type PricingDisplay = {
  currency: string;
  monthly_usd: number;
  yearly_usd: number;
};

type BillingPlansResponse = {
  monthly?: string | null;
  yearly?: string | null;
  enabled?: boolean;
  monthly_trial_days?: number;
  monthly_trial_available?: boolean;
};

type CheckoutPlan = "monthly" | "yearly" | "trial";

export function PricingPage() {
  const navigate = useNavigate();
  const { showcase_mode: showcase } = useSiteStatus();

  const [loadingPlan, setLoadingPlan] = React.useState<CheckoutPlan | null>(null);
  const [error, setError] = React.useState<string | null>(null);
  const [billingCadence, setBillingCadence] = React.useState<"monthly" | "yearly">("yearly");

  const [billingPlans, setBillingPlans] = React.useState<BillingPlansResponse | null>(null);
  const [display, setDisplay] = React.useState<PricingDisplay | null>(null);

  React.useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const [plansRes, displayRes] = await Promise.all([
          apiFetch("/billing/plans", { cache: "no-store" }),
          apiFetch("/public/pricing-display", { cache: "no-store" }),
        ]);

        if (cancelled) return;

        if (plansRes.ok) {
          const p = await plansRes.json();
          setBillingPlans({
            monthly: p?.monthly ?? null,
            yearly: p?.yearly ?? null,
            enabled: Boolean(p?.enabled),
            monthly_trial_days:
              typeof p?.monthly_trial_days === "number" ? Math.max(0, p.monthly_trial_days) : 0,
            monthly_trial_available: Boolean(p?.monthly_trial_available),
          });
        }
        if (displayRes.ok) {
          const d = (await displayRes.json()) as PricingDisplay;
          setDisplay(d);
        }
      } catch {
        // Non-fatal; page has fallbacks.
      }
    })();

    return () => {
      cancelled = true;
    };
  }, []);

  const currency = display?.currency || "USD";
  const monthlyUsd = typeof display?.monthly_usd === "number" ? display!.monthly_usd : 25;
  const yearlyUsd = typeof display?.yearly_usd === "number" ? display!.yearly_usd : 200;
  const billingEnabled = Boolean(billingPlans?.enabled);
  const monthlyAvailable = Boolean(billingEnabled && billingPlans?.monthly);
  const yearlyAvailable = Boolean(billingEnabled && billingPlans?.yearly);
  const trialDays = Math.max(0, Number(billingPlans?.monthly_trial_days ?? 0));
  const trialAvailable = Boolean(monthlyAvailable && billingPlans?.monthly_trial_available && trialDays > 0);

  const features = [
    "AI-rated Form 4 buy/sell signals",
    "Latest filings feed + filters",
    "Cluster detection",
    "Price charts + measured outcomes",
    "Insider performance stats",
    "Technical trade plan (stop, trims, take-profit)",
    "In-app support chat",
  ];

  const start = async (plan: CheckoutPlan) => {
    setLoadingPlan(plan);
    setError(null);
    try {
      const res = await apiFetch("/billing/checkout-session", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ plan }),
      });

      if (res.status === 401) {
        navigate("/signup?next=/pricing", { replace: true });
        return;
      }

      if (!res.ok) {
        const t = await res.text().catch(() => "Failed to start checkout");
        throw new Error(t || "Failed to start checkout");
      }

      const data = (await res.json()) as any;
      if (data?.url) {
        window.location.href = String(data.url);
        return;
      }
      throw new Error("Missing checkout URL");
    } catch (e: any) {
      setError(e?.message || "Failed to start checkout");
    } finally {
      setLoadingPlan(null);
    }
  };

  const activePrice = billingCadence === "monthly" ? monthlyUsd : yearlyUsd;
  const activeAvailable = billingCadence === "monthly" ? monthlyAvailable : yearlyAvailable;
  const formatPrice = (amount: number) => (currency === "USD" ? `$${amount.toLocaleString()}` : `${amount.toLocaleString()} ${currency}`);

  return (
    <div className="mx-auto max-w-5xl space-y-10">
      {showcase ? (
        <div className="rounded-2xl border border-cyan-500/30 bg-cyan-500/10 p-6">
          <div className="text-lg font-semibold text-zinc-50">Subscriptions are closed</div>
          <p className="mt-2 text-sm leading-6 text-zinc-300">
            InsidrsAI is a portfolio project now, so the whole app is free to explore with the read-only demo account.
            This page stays up to show the Stripe integration: Checkout for monthly and yearly plans, a 7-day free
            trial, the Customer Portal, and signed webhooks that keep subscription state in sync.
          </p>
          <div className="mt-4 flex flex-wrap gap-3">
            <DemoButton className="btn-primary h-10 px-5">Open the demo</DemoButton>
            <Link to="/recruiters" className="btn-secondary h-10 px-5">
              Recruiter tour
            </Link>
          </div>
        </div>
      ) : null}

      <div className="text-center">
        <div className="badge">Simple pricing</div>
        <h1 className="mt-5 text-4xl font-bold tracking-tight">Unlock the dashboard and AI insights</h1>
        <p className="mt-4 text-lg muted">Choose monthly, yearly, or start with a free trial. Cancel anytime.</p>
      </div>

      <div data-tour="pricing-card" className="glass-panel relative overflow-hidden p-8 sm:p-10">
        <div className="pointer-events-none absolute inset-0 bg-gradient-to-r from-purple-500/10 via-transparent to-cyan-500/10" />

        <div className="relative grid gap-8 md:grid-cols-2 md:items-start">
          <div>
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div className="text-sm font-semibold">InsidrsAI Pro</div>
              {billingCadence === "yearly" && <span className="badge">Best value</span>}
            </div>

            <div className="mt-4 inline-flex rounded-lg border border-zinc-200/70 bg-white/50 p-1 dark:border-zinc-800/60 dark:bg-black/30">
              <button
                type="button"
                onClick={() => setBillingCadence("monthly")}
                className={billingCadence === "monthly" ? "btn-secondary h-9 px-4" : "btn-ghost h-9 px-4"}
              >
                Monthly
              </button>
              <button
                type="button"
                onClick={() => setBillingCadence("yearly")}
                className={billingCadence === "yearly" ? "btn-secondary h-9 px-4" : "btn-ghost h-9 px-4"}
              >
                Yearly
              </button>
            </div>

            <div className="mt-4 flex items-baseline gap-2">
              <span className="text-4xl font-bold">{formatPrice(activePrice)}</span>
              <span className="text-sm muted">/ {billingCadence === "monthly" ? "month" : "year"}</span>
            </div>
            {currency !== "USD" && <div className="mt-2 text-xs muted">Currency: {currency}</div>}
            <div className="mt-3 text-sm muted">Secure checkout + subscription management via Stripe.</div>

            <button
              type="button"
              onClick={() => start(billingCadence)}
              disabled={loadingPlan !== null || !activeAvailable}
              className="btn-primary mt-6 w-full"
              title={!activeAvailable ? "This plan is not configured" : undefined}
            >
              {loadingPlan === billingCadence
                ? "Redirecting…"
                : showcase
                  ? "Subscriptions closed"
                  : activeAvailable
                  ? billingCadence === "monthly" && trialAvailable
                    ? "Subscribe monthly now"
                    : "Subscribe"
                  : "Plan unavailable"}
            </button>

            {trialAvailable && (
              <div className="mt-5 rounded-2xl border border-emerald-500/30 bg-emerald-500/10 p-4">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <div className="text-sm font-semibold text-zinc-900 dark:text-zinc-100">7-day free trial</div>
                  <span className="badge">New</span>
                </div>
                <p className="mt-2 text-sm muted">
                  Get full access free for {trialDays} days. After the trial, billing continues at {formatPrice(monthlyUsd)}/month unless you cancel first.
                </p>
                <button
                  type="button"
                  onClick={() => start("trial")}
                  disabled={loadingPlan !== null}
                  className="btn-secondary mt-4 w-full"
                >
                  {loadingPlan === "trial" ? `Redirecting…` : `Start ${trialDays}-day free trial`}
                </button>
                <div className="mt-2 text-xs muted">The trial rolls into the monthly plan automatically after the free period.</div>
              </div>
            )}

            <div className="mt-3 text-xs muted">
              Already have an account?{" "}
              <Link className="link" to="/login">
                Log in
              </Link>
            </div>

            {error && (
              <div className="mt-4 rounded-md border border-red-500/30 bg-red-500/10 px-3 py-2 text-sm text-red-700 dark:text-red-300">
                {error}
              </div>
            )}
          </div>

          <div className="glass-card p-6">
            <div className="text-sm font-semibold">What’s included</div>
            <ul className="mt-4 space-y-2 text-sm muted">
              {features.map((f) => (
                <li key={f} className="flex items-start gap-2">
                  <span className="mt-0.5">✓</span>
                  <span>{f}</span>
                </li>
              ))}
            </ul>

            <div className="mt-6 text-xs muted">
              By subscribing you agree to our{" "}
              <Link to="/legal" className="link">
                Privacy + Terms
              </Link>
              .
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
