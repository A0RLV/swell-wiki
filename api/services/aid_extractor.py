"""AID extractor — Claude Sonnet 4.6 on the marketing-ops schema.

Per Cyril's spec: every Fathom call → one Atomic Insight Document, validated,
upserted into the SQLite entity tables, also written to `wiki/calls/<call_id>.md`.

Design notes:
  - Sonnet 4.6 with adaptive thinking — extraction is structured but the
    judgment call on what qualifies as a "decision" vs "discussion" benefits
    from a little reasoning.
  - Prompt caching on the system prompt + tool schema. When backfilling 50
    Target Darts calls, calls 2..N hit cache for the ~2K-token preamble.
  - Strict tool mode (`strict: True`) — the schema is enforced server-side, no
    parser tap-dancing on our end.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

import anthropic
from pydantic import ValidationError

from ..schemas.aid import AID, aid_tool_input_schema

logger = logging.getLogger(__name__)

EXTRACTION_MODEL = "claude-sonnet-4-6"
_PROMPT_PATH = Path(__file__).resolve().parents[2] / "prompts" / "aid_extraction.md"


def _load_system_prompt() -> str:
    return _PROMPT_PATH.read_text(encoding="utf-8")


def _render_transcript_for_extraction(
    segments: list[dict],
    call_id: str,
    title: str,
    date: str,
    attendees: list[str],
    fathom_url: str | None,
) -> str:
    """Render the call as a single prompt block with explicit [t=NNN] anchors.

    Format:
        call_id: <id>
        title:   <title>
        date:    <YYYY-MM-DD>
        attendees: a, b, c
        --
        [t=12] Speaker A: ...
        [t=47] Speaker B: ...
    """
    header = [
        f"call_id: {call_id}",
        f"title: {title}",
        f"date: {date}",
        f"attendees: {', '.join(attendees) if attendees else '(unknown)'}",
    ]
    if fathom_url:
        header.append(f"fathom_url: {fathom_url}")
    header.append("--")

    body = [
        f"[t={seg['t_start_s']}] {seg.get('speaker') or 'Unknown'}: {seg['content']}"
        for seg in segments
    ]
    return "\n".join(header + body)


def extract_aid(
    client: anthropic.Anthropic,
    *,
    call_id: str,
    title: str,
    date: str,
    attendees: list[str],
    fathom_url: str | None,
    segments: list[dict],
) -> AID:
    """Run the extractor against one call. Returns a validated AID.

    Args:
        client: An initialized Anthropic client (workspace's API key).
        segments: Output of `fathom_ingest.normalize_transcript` — each item has
            `seg_index`, `t_start_s`, `t_end_s`, `speaker`, `content`.

    Raises:
        ValueError: if the model didn't call the `record_aid` tool.
        pydantic.ValidationError: if the tool input failed schema validation
            (shouldn't happen with strict=True, but defense-in-depth).
    """
    transcript = _render_transcript_for_extraction(
        segments=segments,
        call_id=call_id,
        title=title,
        date=date,
        attendees=attendees,
        fathom_url=fathom_url,
    )

    system_prompt = _load_system_prompt()

    # System prompt + tool schema are stable across calls → put cache breakpoint
    # at end of system. Tools render before system, so the breakpoint covers both.
    response = client.messages.create(
        model=EXTRACTION_MODEL,
        max_tokens=16000,
        thinking={"type": "adaptive"},
        system=[
            {
                "type": "text",
                "text": system_prompt,
                "cache_control": {"type": "ephemeral"},
            }
        ],
        tools=[
            {
                "name": "record_aid",
                "description": (
                    "Record the Atomic Insight Document for this Fathom call. "
                    "Call this exactly once with the full extraction."
                ),
                "input_schema": aid_tool_input_schema(),
                "strict": True,
            }
        ],
        tool_choice={"type": "tool", "name": "record_aid"},
        messages=[
            {
                "role": "user",
                "content": (
                    "Extract the AID for the call below. Anchor every entity "
                    "to the transcript timestamps shown as [t=NNN].\n\n"
                    f"{transcript}"
                ),
            }
        ],
    )

    logger.info(
        "extract_aid call_id=%s cache_read=%s cache_creation=%s out_tokens=%s",
        call_id,
        response.usage.cache_read_input_tokens,
        response.usage.cache_creation_input_tokens,
        response.usage.output_tokens,
    )

    for block in response.content:
        if block.type == "tool_use" and block.name == "record_aid":
            try:
                return AID.model_validate(block.input)
            except ValidationError as e:
                logger.error("AID validation failed for %s: %s", call_id, e)
                raise

    raise ValueError(
        f"extractor did not call record_aid for {call_id} "
        f"(stop_reason={response.stop_reason})"
    )


def aid_to_wiki_markdown(aid: AID) -> str:
    """Render an AID as a markdown wiki page with YAML frontmatter.

    Lives at `wiki/calls/<call_id>.md`. Citations elsewhere in the wiki point
    here with `#tNNN` anchors that the renderer turns into transcript links.
    """
    lines = ["---", f"call_id: {aid.call.id}", f"date: {aid.call.date}",
             f"title: {json.dumps(aid.call.title)}",
             f"attendees: {json.dumps(aid.call.attendees)}"]
    if aid.call.fathom_url:
        lines.append(f"fathom_url: {aid.call.fathom_url}")
    lines += ["kind: aid", "---", "", f"# {aid.call.title}", "", "## TL;DR"]
    lines += [f"- {b}" for b in aid.summary_bullets]

    def _cite(t_start: int) -> str:
        return f"[[t={t_start}]](#t{t_start})"

    if aid.decisions:
        lines += ["", "## Decisions"]
        for d in aid.decisions:
            owner = f" — _{d.owner}_" if d.owner else ""
            deadline = f" (due {d.deadline})" if d.deadline else ""
            lines.append(f"- {d.summary}{owner}{deadline} {_cite(d.t_start_s)}")

    if aid.commitments:
        lines += ["", "## Commitments"]
        for c in aid.commitments:
            due = f" by {c.due}" if c.due else ""
            lines.append(f"- {c.summary}{due} [{c.status}] {_cite(c.t_start_s)}")

    if aid.experiments:
        lines += ["", "## Experiments"]
        for e in aid.experiments:
            scope = " / ".join(filter(None, [e.market, e.channel]))
            scope_str = f" ({scope})" if scope else ""
            lines.append(f"- **{e.name}**{scope_str} [{e.status}] {_cite(e.t_start_s)}")
            if e.hypothesis:
                lines.append(f"  - Hypothesis: {e.hypothesis}")

    if aid.workstreams:
        lines += ["", "## Workstreams"]
        for w in aid.workstreams:
            status = f" [{w.status}]" if w.status else ""
            lines.append(f"- **{w.name}**{status} {_cite(w.t_start_s)}")
            if w.key_update:
                lines.append(f"  - {w.key_update}")

    if aid.performance_signals:
        lines += ["", "## Performance signals"]
        for p in aid.performance_signals:
            scope = " / ".join(filter(None, [p.market, p.channel]))
            scope_str = f" ({scope})" if scope else ""
            val = f" = {p.value}" if p.value else ""
            arrow = {"up": "↑", "down": "↓", "flat": "→", "unknown": ""}[p.direction]
            lines.append(f"- {p.metric}{val} {arrow}{scope_str} {_cite(p.t_start_s)}")
            if p.note:
                lines.append(f"  - {p.note}")

    if aid.open_questions:
        lines += ["", "## Open questions"]
        for q in aid.open_questions:
            who = f" — ask {q.who_to_ask}" if q.who_to_ask else ""
            lines.append(f"- {q.question}{who} {_cite(q.t_start_s)}")

    if aid.stakeholders:
        lines += ["", "## Stakeholders on this call"]
        for s in aid.stakeholders:
            bits = [s.name]
            if s.role:
                bits.append(s.role)
            if s.company:
                bits.append(f"@ {s.company}")
            lines.append(f"- **{' '.join(bits)}** — {s.seniority}, {s.sentiment}")
            if s.authority_signals:
                for sig in s.authority_signals:
                    lines.append(f"  - _{sig}_")

    return "\n".join(lines) + "\n"
