"""Recompile worker.

Triggered when a new AID lands. Computes the set of wiki pages affected by the
new call (overview, stakeholders, workstreams, markets, channels) and asks
Claude — via the existing llmwiki MCP write/edit tools — to re-derive them.

This module deliberately does NOT modify wiki pages itself. The wiki layer is
owned by Claude over MCP (that's the llmwiki pattern). We just compute the
work envelope, hand Claude a tight prompt, and let it use `write`/`edit`/
`append` against the workspace.

In practice this runs as a background async task spawned by the ingest poller.
For local dev you can also invoke it as a CLI: `python -m recompile.worker --aid <path>`.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from textwrap import dedent

import yaml

logger = logging.getLogger(__name__)


def affected_pages(workspace: Path, aid_path: Path) -> dict[str, list[str]]:
    """Inspect an AID's frontmatter and return the wiki paths that should be
    recompiled. Pure / deterministic — no Claude in the loop here."""
    fm = _read_frontmatter(aid_path)
    if not fm:
        return {}
    client = fm["client"]
    base = f"/wiki/clients/{client}"

    pages: dict[str, list[str]] = {
        "overview": [f"{base}/overview.md"],
        "commitments": [f"{base}/commitments.md"],
        "log": [f"{base}/log.md"],
        "stakeholders": [
            f"{base}/stakeholders/{_slug(p['name'])}.md"
            for p in (fm.get("participants") or [])
            if p.get("name") and not p.get("swell_side")
        ],
        "workstreams": [f"{base}/workstreams/{w}.md" for w in (fm.get("workstreams") or [])],
        "markets": [f"{base}/markets/{m}.md" for m in (fm.get("markets") or [])],
        "channels": [f"{base}/channels/{c}.md" for c in (fm.get("channels") or [])],
        "decisions": [
            f"{base}/decisions/{d['id']}.md"
            for d in (fm.get("decisions") or [])
            if d.get("id")
        ],
    }
    return {k: v for k, v in pages.items() if v}


def build_recompile_prompt(workspace: Path, aid_path: Path) -> str:
    """The prompt we hand to a Claude task with MCP access. The agent's job is
    deterministic from here: read the AID, update the listed pages, append a
    log entry, flag contradictions."""

    rel_aid = aid_path.relative_to(workspace).as_posix()
    pages = affected_pages(workspace, aid_path)
    fm = _read_frontmatter(aid_path) or {}

    bullets: list[str] = []
    for kind, paths in pages.items():
        for p in paths:
            bullets.append(f"  - [{kind}] `{p}`")

    return dedent(f"""
        A new AID has landed for client `{fm.get('client')}` (call date
        {fm.get('call_date')}): `{rel_aid}`.

        Re-derive the wiki layer for this client over the pages below. Read the
        AID first, then update each page in turn. Cite every claim with a
        footnote that links to `{rel_aid}` and the relevant source_timestamp.

        Pages to refresh (create if missing):
        {chr(10).join(bullets)}

        Hygiene rules:
        - If a claim in this AID contradicts an existing claim on a page, do not
          silently overwrite. Add a `## Contradictions` section to that page with
          both claims, both sources, and your synthesis. Append a `lint` entry to
          `/wiki/clients/{fm.get('client')}/log.md` noting the contradiction.
        - Stakeholder pages: only update remit/authority if the AID provides new
          evidence. Always append to the sentiment trail when present.
        - The overview must reflect the latest 5 decisions, the count of open
          commitments, and the active experiments. Keep it under 400 words.
        - Append one `## [YYYY-MM-DD] ingest | <call title>` entry to log.md.

        When done, return a short summary of what changed.
    """).strip()


def _read_frontmatter(path: Path) -> dict | None:
    text = path.read_text(encoding="utf-8", errors="ignore")
    m = re.match(r"^---\n(.*?)\n---\n", text, re.S)
    if not m:
        return None
    return yaml.safe_load(m.group(1))


def _slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-") or "unknown"


# ── Driver ────────────────────────────────────────────────────────────────────

async def recompile_for_aid(workspace: Path, aid_path: Path, claude_runner) -> str:
    """Invoke Claude with MCP access against the recompile prompt.

    `claude_runner` is an async callable `(prompt: str) -> str` that the host
    application provides. In production this is a Claude SDK call configured
    with the llmwiki MCP server; in tests it's a fake. Keeping the dependency
    injected means this module stays import-light and easy to exercise.
    """
    prompt = build_recompile_prompt(workspace, aid_path)
    logger.info("Recompiling for %s", aid_path)
    return await claude_runner(prompt)
