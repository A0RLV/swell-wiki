"""MCP tools exposing the four briefings to Claude Desktop / Claude Code.

Drop into llmwiki's `mcp/tools/` directory and register alongside the existing
search/read/write tools in `mcp/local_server.py`:

    from .briefing import register as register_briefing
    register_briefing(mcp, fs, kb)

Each tool wraps the matching `services/briefings.py` composer. Output is the
markdown answer; citations stay embedded as `[call_id:t_start]` chips, which
Claude can resolve via the existing `search` / `read` tools if it wants context.
"""

from __future__ import annotations

from datetime import date

import anthropic
from mcp.server.fastmcp import FastMCP

from ..db.growth_cloud import GrowthCloudRepo  # type: ignore[import-not-found]
from ..services import briefings as briefings_svc  # type: ignore[import-not-found]


def register(mcp: FastMCP, repo: GrowthCloudRepo, client: anthropic.Anthropic, workspace_id: str) -> None:
    @mcp.tool()
    def briefing_tldr() -> str:
        """Return a 5-bullet TLDR of the current state of the workspace, sourced.

        Use when the user asks 'what's the state of [client]', 'catch me up',
        'TLDR on our work with X'.
        """
        b = briefings_svc.tldr(repo, client, workspace_id=workspace_id)
        return b.answer_md

    @mcp.tool()
    def briefing_delta(since: str, person: str | None = None) -> str:
        """What's new since `since` (ISO-8601 date), optionally narrowed to `person`.

        Use when the user asks 'what's changed since my last call with X',
        'any developments in the last two weeks', 'updates since DATE'.
        """
        return briefings_svc.delta(
            repo, client, workspace_id=workspace_id,
            since=date.fromisoformat(since), person=person,
        ).answer_md

    @mcp.tool()
    def briefing_stakeholders() -> str:
        """Stakeholder map: who calls the shots on what, grouped by company.

        Use when the user asks 'who owns X', 'who can sign off on Y', 'who are
        the stakeholders on this account'.
        """
        return briefings_svc.stakeholder_map(repo, client, workspace_id=workspace_id).answer_md

    @mcp.tool()
    def briefing_onboarding(role: str) -> str:
        """Onboarding briefing: 'where do I fit in' for a given role.

        Use when the user is new to the account and asks 'where do I start',
        'what's open in my area', 'who else should I sync with'.
        """
        return briefings_svc.onboarding(repo, client, workspace_id=workspace_id, user_role=role).answer_md
