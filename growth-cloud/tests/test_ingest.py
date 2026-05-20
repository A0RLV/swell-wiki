"""Tests for the fixture transport + GrowthCloudIngest end-to-end with a
stubbed AIDExtractor (no Anthropic call)."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest

from ingest.fathom import (
    AIDExtractor,
    ClientRouter,
    FathomCall,
    FathomClient,
    FixtureFathomTransport,
    GrowthCloudIngest,
)
from schema.aid import AID


class _StubExtractor:
    """Returns a fixed AID without calling Anthropic."""

    async def extract(self, client_slug: str, call: FathomCall) -> AID:
        return AID(
            client=client_slug,
            call_date=call.started_at.date(),
            fathom_id=call.fathom_id,
            title=call.title,
            duration_seconds=call.duration_seconds,
            summary="stub summary",
        )


async def test_fixture_transport_lists_recent(fixtures_root: Path):
    t = FixtureFathomTransport(fixtures_root)
    since = datetime(2025, 1, 1, tzinfo=timezone.utc)
    items = await t.list_recent(since)
    assert len(items) == 3

    # since filter
    future = datetime(2030, 1, 1, tzinfo=timezone.utc)
    assert await t.list_recent(future) == []


async def test_fixture_transport_fetch_call(fixtures_root: Path):
    t = FixtureFathomTransport(fixtures_root)
    data = await t.fetch_call("call-001")
    assert data["title"].startswith("Paid search")


async def test_fixture_transport_missing_root_raises(tmp_path: Path):
    with pytest.raises(FileNotFoundError):
        FixtureFathomTransport(tmp_path / "does-not-exist")


async def test_poll_once_writes_aids(tmp_path: Path, fixtures_root: Path):
    transport = FixtureFathomTransport(fixtures_root)
    client = FathomClient(transport)
    router = ClientRouter(
        domain_map={"target-darts.com": "target-darts", "verisure.com": "verisure"},
        default=None,
    )
    notifications: list = []

    async def _notify(slug, path):
        notifications.append((slug, path))

    ingest = GrowthCloudIngest(
        workspace=tmp_path,
        client_router=router,
        fathom=client,
        extractor=_StubExtractor(),
        on_aid_written=_notify,
    )
    written = await ingest.poll_once(lookback=timedelta(days=365 * 5))
    assert len(written) == 2  # call-orphan is unrouted
    slugs = sorted(p.parts[-3] for p in written)
    assert slugs == ["target-darts", "verisure"]
    assert len(notifications) == 2


async def test_poll_once_dedupes(tmp_path: Path, fixtures_root: Path):
    transport = FixtureFathomTransport(fixtures_root)
    client = FathomClient(transport)
    router = ClientRouter({"target-darts.com": "target-darts"})
    ingest = GrowthCloudIngest(
        workspace=tmp_path,
        client_router=router,
        fathom=client,
        extractor=_StubExtractor(),
    )
    first = await ingest.poll_once(lookback=timedelta(days=365 * 5))
    second = await ingest.poll_once(lookback=timedelta(days=365 * 5))
    assert len(first) == 1
    assert len(second) == 0  # already-ingested check skips it
