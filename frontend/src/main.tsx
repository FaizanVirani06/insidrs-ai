import React from "react";
import ReactDOM from "react-dom/client";
import { BrowserRouter } from "react-router-dom";

import "@/styles/globals.css";

import { ThemeProvider } from "@/components/theme-provider";
import { AuthProvider } from "@/components/auth-provider";
import { TourProvider } from "@/components/tour/tour-provider";
import { SiteStatusProvider } from "@/lib/site-status";
import { App } from "@/app";

// The product now ships with a single visual mode.
document.documentElement.classList.add("dark");
document.documentElement.style.colorScheme = "dark";

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <ThemeProvider>
      <SiteStatusProvider>
        <BrowserRouter>
          <AuthProvider>
            <TourProvider>
              <App />
            </TourProvider>
          </AuthProvider>
        </BrowserRouter>
      </SiteStatusProvider>
    </ThemeProvider>
  </React.StrictMode>
);
