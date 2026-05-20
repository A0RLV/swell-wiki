"""Serialize an AID to markdown and write it into the llmwiki workspace."""

from __future__ import annotations

import re
from pathlib import Path

import yaml

from schema.aid import AID


def _slugify(s: str) -> str:
    s = re.sub(r"[^a-zA-Z0-9]+", "-", s.lower()).strip("-")
    return s[:60] or "untitled"


def aid_relative_path(aid: AID) -> Path:
    slug = _slugify(aid.title)
    filename = f"{aid.call_date.isoformat()}-{slug}.md"
    return Path("clients") / aid.client / "calls" / filename


def render_aid_markdown(aid: AID) -> str:
    """Render an AID as a markdown file. Frontmatter = full structured payload,
    body = the one-paragraph synthesis. The wiki layer (compiled by Claude over
    MCP) consumes this — it does not duplicate the structured data."""

    frontmatter = aid.model_dump(mode="json", exclude={"summary"})
    yaml_block = yaml.safe_dump(frontmatter, sort_keys=False, allow_unicode=True)

    body_lines = [
        "---",
        yaml_block.strip(),
        "---",
        "",
        f"# {aid.title}",
        "",
        aid.summary or "_(no summary extracted)_",
        "",
    ]

    # A small humans-readable rollup so the AID is useful on its own when
    # opened in Obsidian / a plain editor. Numbers stay authoritative in
    # frontmatter — this is a courtesy view.
    if aid.decisions:
        body_lines.append("## Decisions")
        for d in aid.decisions:
            owner = f" — {d.owner}" if d.owner else ""
            ts = f" [{d.source_timestamp}]" if d.source_timestamp else ""
            body_lines.append(f"- {d.statement}{owner}{ts}")
        body_lines.append("")
    if aid.commitments:
        body_lines.append("## Commitments")
        for c in aid.commitments:
            owner = f" — {c.owner}" if c.owner else ""
            due = f" (due {c.due.isoformat()})" if c.due else ""
            ts = f" [{c.source_timestamp}]" if c.source_timestamp else ""
            body_lines.append(f"- [{c.status}] {c.statement}{owner}{due}{ts}")
        body_lines.append("")
    if aid.performance_signals:
        body_lines.append("## Performance signals")
        for s in aid.performance_signals:
            scope = "/".join(x for x in [s.market, s.channel] if x)
            scope = f" ({scope})" if scope else ""
            mag = f" — {s.magnitude}" if s.magnitude else ""
            body_lines.append(f"- {s.metric}{scope}: {s.direction}{mag}")
        body_lines.append("")
    if aid.open_questions:
        body_lines.append("## Open questions")
        for q in aid.open_questions:
            owner = f" — {q.owner}" if q.owner else ""
            body_lines.append(f"- {q.question}{owner}")
        body_lines.append("")

    return "\n".join(body_lines)


def write_aid(workspace: Path, aid: AID) -> Path:
    rel = aid_relative_path(aid)
    target = workspace / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(render_aid_markdown(aid), encoding="utf-8")
    return target
