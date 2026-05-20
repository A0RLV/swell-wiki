"""Pure-logic tests for recompile.worker.affected_pages."""

from __future__ import annotations

from pathlib import Path

from ingest.writer import write_aid
from recompile.worker import affected_pages, build_recompile_prompt
from schema.aid import AID
from datetime import date


def _minimal_aid(**overrides) -> AID:
    base = dict(
        client="acme",
        call_date=date(2025, 5, 1),
        fathom_id="x",
        title="t",
        participants=[],
        workstreams=[],
        markets=[],
        channels=[],
        decisions=[],
        commitments=[],
        experiments=[],
        performance_signals=[],
        sentiment=[],
        open_questions=[],
        summary="",
    )
    base.update(overrides)
    return AID(**base)


def test_affected_pages_empty_aid(tmp_path: Path):
    p = write_aid(tmp_path, _minimal_aid())
    pages = affected_pages(tmp_path, p)
    # Even an empty AID gets overview, commitments, log; never stakeholders/etc.
    assert pages["overview"] == ["/wiki/clients/acme/overview.md"]
    assert "stakeholders" not in pages
    assert "workstreams" not in pages


def test_affected_pages_full(populated_workspace, sample_aid_factory):
    from ingest.writer import aid_relative_path
    aid = sample_aid_factory()
    rel = aid_relative_path(aid)
    p = populated_workspace / rel
    pages = affected_pages(populated_workspace, p)
    assert any("paid-search" in s for s in pages["workstreams"])
    assert any("de" in s for s in pages["markets"])
    assert any("google-ads" in s for s in pages["channels"])
    assert any("chris" in s.lower() for s in pages["stakeholders"])
    assert any("d1" in s for s in pages["decisions"])


def test_recompile_prompt_mentions_aid_path(populated_workspace, sample_aid_factory):
    from ingest.writer import aid_relative_path
    rel = aid_relative_path(sample_aid_factory())
    prompt = build_recompile_prompt(populated_workspace, populated_workspace / rel)
    assert "target-darts" in prompt
    assert str(rel) in prompt
    assert "Contradictions" in prompt
