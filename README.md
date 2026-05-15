# swell-wiki — Growth Cloud augmentation layer for llmwiki

WIP scaffold for the Growth Cloud MVP. Designed to drop into a checkout of
[lucasastorian/llmwiki](https://github.com/lucasastorian/llmwiki) — paths line
up with llmwiki's existing structure so the additions sit alongside the existing
code rather than forking it.

**Start here:** [`PLAN.md`](./PLAN.md) — the strategic + technical plan.

## What's in here

| Path | What it is | State |
|---|---|---|
| `PLAN.md` | Augmentation plan: what llmwiki gives us, what's missing, the architecture | — |
| `shared/growth_cloud_schema.sql` | SQLite additions (calls, people, decisions, commitments, …) | demo |
| `api/schemas/aid.py` | Pydantic AID — Cyril's marketing-ops schema | demo |
| `api/services/fathom_ingest.py` | Fathom JSON → normalized transcript segments + raw markdown | demo |
| `api/services/aid_extractor.py` | Sonnet 4.6 extractor, strict tool mode, prompt-cached | demo |
| `api/services/briefings.py` | Composers for the four MVP queries (TLDR / delta / stakeholders / onboarding) | demo |
| `api/services/state_compiler.py` | KB hygiene — recompiles `overview.md`, `stakeholders.md`, `workstreams/*.md` on new AIDs | stub |
| `api/db/growth_cloud.py` | SQLite repo: AID upsert + briefing queries | demo |
| `api/routes/briefings.py` | FastAPI router for the four queries | demo |
| `mcp/tools/briefing.py` | MCP tools so Claude Desktop / Code can call the same briefings | demo |
| `web/src/app/(dashboard)/wikis/[slug]/briefings/page.tsx` | Briefings UI page with four cards | demo |
| `web/src/components/briefings/*.tsx` | `BriefingCard`, `Citation` — citation chips link to `wiki/calls/<id>.md#tNNN` | demo |
| `prompts/*.md` | System prompts for extractor, briefings, state compiler | demo |
| `examples/sample_*.json` | One realistic Target Darts call + the AID it should produce | — |

## How it fits into llmwiki

```
llmwiki/
├── shared/sqlite_schema.sql           ← llmwiki's
├── shared/growth_cloud_schema.sql     ← added; loaded after the base schema
├── api/
│   ├── schemas/aid.py                 ← added
│   ├── services/{fathom_ingest,aid_extractor,briefings,state_compiler}.py  ← added
│   ├── db/growth_cloud.py             ← added
│   ├── routes/briefings.py            ← added; include_router in main.py
│   └── deps.py                        ← llmwiki's, extend with get_repo / get_anthropic
├── mcp/tools/{search,read,write,delete,briefing}.py  ← briefing.py added
└── web/src/
    ├── app/(dashboard)/wikis/[slug]/briefings/page.tsx  ← added
    ├── components/briefings/*.tsx     ← added
    └── lib/briefings.ts               ← added
```

Two small llmwiki-side edits are needed to wire it up:

1. `api/main.py`: `from .routes import briefings as briefings_routes; app.include_router(briefings_routes.router)`
2. `mcp/local_server.py`: after the existing tools are registered, call `register_briefing(mcp, repo, client, workspace_id)`

That's the full integration surface.

## Demo flow (against Target Darts)

```bash
# 1. Clone llmwiki, copy this scaffold over it, install deps
git clone https://github.com/lucasastorian/llmwiki.git
cp -r swell-wiki/* llmwiki/
cd llmwiki && pip install -r api/requirements.txt

# 2. Init a workspace for Target Darts
./llmwiki init ~/clients/target-darts

# 3. Drop Fathom JSON exports into ~/clients/target-darts/fathom-exports/
# 4. Run the backfill (small script not included here — would iterate
#    fathom_ingest → aid_extractor → growth_cloud upsert → state_compiler)

# 5. Start the app + visit /wikis/target-darts/briefings
./llmwiki serve ~/clients/target-darts
```

## What still needs doing for the demo

- Backfill script tying ingest → extractor → upsert → state recompile (one Python file)
- `api/deps.py` wiring (`get_repo`, `get_anthropic`) — five lines once llmwiki's existing deps are in scope
- Authority score derivation in `growth_cloud.py` (currently defaults to 0; should be a rolling count of decisions owned ÷ calls attended)
- One real Fathom export to validate the extractor against; sample is hand-written

## What's deliberately not here

Per Andrej's note: cross-client patterns (would need vector storage; out of scope), performance data ingestion (Funnel/GA4 → next), test repository (next), client-facing MCP (next). The wiki structure makes all of these additive — they're more tables and more state files, not a rewrite.
