"use client";

import Link from "next/link";
import { useState } from "react";

import type { Citation as CitationT } from "@/lib/briefings";

// Renders the `[call_id:t_start]` chips emitted by the briefings composer.
// Hover reveals the quote; click jumps to wiki/calls/<id>.md#tNNN.
export function Citation({
  citation,
  workspaceSlug,
}: {
  citation: CitationT;
  workspaceSlug: string;
}) {
  const [open, setOpen] = useState(false);
  const href = `/wikis/${workspaceSlug}/calls/${citation.call_id}#t${citation.t_start_s}`;
  return (
    <span
      className="relative inline-block"
      onMouseEnter={() => setOpen(true)}
      onMouseLeave={() => setOpen(false)}
    >
      <Link
        href={href}
        className="mx-0.5 inline-flex items-center rounded-md border border-zinc-300 bg-zinc-50 px-1.5 py-0.5 text-[10px] font-medium text-zinc-700 hover:bg-zinc-100"
      >
        {citation.call_id.slice(0, 16)}…@{formatTimestamp(citation.t_start_s)}
      </Link>
      {open && (
        <span className="absolute bottom-full left-0 z-10 mb-1 w-72 rounded-md border border-zinc-200 bg-white p-2 text-xs text-zinc-700 shadow-lg">
          “{citation.quote}”
        </span>
      )}
    </span>
  );
}

function formatTimestamp(seconds: number): string {
  const m = Math.floor(seconds / 60);
  const s = seconds % 60;
  return `${m}:${s.toString().padStart(2, "0")}`;
}
