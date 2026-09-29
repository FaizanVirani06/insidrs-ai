"use client";

import * as React from "react";
import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
  ReferenceLine,
  CartesianGrid,
  Label,
} from "recharts";

import type { PricePoint } from "@/lib/types";

function fmt(v: unknown): string {
  if (typeof v !== "number" || Number.isNaN(v)) return "—";
  return v.toLocaleString(undefined, { maximumFractionDigits: 2, minimumFractionDigits: 2 });
}

function TooltipContent({ active, payload, label }: any) {
  if (!active || !payload || payload.length === 0) return null;
  const p = payload[0]?.value as unknown;
  return (
    <div className="rounded-md border bg-white px-3 py-2 text-xs shadow-sm dark:bg-black">
      <div className="font-medium">{label}</div>
      <div className="mt-1">Adj close: {fmt(p)}</div>
    </div>
  );
}

export function PriceChart({
  data,
  tradeDate,
  filingDate,
}: {
  data: PricePoint[];
  tradeDate?: string | null;
  filingDate?: string | null;
}) {
  if (!data || data.length === 0) {
    return <div className="text-sm text-black/60 dark:text-white/60">No price data.</div>;
  }

  return (
    <div className="h-64 w-full">
      <ResponsiveContainer width="100%" height="100%">
        <LineChart data={data} margin={{ top: 10, right: 10, left: 0, bottom: 0 }}>
          <CartesianGrid strokeDasharray="3 3" strokeOpacity={0.25} />
          <XAxis
            dataKey="date"
            tick={{ fill: "currentColor", fontSize: 11 }}
            tickLine={false}
            axisLine={false}
            minTickGap={28}
          />
          <YAxis
            tick={{ fill: "currentColor", fontSize: 11 }}
            tickLine={false}
            axisLine={false}
            width={56}
            domain={["auto", "auto"]}
          />
          <Tooltip content={<TooltipContent />} />
          {tradeDate && (
            <ReferenceLine x={tradeDate} strokeDasharray="3 3" strokeOpacity={0.75}>
              <Label value="Trade" position="top" fill="currentColor" fontSize={11} />
            </ReferenceLine>
          )}
          {filingDate && (
            <ReferenceLine x={filingDate} strokeDasharray="3 3" strokeOpacity={0.75}>
              <Label value="Filed" position="top" fill="currentColor" fontSize={11} />
            </ReferenceLine>
          )}
          <Line type="monotone" dataKey="adj_close" dot={{ r: 1.5 }} strokeWidth={2.5} />
        </LineChart>
      </ResponsiveContainer>

      <div className="mt-2 flex flex-wrap gap-2 text-xs text-black/50 dark:text-white/50">
        {tradeDate && <span>Trade: {tradeDate}</span>}
        {filingDate && <span>Filing: {filingDate}</span>}
      </div>
    </div>
  );
}
