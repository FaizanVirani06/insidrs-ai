import * as React from "react";
import { apiFetch } from "@/lib/api";

export function useEntitlements() {
  const [data, setData] = React.useState<any>(null);
  React.useEffect(() => {
    let c = false;
    apiFetch('/me/entitlements').then(async (r) => {
      if (!r.ok || c) return;
      setData(await r.json());
    }).catch(() => {});
    return () => { c = true; };
  }, []);
  return data;
}
