// Briefings API client — talks to the FastAPI router at /briefings/{workspace}/*.
//
// Drop into `web/src/lib/` alongside llmwiki's existing `api.ts`. The base URL
// resolves from the same `NEXT_PUBLIC_API_URL` llmwiki already uses.

export type Citation = {
  call_id: string;
  t_start_s: number;
  t_end_s: number;
  quote: string;
};

export type Briefing = {
  answer_md: string;
  citations: Citation[];
};

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

async function getJSON<T>(path: string): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, { cache: "no-store" });
  if (!res.ok) throw new Error(`${res.status} ${await res.text()}`);
  return res.json() as Promise<T>;
}

export const briefingsApi = {
  tldr: (workspace: string) =>
    getJSON<Briefing>(`/briefings/${workspace}/tldr`),
  delta: (workspace: string, since: string, person?: string) => {
    const qs = new URLSearchParams({ since });
    if (person) qs.set("person", person);
    return getJSON<Briefing>(`/briefings/${workspace}/delta?${qs}`);
  },
  stakeholders: (workspace: string) =>
    getJSON<Briefing>(`/briefings/${workspace}/stakeholders`),
  onboarding: (workspace: string, role: string) =>
    getJSON<Briefing>(
      `/briefings/${workspace}/onboarding?role=${encodeURIComponent(role)}`,
    ),
};
