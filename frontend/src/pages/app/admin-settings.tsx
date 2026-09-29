import * as React from "react";

import { useAuth } from "@/components/auth-provider";
import { SiteBrandMark } from "@/components/site-brand-mark";
import { apiFetch } from "@/lib/api";
import {
  DEFAULT_SITE_BRANDING,
  emitSiteBrandingUpdated,
  normalizeSiteBranding,
  resolveSiteBrandText,
  resolveSiteFaviconSrc,
  type SiteBranding,
} from "@/lib/site-branding";

type PricingDisplay = {
  currency: string;
  monthly_usd: number;
  yearly_usd: number;
};

type ShowcaseUser = {
  user_id: number;
  username: string;
  role: "showcase";
  is_active: number;
  created_at?: string | null;
  updated_at?: string | null;
  last_login_at?: string | null;
};

function PreviewBrand({ branding }: { branding: SiteBranding }) {
  const showImage = branding.logo_mode === "image" && !!branding.logo_image_src;
  const faviconSrc = resolveSiteFaviconSrc(branding);
  const browserTitle = `Events • ${resolveSiteBrandText(branding)}`;

  return (
    <div className="rounded-2xl border border-zinc-800/60 bg-black/25 p-5">
      <div className="text-xs font-semibold uppercase tracking-[0.18em] muted">
        Live preview
      </div>
      <div className="mt-4 space-y-4 rounded-2xl border border-zinc-800/60 bg-black/35 p-4">
        <div className="rounded-2xl border border-zinc-800/60 bg-zinc-950/90 p-3 shadow-[0_12px_50px_rgba(0,0,0,0.35)]">
          <div className="flex items-center gap-2 rounded-xl border border-zinc-800/60 bg-black/60 px-3 py-2 text-sm text-zinc-300">
            <div className="h-3 w-3 rounded-full bg-red-400/80" />
            <div className="h-3 w-3 rounded-full bg-yellow-400/80" />
            <div className="h-3 w-3 rounded-full bg-emerald-400/80" />
            <div className="ml-2 flex min-w-0 flex-1 items-center gap-2 rounded-lg border border-zinc-800/60 bg-black/60 px-3 py-2">
              <img
                src={faviconSrc}
                alt="Tab icon preview"
                className="h-4 w-4 rounded-sm object-cover"
              />
              <span className="truncate text-sm text-zinc-100">
                {browserTitle}
              </span>
            </div>
          </div>
        </div>

        <div className="rounded-2xl border border-zinc-800/60 bg-black/25 p-4">
          <div className="flex items-center justify-between gap-4 border-b border-zinc-800/60 pb-4">
            <div className="flex items-center gap-3">
              {showImage ? (
                <img
                  src={branding.logo_image_src || undefined}
                  alt={branding.logo_text || "InsidrsAI"}
                  className="h-9 w-auto max-w-[200px] object-contain"
                />
              ) : (
                <div className="bg-gradient-to-r from-purple-400 via-cyan-300 to-blue-300 bg-clip-text text-xl font-semibold tracking-tight text-transparent">
                  {branding.logo_text || "InsidrsAI"}
                </div>
              )}
            </div>
            <div className="rounded-full bg-white/10 px-3 py-2 text-sm text-zinc-300">
              Header logo
            </div>
          </div>

          <div className="mt-4 flex items-center justify-between gap-3 rounded-xl border border-zinc-800/60 bg-black/30 px-3 py-3">
            <div className="flex items-center gap-3">
              <img
                src={faviconSrc}
                alt="Favicon preview"
                className="h-8 w-8 rounded-lg border border-zinc-700/60 object-cover"
              />
              <div>
                <div className="text-sm font-medium text-zinc-100">
                  Browser tab icon
                </div>
                <div className="text-xs muted">
                  Shown in the browser tab and bookmark bar.
                </div>
              </div>
            </div>
            <span className="rounded-full border border-zinc-700/60 bg-white/5 px-3 py-1 text-xs text-zinc-300">
              Favicon
            </span>
          </div>

          <div className="mt-4 flex items-center justify-between gap-3">
            <SiteBrandMark textClassName="text-lg" imageClassName="h-8" />
            <span className="text-sm muted">Current saved branding</span>
          </div>
        </div>
      </div>
    </div>
  );
}

function fmtDateTime(value: string | null | undefined): string {
  if (!value) return "—";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString();
}

function SummaryCard({
  label,
  value,
  helper,
}: {
  label: string;
  value: string;
  helper?: string;
}) {
  return (
    <div className="rounded-2xl border border-zinc-200/70 bg-white/50 p-4 dark:border-zinc-800/60 dark:bg-black/20">
      <div className="text-xs font-semibold uppercase tracking-[0.16em] muted">
        {label}
      </div>
      <div className="mt-2 text-lg font-semibold text-zinc-900 dark:text-zinc-100">
        {value}
      </div>
      {helper ? <div className="mt-1 text-sm muted">{helper}</div> : null}
    </div>
  );
}

async function readFileAsDataUrl(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onerror = () => reject(new Error("Failed to read file"));
    reader.onload = () => resolve(String(reader.result || ""));
    reader.readAsDataURL(file);
  });
}

export function AdminSettingsPage() {
  const { user } = useAuth();
  const isShowcase = user?.role === "showcase";
  const [loading, setLoading] = React.useState(true);
  const [error, setError] = React.useState<string | null>(null);
  const [success, setSuccess] = React.useState<string | null>(null);

  const [savingPricing, setSavingPricing] = React.useState(false);
  const [savingBranding, setSavingBranding] = React.useState(false);
  const [savingShowcase, setSavingShowcase] = React.useState(false);
  const [savingAi, setSavingAi] = React.useState(false);
  const [aiSettings, setAiSettings] = React.useState<{ enabled: boolean; updated_at: string | null } | null>(null);

  const [display, setDisplay] = React.useState<PricingDisplay | null>(null);
  const [plans, setPlans] = React.useState<{
    monthly: string | null;
    yearly: string | null;
  } | null>(null);

  const [monthlyUsd, setMonthlyUsd] = React.useState<string>("");
  const [yearlyUsd, setYearlyUsd] = React.useState<string>("");
  const [currency, setCurrency] = React.useState<string>("USD");

  const [savedBranding, setSavedBranding] = React.useState<SiteBranding>(
    DEFAULT_SITE_BRANDING,
  );
  const [logoMode, setLogoMode] = React.useState<"text" | "image">("text");
  const [logoText, setLogoText] = React.useState("InsidrsAI");
  const [logoImageSrc, setLogoImageSrc] = React.useState("");
  const [faviconImageSrc, setFaviconImageSrc] = React.useState("");
  const [uploadingLogoLabel, setUploadingLogoLabel] = React.useState<
    string | null
  >(null);
  const [uploadingFaviconLabel, setUploadingFaviconLabel] = React.useState<
    string | null
  >(null);

  const [showcaseUser, setShowcaseUser] = React.useState<ShowcaseUser | null>(
    null,
  );
  const [showcaseUsername, setShowcaseUsername] = React.useState("");
  const [showcasePassword, setShowcasePassword] = React.useState("");

  const livePreview = React.useMemo<SiteBranding>(
    () =>
      normalizeSiteBranding({
        logo_mode: logoMode,
        logo_text: logoText,
        logo_image_src: logoImageSrc,
        favicon_image_src: faviconImageSrc,
      }),
    [faviconImageSrc, logoImageSrc, logoMode, logoText],
  );

  const hydrateBranding = React.useCallback((branding: SiteBranding) => {
    const normalized = normalizeSiteBranding(branding);
    setSavedBranding(normalized);
    setLogoMode(normalized.logo_mode);
    setLogoText(normalized.logo_text);
    setLogoImageSrc(normalized.logo_image_src || "");
    setFaviconImageSrc(normalized.favicon_image_src || "");
  }, []);

  const load = React.useCallback(async () => {
    setLoading(true);
    setError(null);
    setSuccess(null);

    try {
      const [dRes, pRes, bRes, sRes, aRes] = await Promise.all([
        apiFetch("/public/pricing-display", { cache: "no-store" }),
        apiFetch("/billing/plans", { cache: "no-store" }),
        apiFetch("/public/site-branding", { cache: "no-store" }),
        apiFetch("/admin/site/showcase-user", { cache: "no-store" }),
        apiFetch("/admin/site/ai-settings", { cache: "no-store" }),
      ]);

      if (!dRes.ok) throw new Error(await dRes.text());
      if (!pRes.ok) throw new Error(await pRes.text());
      if (!bRes.ok) throw new Error(await bRes.text());
      if (!sRes.ok) throw new Error(await sRes.text());
      if (!aRes.ok) throw new Error(await aRes.text());

      const d = (await dRes.json()) as PricingDisplay;
      const p = await pRes.json();
      const b = await bRes.json();
      const s = await sRes.json();
      const a = await aRes.json();
      setAiSettings({ enabled: Boolean(a?.ai_settings?.enabled), updated_at: a?.ai_settings?.updated_at ?? null });

      setDisplay(d);
      setMonthlyUsd(String(d.monthly_usd));
      setYearlyUsd(String(d.yearly_usd));
      setCurrency(d.currency || "USD");
      setPlans({ monthly: p?.monthly ?? null, yearly: p?.yearly ?? null });
      hydrateBranding(b?.branding ?? b);

      const nextShowcase = (s?.showcase_user ?? null) as ShowcaseUser | null;
      setShowcaseUser(nextShowcase);
      setShowcaseUsername(String(nextShowcase?.username || ""));
      setShowcasePassword("");
    } catch (e: any) {
      setError(e?.message || "Failed to load settings");
    } finally {
      setLoading(false);
    }
  }, [hydrateBranding]);

  React.useEffect(() => {
    void load();
  }, [load]);

  async function savePricing() {
    setSavingPricing(true);
    setError(null);
    setSuccess(null);

    try {
      const monthly = parseFloat(monthlyUsd);
      const yearly = parseFloat(yearlyUsd);
      if (!Number.isFinite(monthly) || monthly <= 0)
        throw new Error("Monthly price must be a positive number.");
      if (!Number.isFinite(yearly) || yearly <= 0)
        throw new Error("Yearly price must be a positive number.");

      const res = await apiFetch("/admin/site/pricing-display", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({
          monthly_usd: monthly,
          yearly_usd: yearly,
          currency,
        }),
      });
      if (!res.ok) throw new Error(await res.text());

      const json = await res.json();
      const next = json?.pricing as PricingDisplay | undefined;
      if (next) {
        setDisplay(next);
        setMonthlyUsd(String(next.monthly_usd));
        setYearlyUsd(String(next.yearly_usd));
        setCurrency(next.currency || currency);
      }
      setSuccess("Pricing display saved.");
    } catch (e: any) {
      setError(e?.message || "Failed to save pricing.");
    } finally {
      setSavingPricing(false);
    }
  }

  async function saveBranding() {
    setSavingBranding(true);
    setError(null);
    setSuccess(null);

    try {
      if (!logoText.trim()) throw new Error("Brand text cannot be blank.");
      if (logoMode === "image" && !logoImageSrc.trim()) {
        throw new Error(
          "Choose an image or paste an image URL before saving image mode.",
        );
      }

      const res = await apiFetch("/admin/site/branding", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({
          logo_mode: logoMode,
          logo_text: logoText.trim(),
          logo_image_src: logoImageSrc.trim() || null,
          favicon_image_src: faviconImageSrc.trim() || null,
        }),
      });
      if (!res.ok) throw new Error(await res.text());

      const json = await res.json();
      const branding = normalizeSiteBranding(json?.branding ?? json);
      hydrateBranding(branding);
      emitSiteBrandingUpdated(branding);
      setSuccess("Site branding saved.");
    } catch (e: any) {
      setError(e?.message || "Failed to save branding.");
    } finally {
      setSavingBranding(false);
    }
  }

  async function toggleAi(enabled: boolean) {
    setSavingAi(true);
    setError(null);
    setSuccess(null);
    try {
      const res = await apiFetch("/admin/site/ai-settings", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ enabled }),
      });
      if (!res.ok) throw new Error(await res.text());
      const json = await res.json();
      setAiSettings({ enabled: Boolean(json?.ai_settings?.enabled), updated_at: json?.ai_settings?.updated_at ?? null });
      setSuccess(
        enabled
          ? "Gemini classification enabled. New filings will be rated (and billed) from now on."
          : "Gemini classification paused. New filings are still ingested but won't be rated.",
      );
    } catch (e: any) {
      setError(e?.message || "Failed to update AI settings.");
    } finally {
      setSavingAi(false);
    }
  }

  async function saveShowcaseAccount() {
    setSavingShowcase(true);
    setError(null);
    setSuccess(null);

    try {
      const username = showcaseUsername.trim().toLowerCase();
      if (username.length < 3)
        throw new Error("Showcase login email must be at least 3 characters.");
      if (!showcaseUser && showcasePassword.trim().length < 8) {
        throw new Error(
          "Set a password with at least 8 characters when creating the showcase account.",
        );
      }
      if (showcasePassword.trim() && showcasePassword.trim().length < 8) {
        throw new Error("Showcase password must be at least 8 characters.");
      }

      const res = await apiFetch("/admin/site/showcase-user", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({
          username,
          password: showcasePassword.trim() || null,
        }),
      });
      if (!res.ok) throw new Error(await res.text());

      const json = await res.json();
      const next = (json?.showcase_user ?? null) as ShowcaseUser | null;
      setShowcaseUser(next);
      setShowcaseUsername(String(next?.username || username));
      setShowcasePassword("");
      setSuccess(
        showcaseUser
          ? "Showcase account updated."
          : "Showcase account created.",
      );
    } catch (e: any) {
      const msg = String(e?.message || "");
      if (msg.includes("username_exists")) {
        setError("That login email is already in use.");
      } else if (msg.includes("password_required")) {
        setError("Enter a password to create the showcase account.");
      } else if (msg.includes("password_too_short")) {
        setError("Showcase password must be at least 8 characters.");
      } else if (msg.includes("username_too_short")) {
        setError("Showcase login email must be at least 3 characters.");
      } else {
        setError(msg || "Failed to save showcase account.");
      }
    } finally {
      setSavingShowcase(false);
    }
  }

  async function handleUpload(
    event: React.ChangeEvent<HTMLInputElement>,
    target: "logo" | "favicon",
  ) {
    const file = event.target.files?.[0];
    if (!file) return;

    if (target === "logo") {
      setUploadingLogoLabel(file.name);
    } else {
      setUploadingFaviconLabel(file.name);
    }
    setError(null);

    try {
      const dataUrl = await readFileAsDataUrl(file);
      if (target === "logo") {
        setLogoMode("image");
        setLogoImageSrc(dataUrl);
        setSuccess(
          "Logo loaded into the preview. Save branding to publish it.",
        );
      } else {
        setFaviconImageSrc(dataUrl);
        setSuccess(
          "Tab icon loaded into the preview. Save branding to publish it.",
        );
      }
    } catch (e: any) {
      setError(e?.message || "Failed to load image file.");
    } finally {
      if (target === "logo") {
        setUploadingLogoLabel(null);
      } else {
        setUploadingFaviconLabel(null);
      }
      event.target.value = "";
    }
  }

  const brandingDirty =
    livePreview.logo_mode !== savedBranding.logo_mode ||
    livePreview.logo_text !== savedBranding.logo_text ||
    (livePreview.logo_image_src || "") !==
      (savedBranding.logo_image_src || "") ||
    (livePreview.favicon_image_src || "") !==
      (savedBranding.favicon_image_src || "");

  const faviconStatus = savedBranding.favicon_image_src
    ? "Custom icon"
    : savedBranding.logo_image_src
      ? "Uses logo image"
      : "Default icon";

  return (
    <div className="space-y-6">
      <div className="glass-panel p-6">
        <div className="flex flex-col gap-4 xl:flex-row xl:items-start xl:justify-between">
          <div className="max-w-3xl">
            <div className="text-xs font-semibold uppercase tracking-[0.18em] muted">
              Admin controls
            </div>
            <h1 className="mt-2 text-3xl font-semibold text-zinc-900 dark:text-zinc-100">
              Site settings
            </h1>
            <p className="mt-2 text-sm muted">
              Update customer-facing pricing copy, site branding, browser tab
              icon, and the showcase login without deploying new code.
            </p>
          </div>

          <button
            type="button"
            className="btn-secondary h-10 px-4"
            onClick={() => void load()}
            disabled={loading}
          >
            {loading ? "Reloading…" : "Reload settings"}
          </button>
        </div>

        <div className="mt-6 grid gap-3 sm:grid-cols-2 xl:grid-cols-6">
          <SummaryCard
            label="Display pricing"
            value={
              display ? `${display.currency} ${display.monthly_usd}/mo` : "—"
            }
            helper={
              display
                ? `${display.currency} ${display.yearly_usd}/yr`
                : "Loading…"
            }
          />
          <SummaryCard
            label="Stripe plans"
            value={plans?.monthly ? "Monthly ready" : "Monthly missing"}
            helper={plans?.yearly ? "Yearly ready" : "Yearly missing"}
          />
          <SummaryCard
            label="Brand mode"
            value={
              savedBranding.logo_mode === "image" ? "Image logo" : "Text logo"
            }
            helper={savedBranding.logo_text}
          />
          <SummaryCard
            label="Tab icon"
            value={faviconStatus}
            helper="Displayed in browser tabs and bookmarks"
          />
          <SummaryCard
            label="Brand status"
            value={brandingDirty ? "Unsaved changes" : "Saved"}
            helper={
              brandingDirty
                ? "Preview differs from live"
                : "Header and tab icon are up to date"
            }
          />
          <SummaryCard
            label="Showcase account"
            value={showcaseUser?.username || "Not configured"}
            helper={
              showcaseUser
                ? `Last login ${fmtDateTime(showcaseUser.last_login_at)}`
                : "Create a spectator account for demos"
            }
          />
        </div>
      </div>

      {error ? (
        <div className="rounded-2xl border border-red-500/30 bg-red-500/10 px-4 py-3 text-sm text-red-700 dark:text-red-300">
          {error}
        </div>
      ) : null}
      {success ? (
        <div className="rounded-2xl border border-emerald-500/30 bg-emerald-500/10 px-4 py-3 text-sm text-emerald-700 dark:text-emerald-300">
          {success}
        </div>
      ) : null}

      {isShowcase ? (
        <div className="rounded-2xl border border-cyan-500/30 bg-cyan-500/10 px-4 py-3 text-sm text-cyan-700 dark:text-cyan-300">
          Spectator mode is active. Settings are visible here, but saving
          changes is disabled for the showcase account.
        </div>
      ) : null}

      <div className="glass-panel p-5">
        <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
          <div className="max-w-2xl">
            <div className="flex flex-wrap items-center gap-2">
              <div className="text-sm font-semibold">Gemini AI classification</div>
              {aiSettings ? (
                <span
                  className={
                    aiSettings.enabled
                      ? "rounded-full border border-emerald-500/30 bg-emerald-500/10 px-2.5 py-0.5 text-xs font-medium text-emerald-300"
                      : "rounded-full border border-amber-500/30 bg-amber-500/10 px-2.5 py-0.5 text-xs font-medium text-amber-300"
                  }
                >
                  {aiSettings.enabled ? "On" : "Paused"}
                </span>
              ) : null}
            </div>
            <div className="mt-1 text-xs muted">
              When paused, filings keep flowing in but no Gemini calls are made, and the site shows an
              &quot;AI classification is paused&quot; notice. Filings ingested while paused are not rated
              retroactively when you turn it back on.
              {aiSettings?.updated_at ? ` Last changed ${fmtDateTime(aiSettings.updated_at)}.` : ""}
            </div>
          </div>
          <button
            type="button"
            className={aiSettings?.enabled ? "btn-secondary h-10 px-4" : "btn-primary h-10 px-4"}
            disabled={isShowcase || savingAi || !aiSettings}
            onClick={() => void toggleAi(!aiSettings?.enabled)}
          >
            {savingAi ? "Saving…" : aiSettings?.enabled ? "Pause classification" : "Turn classification on"}
          </button>
        </div>
      </div>

      <div className="grid gap-6 xl:grid-cols-[minmax(0,1fr)_420px]">
        <div className="glass-panel p-5">
          <fieldset
            disabled={isShowcase}
            className="space-y-0 disabled:opacity-70"
          >
            <div className="flex flex-wrap items-end justify-between gap-3">
              <div>
                <div className="text-sm font-semibold">Pricing display</div>
                <div className="mt-1 text-xs muted">
                  Controls the numbers shown on the pricing page. This does not
                  change Stripe billing.
                </div>
              </div>
            </div>

            <div className="mt-4 grid gap-4 md:grid-cols-3">
              <div>
                <label className="block text-sm font-medium text-zinc-900 dark:text-zinc-100">
                  Monthly (USD)
                </label>
                <input
                  className="input mt-1"
                  value={monthlyUsd}
                  onChange={(e) => setMonthlyUsd(e.target.value)}
                  disabled={loading}
                />
                {!plans?.monthly ? (
                  <div className="mt-1 text-xs muted">
                    Stripe monthly plan ID not configured.
                  </div>
                ) : null}
              </div>

              <div>
                <label className="block text-sm font-medium text-zinc-900 dark:text-zinc-100">
                  Yearly (USD)
                </label>
                <input
                  className="input mt-1"
                  value={yearlyUsd}
                  onChange={(e) => setYearlyUsd(e.target.value)}
                  disabled={loading}
                />
                {!plans?.yearly ? (
                  <div className="mt-1 text-xs muted">
                    Stripe yearly plan ID not configured.
                  </div>
                ) : null}
              </div>

              <div>
                <label className="block text-sm font-medium text-zinc-900 dark:text-zinc-100">
                  Currency
                </label>
                <input
                  className="input mt-1"
                  value={currency}
                  onChange={(e) => setCurrency(e.target.value.toUpperCase())}
                  disabled={loading}
                />
                <div className="mt-1 text-xs muted">Usually USD.</div>
              </div>
            </div>

            <div className="mt-4 flex items-center justify-end gap-2">
              <button
                type="button"
                className="btn-primary h-10 px-4"
                onClick={() => void savePricing()}
                disabled={isShowcase || loading || savingPricing}
              >
                {savingPricing ? "Saving…" : "Save pricing"}
              </button>
            </div>
          </fieldset>
        </div>

        <div className="glass-panel p-5">
          <div className="text-sm font-semibold">Current brand</div>
          <div className="mt-1 text-xs muted">
            The header, footer, and browser tab pull from these saved settings
            automatically.
          </div>
          <div className="mt-4 rounded-2xl border border-zinc-800/60 bg-black/25 p-4">
            <div className="flex items-center justify-between gap-4">
              <SiteBrandMark textClassName="text-xl" imageClassName="h-10" />
              <img
                src={resolveSiteFaviconSrc(savedBranding)}
                alt="Current tab icon"
                className="h-10 w-10 rounded-xl border border-zinc-700/60 object-cover"
              />
            </div>
          </div>
        </div>
      </div>

      <div className="grid gap-6 xl:grid-cols-[minmax(0,1fr)_420px]">
        <div className="glass-panel p-5">
          <fieldset
            disabled={isShowcase}
            className="space-y-0 disabled:opacity-70"
          >
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div>
                <div className="text-sm font-semibold">Site branding</div>
                <div className="mt-1 text-xs muted">
                  Choose a text logo or upload an image for the public marketing
                  site, app header, and browser tab.
                </div>
              </div>

              <div className="flex gap-2">
                <button
                  type="button"
                  className="btn-secondary h-10 px-4"
                  onClick={() => hydrateBranding(savedBranding)}
                  disabled={
                    isShowcase || loading || savingBranding || !brandingDirty
                  }
                >
                  Reset preview
                </button>
                <button
                  type="button"
                  className="btn-primary h-10 px-4"
                  onClick={() => void saveBranding()}
                  disabled={isShowcase || loading || savingBranding}
                >
                  {savingBranding ? "Saving…" : "Save branding"}
                </button>
              </div>
            </div>

            <div className="mt-4 grid gap-4 lg:grid-cols-2">
              <div>
                <label className="block text-sm font-medium text-zinc-900 dark:text-zinc-100">
                  Display mode
                </label>
                <select
                  className="input mt-1"
                  value={logoMode}
                  onChange={(e) =>
                    setLogoMode(e.target.value as "text" | "image")
                  }
                  disabled={isShowcase}
                >
                  <option value="text">Text logo</option>
                  <option value="image">Image logo</option>
                </select>
                <div className="mt-1 text-xs muted">
                  Text mode uses the site name in a gradient. Image mode uses
                  your uploaded or linked logo.
                </div>
              </div>

              <div>
                <label className="block text-sm font-medium text-zinc-900 dark:text-zinc-100">
                  Brand text
                </label>
                <input
                  className="input mt-1"
                  value={logoText}
                  onChange={(e) => setLogoText(e.target.value)}
                  disabled={isShowcase}
                />
                <div className="mt-1 text-xs muted">
                  Used for the text logo, alt text, and the browser tab title
                  suffix.
                </div>
              </div>
            </div>

            <div className="mt-4 grid gap-4 lg:grid-cols-[minmax(0,1fr)_220px]">
              <div>
                <label className="block text-sm font-medium text-zinc-900 dark:text-zinc-100">
                  Logo image URL or uploaded data
                </label>
                <textarea
                  className="textarea mt-1 min-h-[110px]"
                  value={logoImageSrc}
                  onChange={(e) => setLogoImageSrc(e.target.value)}
                  placeholder="Paste an https:// image URL or use the upload button below."
                  disabled={isShowcase}
                />
                <div className="mt-1 text-xs muted">
                  PNG, JPG, AVIF, SVG, and uploaded data URLs are supported.
                  Leave blank to use text mode.
                </div>
              </div>

              <div className="rounded-2xl border border-zinc-800/60 bg-black/20 p-4">
                <div className="text-sm font-medium text-zinc-100">
                  Upload logo file
                </div>
                <div className="mt-2 text-xs muted">
                  Convert a local image into an embedded header logo without
                  leaving the dashboard.
                </div>

                <label
                  className={`btn-secondary mt-4 h-10 cursor-pointer px-4 ${isShowcase ? "pointer-events-none opacity-60" : ""}`}
                >
                  Choose file
                  <input
                    type="file"
                    accept="image/*"
                    className="hidden"
                    disabled={isShowcase}
                    onChange={(event) => void handleUpload(event, "logo")}
                  />
                </label>

                <div className="mt-3 text-xs muted">
                  {uploadingLogoLabel
                    ? `Loading ${uploadingLogoLabel}…`
                    : "A saved upload becomes part of the site settings."}
                </div>

                {logoImageSrc ? (
                  <button
                    type="button"
                    className="btn-ghost mt-4 h-9 px-3"
                    onClick={() => setLogoImageSrc("")}
                    disabled={isShowcase}
                  >
                    Clear logo image
                  </button>
                ) : null}
              </div>
            </div>

            <div className="mt-6 grid gap-4 lg:grid-cols-[minmax(0,1fr)_220px]">
              <div>
                <label className="block text-sm font-medium text-zinc-900 dark:text-zinc-100">
                  Browser tab icon URL or uploaded data
                </label>
                <textarea
                  className="textarea mt-1 min-h-[110px]"
                  value={faviconImageSrc}
                  onChange={(e) => setFaviconImageSrc(e.target.value)}
                  placeholder="Paste an https:// image URL or use the upload button below. Leave blank to use the logo image or default icon."
                  disabled={isShowcase}
                />
                <div className="mt-1 text-xs muted">
                  Recommended: a square PNG or AVIF. The tab icon updates across
                  the app as soon as you save.
                </div>
              </div>

              <div className="rounded-2xl border border-zinc-800/60 bg-black/20 p-4">
                <div className="text-sm font-medium text-zinc-100">
                  Upload tab icon
                </div>
                <div className="mt-2 text-xs muted">
                  Use a clean square mark for the browser tab and bookmarks.
                </div>

                <label
                  className={`btn-secondary mt-4 h-10 cursor-pointer px-4 ${isShowcase ? "pointer-events-none opacity-60" : ""}`}
                >
                  Choose file
                  <input
                    type="file"
                    accept="image/*"
                    className="hidden"
                    disabled={isShowcase}
                    onChange={(event) => void handleUpload(event, "favicon")}
                  />
                </label>

                <div className="mt-3 text-xs muted">
                  {uploadingFaviconLabel
                    ? `Loading ${uploadingFaviconLabel}…`
                    : "Square icons usually look best at small sizes."}
                </div>

                {faviconImageSrc ? (
                  <button
                    type="button"
                    className="btn-ghost mt-4 h-9 px-3"
                    onClick={() => setFaviconImageSrc("")}
                    disabled={isShowcase}
                  >
                    Clear tab icon
                  </button>
                ) : null}
              </div>
            </div>
          </fieldset>
        </div>

        <PreviewBrand branding={livePreview} />
      </div>

      <div className="grid gap-6 xl:grid-cols-[minmax(0,1fr)_320px]">
        <div className="glass-panel p-5">
          <fieldset
            disabled={isShowcase}
            className="space-y-0 disabled:opacity-70"
          >
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div>
                <div className="text-sm font-semibold">Showcase account</div>
                <div className="mt-1 text-xs muted">
                  Manage the read-only spectator login you can use for demos,
                  interviews, and portfolio review sessions.
                </div>
              </div>
              <span className="rounded-full border border-cyan-500/30 bg-cyan-500/10 px-3 py-1 text-xs font-medium text-cyan-300">
                Role: showcase
              </span>
            </div>

            <div className="mt-4 grid gap-4 md:grid-cols-2">
              <div>
                <label className="block text-sm font-medium text-zinc-900 dark:text-zinc-100">
                  Showcase login email
                </label>
                <input
                  className="input mt-1"
                  value={showcaseUsername}
                  onChange={(e) => setShowcaseUsername(e.target.value)}
                  placeholder="showcase@yourdomain.com"
                  disabled={isShowcase}
                />
                <div className="mt-1 text-xs muted">
                  This is the username used to sign in to the spectator account.
                </div>
              </div>

              <div>
                <label className="block text-sm font-medium text-zinc-900 dark:text-zinc-100">
                  {showcaseUser ? "New showcase password" : "Showcase password"}
                </label>
                <input
                  type="password"
                  className="input mt-1"
                  value={showcasePassword}
                  onChange={(e) => setShowcasePassword(e.target.value)}
                  placeholder={
                    showcaseUser
                      ? "Leave blank to keep current password"
                      : "Create a password"
                  }
                  disabled={isShowcase}
                />
                <div className="mt-1 text-xs muted">
                  {showcaseUser
                    ? "Leave blank to keep the current password."
                    : "Use at least 8 characters when creating the account."}
                </div>
              </div>
            </div>

            <div className="mt-4 rounded-2xl border border-zinc-800/60 bg-black/20 p-4 text-sm text-zinc-300">
              The showcase account can browse the app and every admin page in
              read-only mode. It cannot remove users, reply to support, change
              pricing or branding, regenerate AI, or view raw admin-only AI
              internals.
            </div>

            <div className="mt-4 flex items-center justify-end gap-2">
              <button
                type="button"
                className="btn-primary h-10 px-4"
                onClick={() => void saveShowcaseAccount()}
                disabled={isShowcase || loading || savingShowcase}
              >
                {savingShowcase
                  ? "Saving…"
                  : showcaseUser
                    ? "Save showcase account"
                    : "Create showcase account"}
              </button>
            </div>
          </fieldset>
        </div>

        <div className="glass-panel p-5">
          <div className="text-sm font-semibold">Showcase status</div>
          <div className="mt-1 text-xs muted">
            Quick reference for the spectator account used to demonstrate the
            product.
          </div>

          <div className="mt-4 space-y-3 rounded-2xl border border-zinc-800/60 bg-black/20 p-4">
            <SummaryCard
              label="Login"
              value={showcaseUser?.username || "Not configured"}
              helper="Editable from this page"
            />
            <SummaryCard
              label="Role"
              value={showcaseUser?.role || "showcase"}
              helper="Read-only admin viewer"
            />
            <SummaryCard
              label="Status"
              value={
                showcaseUser
                  ? Number(showcaseUser.is_active || 0) === 1
                    ? "Active"
                    : "Inactive"
                  : "Missing"
              }
              helper={
                showcaseUser
                  ? `Last login ${fmtDateTime(showcaseUser.last_login_at)}`
                  : "Create the account to enable demos"
              }
            />
          </div>
        </div>
      </div>
    </div>
  );
}
