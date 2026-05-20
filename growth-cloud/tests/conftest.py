"""Shared pytest fixtures for the Growth Cloud test suite."""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from schema.aid import (  # noqa: E402
    AID,
    Commitment,
    Decision,
    Experiment,
    Participant,
    PerformanceSignal,
    SentimentBeat,
)
from ingest.writer import write_aid  # noqa: E402


def _sample_aid(client: str = "target-darts", call_date: date | None = None, fathom_id: str = "abc123") -> AID:
    return AID(
        client=client,
        call_date=call_date or date(2025, 4, 12),
        fathom_id=fathom_id,
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
        summary="Paid search review for DACH. Aligned on copy fix.",
    )


@pytest.fixture
def sample_aid_factory():
    return _sample_aid


@pytest.fixture
def populated_workspace(tmp_path: Path, sample_aid_factory):
    """Workspace with one AID written under clients/target-darts/calls/."""
    write_aid(tmp_path, sample_aid_factory())
    return tmp_path


@pytest.fixture
def fixtures_root() -> Path:
    return ROOT / "tests" / "fixtures" / "fathom"
