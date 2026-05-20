# Swell Growth Cloud

Auto-ingests Fathom call transcripts, extracts structured data into AID documents and compounds a per-client wiki via Claude over MCP. Built on [llmwiki](./llmwiki/).

## Setup

```bash
# Install
pip install -e './growth-cloud[dev]'

# Init workspace
./growth-cloud/growth-cloud init ~/my-workspace

# Add to Claude Desktop (copy output into claude_desktop_config.json)
./growth-cloud/growth-cloud mcp-config ~/my-workspace

# Ingest calls
./growth-cloud/growth-cloud ingest ~/my-workspace --once

# Run tests
make test -C growth-cloud
```

### MCP Tools

Inherits from llmwiki: `create`, `edit`, `append`, `delete`, `read`, `search`.

Adds:

| Tool | Purpose |
|------|---------|
| `guide` | Growth Cloud doctrine (overrides llmwiki's) |
| `briefing` | Client state briefing with citations |
| `stakeholders` | Ranked stakeholder list |
| `commitments` | Open/closed commitments, filterable by owner |
| `decisions` | Decision log, filterable by workstream/date |
| `clients` | List all known clients |

The four query tools are deterministic (no LLM in the loop!); they aggregate YAML frontmatter directly.

### CLI

| Command | Description |
|---------|-------------|
| `./growth-cloud init <ws>` | Create workspace with schema + directory structure |
| `./growth-cloud mcp <ws>` | Start MCP server (stdio, for Claude Desktop) |
| `./growth-cloud mcp-config <ws>` | Print Claude Desktop JSON config |
| `./growth-cloud ingest <ws>` | Poll Fathom, extract AIDs, trigger recompile |
| `./growth-cloud recompile <ws> <aid>` | Recompile wiki pages affected by a specific AID |

Optional env vars (see `growth-cloud/.env.example`):

| Variable | Default | Description |
|----------|---------|-------------|
| `ANTHROPIC_MODEL` | `claude-sonnet-4-5-20250929` | Override extraction model |
| `LLMWIKI_ROOT` | `../llmwiki` | Path to llmwiki checkout |
| `LOG_LEVEL` | `INFO` | Logging verbosity |

## Specification

### Data Flow

```
Fathom API -> ingest poller -> Claude (extract) -> AID markdown -> workspace
                                                                      |
                                                        recompile worker
                                                                      |
                                                        Claude (MCP tools)
                                                                      |
                                                  /wiki/clients/<c>/...
```

### On-Disk Layout

```
workspace/
  clients/<slug>/calls/*.md   # AIDs (YAML frontmatter = structured data, body = summary)
  wiki/clients/<slug>/        # overview.md, commitments.md, log.md, stakeholders/, ...
  .llmwiki/index.db           # Derived SQLite index (rebuildable from filesystem)
```

## Requirements

- Python 3.11+
- [llmwiki](./llmwiki/) checkout (auto-detected as sibling, or set `LLMWIKI_ROOT`)
- `FATHOM_API_KEY` — Fathom API token (for ingest)
- `ANTHROPIC_API_KEY` — Anthropic API key (for extraction + recompile)

Runs entirely local otherwise: filesystem + SQLite.


