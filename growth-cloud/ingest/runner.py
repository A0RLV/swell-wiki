"""Claude runners for the recompile loop.

The recompile worker (`recompile.worker.recompile_for_aid`) takes a
`claude_runner: (prompt: str) -> str` callable. This module provides two
implementations:

  * ``StdoutClaudeRunner`` — logs the prompt, applies a deterministic
    minimal-viable recompile (touches one log line in
    ``/wiki/clients/<slug>/log.md``), returns a canned summary. Used by tests
    and `--dry-run` so the loop runs without an Anthropic key.

  * ``AnthropicClaudeRunner`` — drives Claude with a small set of in-process
    "tools" (read AID, write/append wiki page) and a hard iteration cap.
    This is intentionally narrower than the full llmwiki MCP surface — the
    recompile prompt at `recompile/worker.py:72-95` only needs read+write
    against known paths.

Production deployments may swap this for the official Claude Agent SDK
talking to the stdio MCP server. This implementation keeps the
dependency footprint tiny and the loop testable.
"""

from __future__ import annotations

import asyncio
import logging
import re
from datetime import date as _date
from pathlib import Path
from typing import Awaitable, Callable

import yaml

logger = logging.getLogger(__name__)

ClaudeRunner = Callable[[str], Awaitable[str]]


# ── StdoutClaudeRunner ────────────────────────────────────────────────────────

class StdoutClaudeRunner:
    """Deterministic, no-network runner used by tests and `--dry-run`.

    Parses the recompile prompt to discover the AID path, ensures the client
    overview/log files exist, appends one log entry, and returns a summary.
    This is enough to verify the end-to-end pipeline wires together; real
    wiki authoring requires the Anthropic runner.
    """

    def __init__(self, workspace: Path):
        self.workspace = Path(workspace)

    async def __call__(self, prompt: str) -> str:
        # Extract the AID relative path from the recompile prompt — see
        # recompile/worker.py:62-74 for the format string.
        m = re.search(r"`([^`]+\.md)`", prompt)
        if not m:
            return "stdout-runner: no AID path detected"
        rel = m.group(1)
        aid_path = self.workspace / rel
        if not aid_path.is_file():
            return f"stdout-runner: AID not found at {rel}"

        fm = _read_frontmatter(aid_path)
        if not fm:
            return "stdout-runner: no frontmatter"
        client = fm.get("client", "unknown")
        title = fm.get("title", "untitled")
        call_date = fm.get("call_date", _date.today().isoformat())

        wiki_dir = self.workspace / "wiki" / "clients" / client
        wiki_dir.mkdir(parents=True, exist_ok=True)

        overview = wiki_dir / "overview.md"
        if not overview.exists():
            overview.write_text(
                f"# {client} — overview\n\n"
                "_Auto-scaffolded by stdout-runner. Replace with Claude-authored "
                "content when ANTHROPIC_API_KEY is set._\n"
            )

        log = wiki_dir / "log.md"
        entry = f"## [{call_date}] ingest | {title}\n- AID: `{rel}`\n\n"
        if log.exists():
            log.write_text(log.read_text() + entry)
        else:
            log.write_text(entry)

        return f"stdout-runner: wrote log entry for {client}/{title}"


# ── AnthropicClaudeRunner ─────────────────────────────────────────────────────

class AnthropicClaudeRunner:
    """Minimal Anthropic tool-use loop scoped to the recompile envelope.

    Tools exposed to Claude:
      - ``read_aid(path)`` — full text of an AID
      - ``read_page(path)`` — existing wiki page (returns empty if missing)
      - ``write_page(path, content)`` — overwrites or creates a wiki page
      - ``append_page(path, content)`` — appends to an existing wiki page

    All paths are workspace-relative and must start with ``wiki/clients/`` or
    ``clients/`` to prevent escape. Iteration is capped at MAX_TURNS.
    """

    MAX_TURNS = 12
    MAX_TOKENS = 4096

    def __init__(self, settings, workspace: Path):
        from anthropic import AsyncAnthropic

        self._anthropic = AsyncAnthropic(api_key=settings.ANTHROPIC_API_KEY)
        self._model = settings.ANTHROPIC_MODEL
        self.workspace = Path(workspace)

    async def __call__(self, prompt: str) -> str:
        tools = self._tool_specs()
        messages: list[dict] = [{"role": "user", "content": prompt}]

        for turn in range(self.MAX_TURNS):
            resp = await self._anthropic.messages.create(
                model=self._model,
                max_tokens=self.MAX_TOKENS,
                tools=tools,
                messages=messages,
            )
            messages.append({"role": "assistant", "content": resp.content})

            if resp.stop_reason == "end_turn":
                # Concatenate the last text blocks as the runner result.
                return "".join(b.text for b in resp.content if getattr(b, "type", "") == "text")

            if resp.stop_reason != "tool_use":
                return f"anthropic-runner: unexpected stop_reason={resp.stop_reason}"

            tool_results = []
            for block in resp.content:
                if getattr(block, "type", "") != "tool_use":
                    continue
                try:
                    out = self._dispatch(block.name, block.input)
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": out,
                    })
                except Exception as e:
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": f"error: {e}",
                        "is_error": True,
                    })
            messages.append({"role": "user", "content": tool_results})

        return "anthropic-runner: hit MAX_TURNS without end_turn"

    def _tool_specs(self) -> list[dict]:
        return [
            {
                "name": "read_aid",
                "description": "Read an AID markdown file. Path must start with 'clients/'.",
                "input_schema": {
                    "type": "object",
                    "properties": {"path": {"type": "string"}},
                    "required": ["path"],
                },
            },
            {
                "name": "read_page",
                "description": "Read a wiki page. Returns empty string if missing. Path must start with 'wiki/'.",
                "input_schema": {
                    "type": "object",
                    "properties": {"path": {"type": "string"}},
                    "required": ["path"],
                },
            },
            {
                "name": "write_page",
                "description": "Create or overwrite a wiki page. Path must start with 'wiki/'.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string"},
                        "content": {"type": "string"},
                    },
                    "required": ["path", "content"],
                },
            },
            {
                "name": "append_page",
                "description": "Append text to a wiki page (creating it if missing). Path must start with 'wiki/'.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string"},
                        "content": {"type": "string"},
                    },
                    "required": ["path", "content"],
                },
            },
        ]

    def _resolve(self, path: str, allowed_prefixes: tuple[str, ...]) -> Path:
        if not any(path.startswith(p) for p in allowed_prefixes):
            raise ValueError(f"path must start with one of {allowed_prefixes}: {path}")
        # Reject traversal.
        if ".." in Path(path).parts:
            raise ValueError(f"path traversal rejected: {path}")
        full = (self.workspace / path).resolve()
        # Defense in depth: confirm the resolved path is still inside workspace.
        if not str(full).startswith(str(self.workspace.resolve())):
            raise ValueError(f"path escapes workspace: {path}")
        return full

    def _dispatch(self, name: str, inputs: dict) -> str:
        if name == "read_aid":
            p = self._resolve(inputs["path"], ("clients/",))
            return p.read_text(encoding="utf-8") if p.is_file() else ""
        if name == "read_page":
            p = self._resolve(inputs["path"], ("wiki/",))
            return p.read_text(encoding="utf-8") if p.is_file() else ""
        if name == "write_page":
            p = self._resolve(inputs["path"], ("wiki/",))
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(inputs["content"], encoding="utf-8")
            return f"wrote {inputs['path']} ({len(inputs['content'])} bytes)"
        if name == "append_page":
            p = self._resolve(inputs["path"], ("wiki/",))
            p.parent.mkdir(parents=True, exist_ok=True)
            existing = p.read_text(encoding="utf-8") if p.is_file() else ""
            p.write_text(existing + inputs["content"], encoding="utf-8")
            return f"appended {len(inputs['content'])} bytes to {inputs['path']}"
        raise ValueError(f"unknown tool: {name}")


# ── Factory ───────────────────────────────────────────────────────────────────

def build_claude_runner(settings, dry_run: bool) -> ClaudeRunner:
    """Choose the runner for a given settings + flag combo.

    `dry_run=True` or missing `ANTHROPIC_API_KEY` falls back to the stdout
    runner.
    """
    workspace = Path(settings.GROWTH_CLOUD_WORKSPACE)
    if dry_run or not settings.ANTHROPIC_API_KEY:
        return StdoutClaudeRunner(workspace)
    return AnthropicClaudeRunner(settings, workspace)


# ── Helpers ───────────────────────────────────────────────────────────────────

_FRONTMATTER_RE = re.compile(r"^---\n(.*?)\n---\n", re.S)


def _read_frontmatter(path: Path) -> dict | None:
    text = path.read_text(encoding="utf-8", errors="ignore")
    m = _FRONTMATTER_RE.match(text)
    if not m:
        return None
    data = yaml.safe_load(m.group(1))
    return data if isinstance(data, dict) else None
