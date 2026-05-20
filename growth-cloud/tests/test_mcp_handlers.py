"""Tests for the four MVP MCP tool handlers + the guide override.

Uses FastMCP's `call_tool` public API (pinned in pyproject.toml to mcp[cli]>=1.27,<2)
to invoke handlers as Claude would. Assertions check the citation contract.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from mcp.server.fastmcp import FastMCP

from mcp_tools.guide import register as register_guide
from mcp_tools.tools import register as register_tools


@pytest.fixture
def mcp_server(populated_workspace: Path) -> FastMCP:
    mcp = FastMCP(name="test")
    register_guide(mcp, populated_workspace)
    register_tools(mcp, populated_workspace)
    return mcp


async def _call(mcp: FastMCP, name: str, **kwargs) -> str:
    """Invoke a tool and return its concatenated text output."""
    result = await mcp.call_tool(name, kwargs)
    # FastMCP returns (content_blocks, structured) — content_blocks is list[TextContent].
    blocks = result[0] if isinstance(result, tuple) else result
    return "".join(getattr(b, "text", str(b)) for b in blocks)


async def test_guide_returns_growth_cloud_text(mcp_server, populated_workspace):
    out = await _call(mcp_server, "guide")
    assert "Swell Growth Cloud" in out
    assert "target-darts" in out  # populated workspace lists this client
    # Confirm we did NOT get llmwiki's research-wiki guide text.
    assert "Concepts" not in out or "compounded wiki" in out


async def test_clients_lists_target_darts(mcp_server):
    out = await _call(mcp_server, "clients")
    assert "target-darts" in out


async def test_briefing_includes_citation(mcp_server):
    out = await _call(mcp_server, "briefing", client="target-darts")
    assert "target-darts" in out
    assert "clients/target-darts/calls/" in out
    assert "@ 00:14:22" in out or "@ 00:18:05" in out


async def test_briefing_with_since(mcp_server):
    # Fixture AID has call_date=2025-04-12; use an ISO date well before it.
    out = await _call(mcp_server, "briefing", client="target-darts", since="2025-01-01")
    assert "1 call" in out


async def test_stakeholders_ranks_chris(mcp_server):
    out = await _call(mcp_server, "stakeholders", client="target-darts")
    assert "Chris Strand" in out
    assert "clients/target-darts/calls/" in out


async def test_commitments_default_open(mcp_server):
    out = await _call(mcp_server, "commitments", client="target-darts")
    assert "Mar to ship copy change" in out
    assert "@ 00:18:05" in out


async def test_commitments_filtered_by_owner(mcp_server):
    out = await _call(mcp_server, "commitments", client="target-darts", owner="Mar Vidal")
    assert "Mar to ship" in out

    none = await _call(mcp_server, "commitments", client="target-darts", owner="Nobody")
    assert "No `open` commitments" in none


async def test_decisions_with_workstream(mcp_server):
    out = await _call(mcp_server, "decisions", client="target-darts", workstream="paid-search")
    assert "Switch DE landing pages" in out
    assert "@ 00:14:22" in out


async def test_decisions_empty_for_missing_client(mcp_server):
    out = await _call(mcp_server, "decisions", client="nonexistent")
    assert "No decisions matched" in out
