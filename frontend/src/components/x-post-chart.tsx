import * as React from "react";
import {
  AreaSeries,
  ColorType,
  createChart,
  createSeriesMarkers,
  type Time,
} from "lightweight-charts";

import type { XPostChartPayload } from "@/lib/types";

const IMAGE_WIDTH = 1200;
const IMAGE_HEIGHT = 675;
const CHART_WIDTH = 1104;
const CHART_HEIGHT = 492;

function fmtPrice(value: number): string {
  return `$${value.toLocaleString(undefined, { maximumFractionDigits: 2, minimumFractionDigits: 2 })}`;
}

function fmtReturn(value: number): string {
  const sign = value > 0 ? "+" : "";
  return `${sign}${value.toFixed(2)}%`;
}

function chartData(payload: XPostChartPayload) {
  return payload.dates
    .map((date, idx) => ({ time: date as Time, value: Number(payload.prices[idx]) }))
    .filter((point) => String(point.time) && Number.isFinite(point.value));
}

function composeChartImage(payload: XPostChartPayload, chartCanvas: HTMLCanvasElement): string {
  const canvas = document.createElement("canvas");
  canvas.width = IMAGE_WIDTH;
  canvas.height = IMAGE_HEIGHT;
  const ctx = canvas.getContext("2d");
  if (!ctx) return chartCanvas.toDataURL("image/png");

  const up = payload.return_pct >= 0;
  const accent = up ? "#22c55e" : "#fb7185";
  const ticker = (payload.ticker || "SIGNAL").toUpperCase();

  ctx.fillStyle = "#08090d";
  ctx.fillRect(0, 0, IMAGE_WIDTH, IMAGE_HEIGHT);

  const gradient = ctx.createLinearGradient(0, 0, IMAGE_WIDTH, 0);
  gradient.addColorStop(0, up ? "rgba(34,197,94,0.16)" : "rgba(244,63,94,0.16)");
  gradient.addColorStop(0.62, "rgba(56,189,248,0.08)");
  gradient.addColorStop(1, "rgba(8,9,13,0)");
  ctx.fillStyle = gradient;
  ctx.fillRect(0, 0, IMAGE_WIDTH, IMAGE_HEIGHT);

  ctx.fillStyle = "#f8fafc";
  ctx.font = "700 46px Inter, ui-sans-serif, system-ui, -apple-system, Segoe UI, sans-serif";
  ctx.fillText(`$${ticker} insider signal`, 48, 70);

  ctx.fillStyle = accent;
  ctx.font = "700 44px Inter, ui-sans-serif, system-ui, -apple-system, Segoe UI, sans-serif";
  ctx.textAlign = "right";
  ctx.fillText(fmtReturn(payload.return_pct), IMAGE_WIDTH - 48, 70);
  ctx.textAlign = "left";

  ctx.fillStyle = "#a1a1aa";
  ctx.font = "500 24px Inter, ui-sans-serif, system-ui, -apple-system, Segoe UI, sans-serif";
  ctx.fillText(`Signal ${payload.signal_date} at ${fmtPrice(payload.signal_price)}`, 48, 112);
  ctx.textAlign = "right";
  ctx.fillText(`Latest ${fmtPrice(payload.latest_price)}`, IMAGE_WIDTH - 48, 112);
  ctx.textAlign = "left";

  ctx.strokeStyle = "rgba(255,255,255,0.12)";
  ctx.lineWidth = 2;
  ctx.strokeRect(47, 139, CHART_WIDTH + 2, CHART_HEIGHT + 2);
  ctx.drawImage(chartCanvas, 48, 140, CHART_WIDTH, CHART_HEIGHT);

  ctx.fillStyle = "#71717a";
  ctx.font = "500 18px Inter, ui-sans-serif, system-ui, -apple-system, Segoe UI, sans-serif";
  ctx.fillText("InsidrsAI research signal", 48, IMAGE_HEIGHT - 26);
  ctx.textAlign = "right";
  ctx.fillText("Research only. Not financial advice.", IMAGE_WIDTH - 48, IMAGE_HEIGHT - 26);

  return canvas.toDataURL("image/png");
}

export function XPostChartRenderer({
  payload,
  onImageReady,
}: {
  payload: XPostChartPayload | null;
  onImageReady: (dataUrl: string | null) => void;
}) {
  const elRef = React.useRef<HTMLDivElement | null>(null);

  React.useEffect(() => {
    if (!payload || !elRef.current) {
      onImageReady(null);
      return;
    }

    const data = chartData(payload);
    if (data.length === 0) {
      onImageReady(null);
      return;
    }

    let alive = true;
    const chart = createChart(elRef.current, {
      width: CHART_WIDTH,
      height: CHART_HEIGHT,
      autoSize: false,
      layout: {
        background: { type: ColorType.Solid, color: "#0b0d12" },
        textColor: "#d4d4d8",
        fontSize: 18,
        fontFamily: "Inter, ui-sans-serif, system-ui, -apple-system, Segoe UI, sans-serif",
      },
      grid: {
        vertLines: { color: "rgba(148,163,184,0.14)" },
        horzLines: { color: "rgba(148,163,184,0.14)" },
      },
      rightPriceScale: {
        borderColor: "rgba(148,163,184,0.22)",
        scaleMargins: { top: 0.12, bottom: 0.18 },
      },
      timeScale: {
        borderColor: "rgba(148,163,184,0.22)",
        fixLeftEdge: true,
        fixRightEdge: true,
        timeVisible: false,
      },
      crosshair: {
        vertLine: { visible: false },
        horzLine: { visible: false },
      },
      handleScale: false,
      handleScroll: false,
    });

    const up = payload.return_pct >= 0;
    const lineColor = up ? "#22c55e" : "#fb7185";
    const series = chart.addSeries(AreaSeries, {
      lineColor,
      lineWidth: 4,
      topColor: up ? "rgba(34,197,94,0.28)" : "rgba(244,63,94,0.28)",
      bottomColor: "rgba(8,9,13,0)",
      priceLineVisible: false,
      lastValueVisible: false,
    });
    series.setData(data);
    series.createPriceLine({
      price: Number(payload.signal_price),
      color: "rgba(250,250,250,0.52)",
      lineWidth: 1,
      lineStyle: 2,
      axisLabelVisible: true,
      title: "Signal",
    });
    createSeriesMarkers(series, [
      {
        time: payload.signal_date as Time,
        position: "belowBar",
        color: "#22c55e",
        shape: "arrowUp",
        text: "Signal",
      },
      {
        time: data[data.length - 1].time,
        position: up ? "aboveBar" : "belowBar",
        color: lineColor,
        shape: "circle",
        text: "Now",
      },
    ]);
    chart.timeScale().fitContent();

    const frame = window.requestAnimationFrame(() => {
      window.requestAnimationFrame(() => {
        if (!alive) return;
        const screenshot = chart.takeScreenshot(true);
        onImageReady(composeChartImage(payload, screenshot));
      });
    });

    return () => {
      alive = false;
      window.cancelAnimationFrame(frame);
      chart.remove();
    };
  }, [onImageReady, payload]);

  return (
    <div
      ref={elRef}
      aria-hidden="true"
      className="pointer-events-none fixed top-0 -left-[20000px]"
      style={{ width: CHART_WIDTH, height: CHART_HEIGHT }}
    />
  );
}
