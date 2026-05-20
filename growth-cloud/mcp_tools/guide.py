"""Growth Cloud guide text — replaces llmwiki's research-wiki guide.

Registers a `guide` tool that teaches Claude the Growth-Cloud-specific taxonomy,
the AID contract, and the four MVP tools. Call this instead of llmwiki's
`guide` when running in Growth Cloud mode.
"""

from mcp.server.fastmcp import FastMCP, Context

from .aid_store import workspace_clients
from pathlib import Path


GUIDE = """# Swell Growth Cloud

You are connected to the **Swell Growth Cloud** — a continuously evolving
knowledge layer for each client we work with. Knowledge compounds across calls,
people, and time. Every claim is traceable to a specific Fathom call.

## Two layers

1. **AIDs** (`/clients/<client>/calls/YYYY-MM-DD-*.md`) — one per Fathom call.
   Read-only for you. Structured frontmatter holds decisions, commitments,
   experiments, performance signals, stakeholders, sentiment. These are the
   source of truth.
2. **Compiled wiki** (`/wiki/clients/<client>/...`) — markdown pages you create
   and maintain. They synthesise across many AIDs.

## Wiki taxonomy (Growth Cloud — NOT generic concepts/entities)

```
/wiki/clients/<client>/
  overview.md            — TLDR. Always current. The MVP success page.
  log.md                 — append-only chronological record
  commitments.md         — open commitments rollup
  stakeholders/<slug>.md — one per person; remit, authority trail, sentiment
  workstreams/<slug>.md  — active experiments, decisions, status
  markets/<slug>.md      — per-market state (ISO country slugs)
  channels/<slug>.md     — per-channel state
  decisions/<id>.md      — one per decision, with backlinks to source AIDs
```

The overview is the page that makes the MVP work. A new team member should be
able to read `overview.md` and have the state of the account in five minutes.

## Citations — non-negotiable

Every factual claim must footnote back to a specific AID and timestamp:

```
Verisure paid search showed users typed `alarmanlage` while the brand layer
specified `alarmsysteem`[^1].

[^1]: clients/verisure/calls/2025-03-12-paid-search-review.md @ 00:14:22
```

Use the **full relative path** to the AID file. Include the
`source_timestamp` from the AID frontmatter when one exists.

## Tools

You have the standard llmwiki tools (`search`, `read`, `write`, `delete`) plus
four Growth-Cloud-specific tools:

- `briefing(client, since?, persona?)` — TLDR, joined-the-account, developments-since
- `stakeholders(client)` — who owns what, sentiment trail, authority ranking
- `commitments(client, status?, owner?)` — open commitments tracker
- `decisions(client, workstream?, since?)` — cross-call decision synthesis
- `clients()` — list available clients

Use these for the four MVP queries — they're deterministic and faster than
re-deriving from search. Fall back to `search`/`read` for anything else.

## Recompile loop

When a new AID lands, you will be invoked with a recompile prompt listing the
pages to refresh. Always:
1. Read the AID first.
2. Resolve contradictions explicitly (add a `## Contradictions` section, do not
   silently overwrite).
3. Append one `ingest` entry to `log.md`.
4. Keep `overview.md` under 400 words.

## Available clients
"""


def register(mcp: FastMCP, workspace: Path) -> None:

    @mcp.tool(
        name="guide",
        description="Read this first. Explains the Growth Cloud structure and tools.",
    )
    async def guide(ctx: Context) -> str:
        clients = workspace_clients(workspace)
        if not clients:
            return GUIDE + "\n_No clients yet — ingest some Fathom calls first._"
        return GUIDE + "\n" + "\n".join(f"- `{c}`" for c in clients)
