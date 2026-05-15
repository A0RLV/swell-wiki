"use client";

import { use, useState } from "react";

import { briefingsApi } from "@/lib/briefings";
import { BriefingCard } from "@/components/briefings/BriefingCard";

// Drops in at /wikis/[slug]/briefings — appears next to llmwiki's existing
// per-wiki routes. The `[slug]` is the workspace identifier.

export default function BriefingsPage({
  params,
}: {
  params: Promise<{ slug: string }>;
}) {
  const { slug } = use(params);

  const [since, setSince] = useState(() => {
    const d = new Date();
    d.setDate(d.getDate() - 14);
    return d.toISOString().slice(0, 10);
  });
  const [personFilter, setPersonFilter] = useState("");
  const [role, setRole] = useState("");

  return (
    <main className="mx-auto max-w-4xl space-y-4 p-6">
      <header className="space-y-1">
        <h1 className="text-2xl font-semibold text-zinc-900">Briefings</h1>
        <p className="text-sm text-zinc-500">
          Sourced answers about <span className="font-medium">{slug}</span>. Every chip links to a transcript moment.
        </p>
      </header>

      <BriefingCard
        title="TL;DR — state of the account"
        description="5-bullet readout of the most consequential open work, citation-chipped."
        workspaceSlug={slug}
        loader={() => briefingsApi.tldr(slug)}
      />

      <BriefingCard
        title="What's new since…"
        description="Developments since a date, grouped by workstream. Optionally narrow to one person."
        workspaceSlug={slug}
        controls={
          <div className="flex gap-2 text-sm">
            <input
              type="date"
              value={since}
              onChange={(e) => setSince(e.target.value)}
              className="rounded-md border border-zinc-300 px-2 py-1"
            />
            <input
              placeholder="Person (optional)"
              value={personFilter}
              onChange={(e) => setPersonFilter(e.target.value)}
              className="flex-1 rounded-md border border-zinc-300 px-2 py-1"
            />
          </div>
        }
        loader={() => briefingsApi.delta(slug, since, personFilter || undefined)}
      />

      <BriefingCard
        title="Stakeholder map"
        description="Who's calling the shots on what — grouped by company, ordered by seniority."
        workspaceSlug={slug}
        loader={() => briefingsApi.stakeholders(slug)}
      />

      <BriefingCard
        title="Onboarding — where do I fit in?"
        description="Active workstreams, open items, and adjacent owners for your role."
        workspaceSlug={slug}
        controls={
          <input
            placeholder='Your role (e.g. "paid search lead")'
            value={role}
            onChange={(e) => setRole(e.target.value)}
            className="w-full rounded-md border border-zinc-300 px-2 py-1 text-sm"
          />
        }
        loader={() =>
          briefingsApi.onboarding(slug, role || "operator")
        }
      />
    </main>
  );
}
