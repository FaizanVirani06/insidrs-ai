import { Navigate, Route, Routes } from "react-router-dom";

import { RequireAdminViewer, RequireAuth, RequireSubscription } from "@/components/route-guards";

import { RootLayout } from "@/pages/root-layout";
import { HomePage } from "@/pages/home";
import { PricingPage } from "@/pages/pricing";
import { RecruitersPage } from "@/pages/recruiters";
import { LegalPage } from "@/pages/legal";
import { PrivacyPage } from "@/pages/privacy";
import { TermsPage } from "@/pages/terms";
import { LoginPage } from "@/pages/login";
import { SignupPage } from "@/pages/signup";

import { AppShell } from "@/pages/app/app-shell";
import { AccountPage } from "@/pages/app/account";
import { AdminFeedbackPage } from "@/pages/app/admin-feedback";
import { AdminJobsPage } from "@/pages/app/admin-jobs";
import { AdminMonitoringPage } from "@/pages/app/admin-monitoring";
import { AdminSettingsPage } from "@/pages/app/admin-settings";
import { AdminSupportPage } from "@/pages/app/admin-support";
import { EventDetailPage } from "@/pages/app/event-detail";
import { EventsPage } from "@/pages/app/events";
import { FeedbackPage } from "@/pages/app/feedback";
import { ProfilePage } from "@/pages/app/profile";
import { RecommendationsPage } from "@/pages/app/recommendations";
import { TickerDetailPage } from "@/pages/app/ticker-detail";
import { TickersPage } from "@/pages/app/tickers";
import { AdminSocialPage } from "@/pages/app/admin-social";
import { AdminUsersPage } from "@/pages/admin/users";

function NotFound() {
  return (
    <div className="py-20 text-center">
      <div className="text-2xl font-semibold">404</div>
      <div className="mt-2 text-sm muted">Page not found.</div>
    </div>
  );
}

export function App() {
  return (
    <Routes>
      <Route element={<RootLayout />}>
        <Route index element={<HomePage />} />
        <Route path="pricing" element={<PricingPage />} />
        <Route path="recruiters" element={<RecruitersPage />} />
        <Route path="recruiter" element={<Navigate to="/recruiters" replace />} />
        <Route path="tour" element={<Navigate to="/recruiters" replace />} />
        <Route path="legal" element={<LegalPage />} />
        <Route path="privacy" element={<PrivacyPage />} />
        <Route path="terms" element={<TermsPage />} />
        <Route path="login" element={<LoginPage />} />
        <Route path="signup" element={<SignupPage />} />

        <Route
          path="app"
          element={
            <RequireAuth>
              <AppShell />
            </RequireAuth>
          }
        >
          <Route index element={<Navigate to="for-you" replace />} />
          <Route path="profile" element={<ProfilePage />} />
          <Route path="account" element={<AccountPage />} />

          {/* Subscription-gated routes */}
          <Route element={<RequireSubscription />}>
            <Route path="for-you" element={<RecommendationsPage />} />
            <Route path="recommendations" element={<Navigate to="/app/for-you" replace />} />
            <Route path="tickers" element={<TickersPage />} />
            <Route path="ticker/:ticker" element={<TickerDetailPage />} />
            <Route path="events" element={<EventsPage />} />
            <Route path="event/:issuer_cik/:owner_key/:accession_number" element={<EventDetailPage />} />
            <Route path="feedback" element={<FeedbackPage />} />
          </Route>

          {/* Admin routes */}
          <Route element={<RequireAdminViewer />}>
            <Route path="admin/users" element={<AdminUsersPage />} />
            <Route path="admin/monitoring" element={<AdminMonitoringPage />} />
            <Route path="admin/jobs" element={<AdminJobsPage />} />
            <Route path="admin/feedback" element={<AdminFeedbackPage />} />
            <Route path="admin/support" element={<AdminSupportPage />} />
            <Route path="admin/settings" element={<AdminSettingsPage />} />
            <Route path="admin/social" element={<AdminSocialPage />} />
          </Route>
        </Route>

        <Route path="*" element={<NotFound />} />
      </Route>
    </Routes>
  );
}
