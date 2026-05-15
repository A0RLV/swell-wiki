# Growth Cloud — augmentation plan on top of llmwiki

WIP. Andrej, this is the read-only thinking + scaffold. Pieces marked `[demo]` are wired for a working demo; `[stub]` is the shape but not the live code; `[next]` is roadmapped.

## What llmwiki gives us for free

- Workspace = folder. `wiki/` (generated markdown) + `sources/` (raw files) + `.llmwiki/index.db` (SQLite + FTS5).
- MCP server with `search` / `read` / `write` / `delete` — Claude curates the wiki itself by reading sources and writing markdown.
- Next.js app renders wiki pages with citations, has a graph viewer, supports highlights, OAuth.
- Git-versioned filesystem-as-truth; SQLite as derived index.

That's most of what Cyril's stack already needs. **One workspace per client** maps cleanly onto Swell's account structure — Target Darts is one workspace, Porsche is another. Data isolation comes for free.

## What it's missing for the Growth Cloud MVP

llmwiki treats every source as opaque text and lets Claude write prose summaries. The Growth Cloud needs **typed entities** extracted on a marketing-ops schema, cross-referenced across calls, queryable by time + person + decision + experiment. Specifically:

1. **Fathom transcript ingestion** — llmwiki handles PDF/MD/HTML/Excel. Fathom calls (transcripts with speakers, timestamps, share URL) need a dedicated converter so each call lands as a structured document with speaker-labeled, timestamped chunks.
2. **AID extraction** — every call should produce a sidecar Atomic Insight Document (AID) of structured entities: decisions, commitments, experiments, stakeholders, workstreams, performance signals, open questions. This is the Claude Sonnet 4.6 + marketing-ops schema pipeline from Cyril.
3. **Entity tables in SQLite** — alongside llmwiki's `documents` / `chunks_fts`, add `people`, `decisions`, `commitments`, `experiments`, `workstreams`, `performance_signals`, plus join tables. Every row cites a `(call_id, t_start_seconds, t_end_seconds)` anchor.
4. **Briefing endpoints** — a query layer that composes answers from entities + transcript citations. Four MVP queries: TLDR, delta-since-date, stakeholder map, onboarding.
5. **State-file recompiler** — when a new transcript lands, regenerate `wiki/overview.md`, `wiki/stakeholders.md`, `wiki/workstreams.md` so the human-readable wiki stays current without manual upkeep. This is KB hygiene.
6. **Briefings UI** — a `/wikis/[slug]/briefings` route with the four query cards; citations chip-link back to `wiki/calls/<id>.md#tNNN` with timestamp anchors.
7. **MCP tools** — expose `briefing`, `delta`, `stakeholders`, `onboarding` over the MCP server so Claude Desktop / Code can ask the same queries.

## Architecture (additive — does not fork llmwiki)

```
Fathom call
     │
     ▼
  [Fathom ingest]  ──▶  sources/calls/<date>-<slug>.md   (speaker-labeled, timestamped)
     │
     ▼
  [AID extractor]  ──▶  wiki/calls/<call-id>.md          (markdown w/ YAML frontmatter, AID body)
     │              ──▶  growth_cloud tables in index.db (people, decisions, …, all with call_id + t_start)
     │
     ▼
  [State compiler] ──▶  wiki/overview.md / stakeholders.md / workstreams.md (recompiled on every new AID)
     │
     ▼
  [Briefings API]  ◀── queries entities + reads transcript spans for citations
     │
     ▼
  Next.js /briefings page  +  MCP tools (briefing/delta/stakeholders/onboarding)
```

The augmentation lives next to llmwiki, not inside it. `shared/growth_cloud_schema.sql` is loaded after llmwiki's schema; `api/routes/briefings.py` mounts as a new router; the Next.js route is one new folder. Easy to upstream as a feature flag later.

## Schema additions

See `shared/growth_cloud_schema.sql`. Highlights:

- `calls(id, date, title, fathom_url, attendees, duration_s, raw_path, …)`
- `transcript_segments(call_id, t_start_s, t_end_s, speaker, content)` — feeds citations and FTS
- `people(id, name, company, role, seniority, authority_score, sentiment_avg, first_seen, last_seen)`
- `decisions / commitments / experiments / workstreams / performance_signals / open_questions` — all with `call_id`, `t_start_s`, `t_end_s`, `confidence`
- `call_people(call_id, person_id, talk_time_pct, sentiment)` — for stakeholder mapping
- FTS5 over `transcript_segments.content` and AID summary fields

Every entity row is traceable to a call timestamp range, which is the citation primitive.

## AID schema (Pydantic — Sonnet 4.6 strict tool output)

See `api/schemas/aid.py`. Roughly:

```
AID
├── call_metadata: { id, date, title, attendees, duration_s }
├── summary: 3-bullet TLDR
├── stakeholders: list[Stakeholder]      # name, company, role, seniority, sentiment, talk_time_pct
├── decisions: list[Decision]            # summary, owner, deadline?, status, t_start_s, t_end_s
├── commitments: list[Commitment]        # owner, what, due?, status, t_start_s, t_end_s
├── experiments: list[Experiment]        # name, hypothesis, status, market?, channel?, t_start_s
├── workstreams: list[Workstream]        # name, status, key_update, t_start_s
├── performance_signals: list[PerfSignal]# market, channel, metric, value, direction, t_start_s
└── open_questions: list[OpenQuestion]   # question, who_to_ask?, t_start_s
```

This is what gets cached as the tool schema in the extractor call.

## The four MVP queries

All share the same primitive: query SQLite for the relevant rows → format a prompt with the entities and a budget of supporting transcript spans → ask Sonnet 4.6 to render the answer with inline `[call_id:t_start_s]` citations → the UI rehydrates citations into chips.

| Query | SQL primitive | What the LLM does |
|---|---|---|
| TLDR (onboarding) | top decisions + open commitments + active experiments + most-active stakeholders, scoped to workspace | 5-bullet summary, each bullet cited |
| Delta since date | same tables filtered by `call_date >= since` | What's new since X, grouped by workstream |
| Stakeholder map | `people` joined to `call_people`, clustered by `(company, seniority)` | Render groups + cite the calls where authority/sentiment was inferred |
| Onboarding ("where do I fit in") | workstreams + open commitments without an owner OR matching the user's role | "Here's what's open in your area, here's who owns the adjacent pieces" |

The prompt for each query is in `prompts/`. They share a system preamble that's prompt-cached (large + stable across queries within a workspace).

## KB hygiene — recompilation on new transcripts

When a new transcript lands and AID extraction completes, `services/state_compiler.py` runs three small Claude calls (Sonnet 4.6, fully cacheable preamble):

1. **Overview merge.** Take the current `wiki/overview.md` + the new AID's summary → emit a new overview. Handle contradictions (newer = wins; older claim → moved to `wiki/decisions/log.md` as superseded).
2. **Stakeholder merge.** Update `wiki/stakeholders.md` with new sentiment / authority / role observations. Same contradiction handling.
3. **Workstream merge.** Rebuild `wiki/workstreams/<name>.md` for any workstream the AID touches.

llmwiki's existing `watcher.py` is the hook. Filesystem stays the source of truth; SQLite is rebuilt from disk via `llmwiki reindex` whenever we want.

## What's out of scope for the demo

- Performance data ingestion (Funnel.io, GA4)
- Growth canvas / strategy doc ingestion
- Test repository
- Client-facing MCP access
- Cross-client pattern recognition (would need vectors; not in scope per Andrej's note)
- Predictive surfacing

## Demo state (one week from kickoff)

What runs end-to-end against the 50 Target Darts calls:

- [demo] Fathom ingest from local JSON exports (real Fathom MCP later)
- [demo] AID extractor with marketing-ops schema, prompt-cached
- [demo] SQLite schema + AID upsert
- [demo] Four briefing endpoints
- [demo] Briefings UI page with the four cards + citation chips
- [stub] State compiler (skeleton + prompts; wired but conservative)
- [stub] MCP tools for briefings (compose calls; the schema is there)
- [next] Real Fathom API ingest (vs JSON exports)
- [next] Per-user onboarding personalization (right now: role string → matched workstreams)

## Repo layout

```
swell-wiki/
├── PLAN.md                                # this file
├── shared/growth_cloud_schema.sql         # SQLite additions
├── api/
│   ├── schemas/aid.py                     # Pydantic AID
│   ├── services/
│   │   ├── fathom_ingest.py              # transcript → sources/calls/*.md + segments
│   │   ├── aid_extractor.py              # Sonnet 4.6 + marketing-ops schema, cached
│   │   ├── briefings.py                  # four query composers
│   │   └── state_compiler.py             # KB hygiene
│   ├── routes/briefings.py               # FastAPI router
│   └── db/growth_cloud.py                # upsert helpers
├── mcp/tools/briefing.py                  # MCP tools (briefing/delta/stakeholders/onboarding)
├── web/src/
│   ├── app/(dashboard)/wikis/[slug]/briefings/page.tsx
│   ├── components/briefings/{BriefingCard,StakeholderMap,Citation}.tsx
│   └── lib/briefings.ts                  # client
├── prompts/{aid_extraction,tldr,delta,stakeholders,onboarding}.md
└── examples/{sample_fathom_transcript.json,sample_aid.json}
```

Drop these into a `lucasastorian/llmwiki` checkout and the paths line up — `shared/sqlite_schema.sql` is appended, `api/routes/` mounts the new router in `api/main.py`, `mcp/tools/` adds another tool registration, `web/src/app/(dashboard)/wikis/[slug]/` gets the new route.
