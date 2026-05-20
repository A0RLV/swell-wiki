"""End-to-end test exercising the StdoutClaudeRunner against a written AID."""

from __future__ import annotations

from pathlib import Path

from ingest.runner import StdoutClaudeRunner
from ingest.writer import aid_relative_path
from recompile.worker import build_recompile_prompt


async def test_stdout_runner_writes_log_entry(populated_workspace: Path, sample_aid_factory):
    rel = aid_relative_path(sample_aid_factory())
    aid_path = populated_workspace / rel
    prompt = build_recompile_prompt(populated_workspace, aid_path)

    runner = StdoutClaudeRunner(populated_workspace)
    result = await runner(prompt)

    assert "target-darts" in result
    log = populated_workspace / "wiki" / "clients" / "target-darts" / "log.md"
    assert log.is_file()
    assert "## [2025-04-12] ingest" in log.read_text()

    overview = populated_workspace / "wiki" / "clients" / "target-darts" / "overview.md"
    assert overview.is_file()


async def test_stdout_runner_handles_missing_aid(tmp_path: Path):
    runner = StdoutClaudeRunner(tmp_path)
    result = await runner("A new AID has landed: `clients/x/calls/missing.md`.\n")
    assert "not found" in result.lower()
