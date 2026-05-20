# Swell Growth Cloud

A vertical marketing-ops product built on top of [llmwiki](../llmwiki/). It turns
Fathom call transcripts into structured **AID** documents (Augmented Interaction
Documents) and compounds a per-client wiki over them using Claude via MCP.

## Architecture

```
Fathom API --> ingest poller --> Claude (extract) --> AID markdown --> llmwiki workspace
                                                                           |
                                                             recompile worker
                                                                           |
                                                             Claude (over MCP)
                                                                           |
                                                       /wiki/clients/<c>/...
```

- **Source layer** — raw AID documents the user owns. Read-only to Claude.
- **Wiki layer** — markdown pages under `/wiki/...` written by Claude via MCP tools.

## Quick Start

```bash
# 1. Install
pip install -e '.[dev]'

# 2. Init a workspace
./growth-cloud init /path/to/workspace

# 3. Get Claude Desktop config
./growth-cloud mcp-config /path/to/workspace

# 4. Run ingest (requires FATHOM_API_KEY and ANTHROPIC_API_KEY)
./growth-cloud ingest /path/to/workspace --once
```

## Environment Variables

Copy `.env.example` and fill in your values:

| Variable | Required | Description |
|----------|----------|-------------|
| `FATHOM_API_KEY` | Yes (ingest) | Fathom API token |
| `ANTHROPIC_API_KEY` | Yes (ingest + recompile) | Anthropic API key |
| `ANTHROPIC_MODEL` | No | Override model (default: claude-sonnet-4-5-20250929) |
| `LLMWIKI_ROOT` | No | Path to llmwiki checkout (auto-detected from sibling) |
| `LOG_LEVEL` | No | Logging level (default: INFO) |

## CLI Commands

| Command | Description |
|---------|-------------|
| `./growth-cloud init <workspace>` | Initialize a workspace with schema and directory structure |
| `./growth-cloud mcp <workspace>` | Start the MCP server (stdio transport for Claude Desktop) |
| `./growth-cloud mcp-config <workspace>` | Print Claude Desktop JSON config snippet |
| `./growth-cloud ingest <workspace>` | Poll Fathom and ingest new calls as AIDs |
| `./growth-cloud recompile <workspace> <aid-path>` | Recompile wiki pages affected by a specific AID |

## MCP Tools

Inherits all llmwiki tools (`search`, `read`, `write`, `delete`, `references`, `ping`)
plus Growth Cloud-specific tools:

| Tool | Description |
|------|-------------|
| `guide` | Growth Cloud doctrine (overrides llmwiki's guide) |
| `briefing` | Current-state briefing for a client |
| `stakeholders` | Ranked stakeholder list with citations |
| `commitments` | Open/closed commitments filtered by owner |
| `decisions` | Decision log filtered by workstream/date |
| `clients` | List all known clients |

## Testing

```bash
pytest tests/ -v
```

## Project Structure

```
growth-cloud/
  ingest/          # Fathom polling, AID extraction, writing
  mcp_tools/       # MCP tool handlers (guide, briefing, etc.)
  recompile/       # Wiki recompile worker
  schema/          # AID pydantic schema
  server/          # MCP server entry point + CLI
  tests/           # Test suite
  examples/        # Example workspace with sample AIDs
```
