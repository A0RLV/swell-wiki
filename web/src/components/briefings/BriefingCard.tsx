"use client";

import { useState } from "react";

import type { Briefing } from "@/lib/briefings";
import { Citation } from "./Citation";

type Props = {
  title: string;
  description: string;
  loader: () => Promise<Briefing>;
  workspaceSlug: string;
  controls?: React.ReactNode;
};

export function BriefingCard({ title, description, loader, workspaceSlug, controls }: Props) {
  const [state, setState] = useState<
    { kind: "idle" } | { kind: "loading" } | { kind: "ok"; data: Briefing } | { kind: "err"; msg: string }
  >({ kind: "idle" });

  async function run() {
    setState({ kind: "loading" });
    try {
      const data = await loader();
      setState({ kind: "ok", data });
    } catch (e) {
      setState({ kind: "err", msg: e instanceof Error ? e.message : String(e) });
    }
  }

  return (
    <section className="rounded-xl border border-zinc-200 bg-white p-5">
      <header className="mb-3 flex items-start justify-between gap-4">
        <div>
          <h2 className="text-base font-semibold text-zinc-900">{title}</h2>
          <p className="text-sm text-zinc-500">{description}</p>
        </div>
        <button
          onClick={run}
          disabled={state.kind === "loading"}
          className="rounded-md bg-zinc-900 px-3 py-1.5 text-sm font-medium text-white hover:bg-zinc-700 disabled:opacity-50"
        >
          {state.kind === "loading" ? "Composing…" : "Run"}
        </button>
      </header>

      {controls && <div className="mb-3">{controls}</div>}

      {state.kind === "err" && (
        <div className="rounded-md border border-rose-200 bg-rose-50 p-3 text-sm text-rose-900">
          {state.msg}
        </div>
      )}

      {state.kind === "ok" && (
        <div className="space-y-3 text-sm text-zinc-800">
          {renderAnswer(state.data, workspaceSlug)}
        </div>
      )}
    </section>
  );
}

// Render the markdown answer with `[call_id:t_start]` chips swapped out for <Citation> components.
// Kept deliberately simple: split on chip pattern, drop the chips into the right places.
function renderAnswer(briefing: Briefing, workspaceSlug: string) {
  const chipRe = /\[([a-z0-9\-]+):(\d+)\]/g;
  const byKey = new Map(
    briefing.citations.map((c) => [`${c.call_id}:${c.t_start_s}`, c]),
  );

  const lines = briefing.answer_md.split("\n");
  return lines.map((line, lineIdx) => {
    const parts: React.ReactNode[] = [];
    let cursor = 0;
    let m: RegExpExecArray | null;
    chipRe.lastIndex = 0;
    while ((m = chipRe.exec(line))) {
      if (m.index > cursor) parts.push(line.slice(cursor, m.index));
      const key = `${m[1]}:${m[2]}`;
      const cite = byKey.get(key);
      if (cite) {
        parts.push(
          <Citation key={`${lineIdx}-${m.index}`} citation={cite} workspaceSlug={workspaceSlug} />,
        );
      } else {
        parts.push(<span key={`${lineIdx}-${m.index}`} className="text-zinc-400">[{key}]</span>);
      }
      cursor = m.index + m[0].length;
    }
    if (cursor < line.length) parts.push(line.slice(cursor));
    return (
      <p key={lineIdx} className="whitespace-pre-wrap leading-relaxed">
        {parts.length ? parts : line || " "}
      </p>
    );
  });
}
