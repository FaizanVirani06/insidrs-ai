import * as React from "react";

function initials(name: string): string {
  return name
    .split(/\s+/)
    .map((part) => part[0])
    .join("")
    .slice(0, 2)
    .toUpperCase();
}

export function XPostPreview({
  content,
  chartImageDataUrl,
  handle = "InsidrsAI",
  displayName = "InsidrsAI",
}: {
  content: string;
  chartImageDataUrl: string | null;
  handle?: string;
  displayName?: string;
}) {
  const text = (content || "").trim();
  if (!text && !chartImageDataUrl) return null;

  return (
    <div className="w-full max-w-[600px] rounded-2xl border border-zinc-800 bg-black text-white">
      <div className="flex gap-3 p-4">
        <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-white text-sm font-bold text-black">
          {initials(displayName)}
        </div>
        <div className="min-w-0 flex-1">
          <div className="flex min-w-0 items-center gap-1 text-[15px] leading-5">
            <span className="truncate font-bold">{displayName}</span>
            <span className="truncate text-zinc-500">@{handle}</span>
            <span className="text-zinc-500">·</span>
            <span className="text-zinc-500">now</span>
          </div>
          {text ? <div className="mt-1 whitespace-pre-wrap break-words text-[15px] leading-5">{text}</div> : null}
          {chartImageDataUrl ? (
            <div className="mt-3 overflow-hidden rounded-2xl border border-zinc-800 bg-zinc-950">
              <img className="block aspect-video w-full object-cover" src={chartImageDataUrl} alt="Attached signal chart" />
            </div>
          ) : null}
          <div className="mt-3 flex max-w-[420px] justify-between text-zinc-500">
            <span aria-label="Replies">0</span>
            <span aria-label="Reposts">0</span>
            <span aria-label="Likes">0</span>
            <span aria-label="Views">0</span>
          </div>
        </div>
      </div>
    </div>
  );
}
