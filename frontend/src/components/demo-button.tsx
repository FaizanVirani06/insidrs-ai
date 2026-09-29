import * as React from "react";
import { useNavigate } from "react-router-dom";

import { useAuth } from "@/components/auth-provider";

/**
 * "Open the demo": signs in as the read-only showcase account if needed, then navigates.
 * Already signed-in users just go straight to `to`.
 */
export function DemoButton({
  to = "/app/events",
  className = "btn-secondary h-11 px-6 text-sm",
  children = "Explore the demo",
}: {
  to?: string;
  className?: string;
  children?: React.ReactNode;
}) {
  const { user, loginAsDemo } = useAuth();
  const navigate = useNavigate();
  const [busy, setBusy] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);

  const open = async () => {
    setError(null);
    if (user) {
      navigate(to);
      return;
    }
    setBusy(true);
    try {
      await loginAsDemo();
      navigate(to);
    } catch (e: any) {
      setError(e?.message || "Could not open the demo.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <span className="inline-flex flex-col">
      <button type="button" onClick={() => void open()} disabled={busy} className={className}>
        {busy ? "Opening…" : children}
      </button>
      {error ? <span className="mt-1 text-xs text-red-300">{error}</span> : null}
    </span>
  );
}
