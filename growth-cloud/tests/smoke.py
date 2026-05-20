"""Smoke test the schema → writer → MCP-tool path without network or Claude."""

from __future__ import annotations

import asyncio
import sys
import tempfile
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT.parent))  # so `growth_cloud.*` resolves
sys.path.insert(0, str(ROOT))

from schema.aid import (
    AID, Commitment, Decision, Experiment, Participant, PerformanceSignal, SentimentBeat,
)
from ingest.writer import write_aid
from mcp_tools.aid_store import load_aids, workspace_clients


def _fake_aid() -> AID:
    return AID(
        client="target-darts",
        call_date=date(2025, 4, 12),
        fathom_id="abc123",
        title="Paid search review — DACH",
        duration_seconds=2640,
        participants=[
            Participant(name="Chris Strand", role="CMO", org="Target Darts", swell_side=False),
            Participant(name="Mar Vidal", role="Strategist", org="Swell", swell_side=True),
        ],
        workstreams=["paid-search", "brand-de"],
        markets=["de", "nl"],
        channels=["google-ads"],
        decisions=[Decision(
            id="d1", statement="Switch DE landing pages to 'alarmanlage' headline",
            owner="Mar Vidal", status="agreed", workstream="paid-search",
            source_timestamp="00:14:22",
        )],
        commitments=[Commitment(
            id="c1", statement="Mar to ship copy change to webflow by Friday",
            owner="Mar Vidal", due=date(2025, 4, 18), status="open",
            source_timestamp="00:18:05",
        )],
        experiments=[Experiment(
            id="e1", hypothesis="Aligning ad copy and LP copy in DE lifts CVR >10%",
            status="proposed", owner="Mar Vidal", workstream="paid-search",
            source_timestamp="00:21:40",
        )],
        performance_signals=[PerformanceSignal(
            metric="CTR", market="de", channel="google-ads",
            direction="up", magnitude="+12% WoW", source_timestamp="00:09:11",
        )],
        sentiment=[SentimentBeat(
            person="Chris Strand", topic="brand consistency", valence="negative",
            note="frustrated about ad/LP mismatch", source_timestamp="00:13:50",
        )],
        summary=(
            "Paid search review for DACH. Discovered DE ads-vs-LP copy mismatch "
            "(alarmanlage vs alarmsysteem); agreed to align LP headline. Mar owns "
            "the change by Friday."
        ),
    )


async def main() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        workspace = Path(tmp)
        path = write_aid(workspace, _fake_aid())
        assert path.exists(), "AID not written"

        clients = workspace_clients(workspace)
        assert clients == ["target-darts"], clients

        aids = load_aids(workspace, "target-darts")
        assert len(aids) == 1, aids
        _, fm = aids[0]
        assert fm["fathom_id"] == "abc123"
        assert any(d["statement"].startswith("Switch DE") for d in fm["decisions"])

        # Exercise the MCP tool handlers in-process (without spinning up FastMCP)
        from mcp.server.fastmcp import FastMCP
        from mcp_tools.tools import register as register_gc

        # Capture the registered handlers
        mcp = FastMCP(name="test")
        register_gc(mcp, workspace)

        # FastMCP stores tools internally; find them and call directly.
        # We just verify the underlying loaders produce sane output by calling
        # the python-level helpers, since FastMCP's internal API varies.
        from mcp_tools.tools import _parse_since  # type: ignore
        assert _parse_since("7d") is not None
        assert _parse_since(None) is None

        print("OK — AID round-trip + load + parse smoke passed.")
        print("AID written to:", path.relative_to(workspace))
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
