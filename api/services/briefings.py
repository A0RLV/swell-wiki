"""Briefings — the four MVP query composers.

Each composer follows the same shape:
  1. Pull pre-filtered rows from the entity store (helpers in `db/growth_cloud.py`).
  2. Pull supporting transcript spans (transcript_segments table).
  3. Render a prompt with rows + spans; ask Sonnet 4.6 to compose the answer.
  4. Return { answer_md, citations: [{call_id, t_start_s, t_end_s, quote}] }.

The system preamble is cached. Within a workspace, queries 2..N share the cache.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import anthropic

from ..db.growth_cloud import GrowthCloudRepo

logger = logging.getLogger(__name__)

BRIEFING_MODEL = "claude-sonnet-4-6"
_PROMPT_PATH = Path(__file__).resolve().parents[2] / "prompts" / "briefings.md"


@dataclass
class Citation:
    call_id: str
    t_start_s: int
    t_end_s: int
    quote: str


@dataclass
class Briefing:
    answer_md: str
    citations: list[Citation]


def _system_preamble() -> list[dict]:
    return [
        {
            "type": "text",
            "text": _PROMPT_PATH.read_text(encoding="utf-8"),
            "cache_control": {"type": "ephemeral"},
        }
    ]


def _compose(
    client: anthropic.Anthropic,
    *,
    rows_block: str,
    spans_block: str,
    instruction: str,
) -> str:
    """Run a single Sonnet 4.6 composition call.

    Returns the markdown answer. Citations are extracted from the answer text
    by the caller using the `[call_id:t_start]` chip pattern.
    """
    response = client.messages.create(
        model=BRIEFING_MODEL,
        max_tokens=2048,
        thinking={"type": "adaptive"},
        system=_system_preamble(),
        messages=[
            {
                "role": "user",
                "content": (
                    f"{instruction}\n\n"
                    "## Rows from the entity store\n\n"
                    f"{rows_block}\n\n"
                    "## Supporting transcript spans\n\n"
                    f"{spans_block}\n\n"
                    "Compose the answer now."
                ),
            }
        ],
    )
    out = []
    for b in response.content:
        if b.type == "text":
            out.append(b.text)
    return "\n".join(out).strip()


# --- Composers ---------------------------------------------------------------


def tldr(repo: GrowthCloudRepo, client: anthropic.Anthropic, *, workspace_id: str) -> Briefing:
    """'What's the TLDR on our work with this client right now?'

    Composition: open decisions + open commitments + running experiments + top stakeholders.
    """
    decisions = repo.list_decisions(workspace_id, status="open", limit=10)
    commitments = repo.list_open_commitments(workspace_id, limit=10)
    experiments = repo.list_experiments(workspace_id, status="running", limit=10)
    stakeholders = repo.list_top_stakeholders(workspace_id, limit=8)
    spans = repo.fetch_spans_for_rows(decisions + commitments + experiments, max_chars=4000)

    rows_block = json.dumps(
        {
            "decisions": [d for d in decisions],
            "commitments": [c for c in commitments],
            "experiments": [e for e in experiments],
            "stakeholders": [s for s in stakeholders],
        },
        indent=2,
        default=str,
    )
    spans_block = _format_spans(spans)
    instruction = (
        "Produce a 5-bullet TLDR of the current state of this account. "
        "Each bullet covers one of: (1) most important open decision, "
        "(2) biggest open commitment, (3) most consequential running experiment, "
        "(4) key stakeholder dynamic to know, (5) anything else load-bearing. "
        "If a category has no data, replace the bullet with a different load-bearing item — "
        "do not invent."
    )
    answer = _compose(client, rows_block=rows_block, spans_block=spans_block, instruction=instruction)
    return Briefing(answer_md=answer, citations=_extract_citations(answer, spans))


def delta(
    repo: GrowthCloudRepo,
    client: anthropic.Anthropic,
    *,
    workspace_id: str,
    since: date,
    person: str | None = None,
) -> Briefing:
    """'Any developments since my last call with $person / since $date?'"""
    decisions = repo.list_decisions(workspace_id, since=since, limit=20)
    commitments = repo.list_commitments(workspace_id, since=since, limit=20)
    experiments = repo.list_experiment_updates(workspace_id, since=since, limit=20)
    perf = repo.list_performance_signals(workspace_id, since=since, limit=20)
    rows = decisions + commitments + experiments + perf
    spans = repo.fetch_spans_for_rows(rows, max_chars=5000)

    rows_block = json.dumps(
        {
            "decisions": decisions,
            "commitments": commitments,
            "experiment_updates": experiments,
            "performance_signals": perf,
        },
        indent=2,
        default=str,
    )
    spans_block = _format_spans(spans)
    person_clause = f" (specifically related to {person})" if person else ""
    instruction = (
        f"What's new on this account since {since.isoformat()}{person_clause}? "
        "Group by workstream. Lead with the most consequential change. "
        "If nothing material has happened in a workstream, omit it — do not pad."
    )
    answer = _compose(client, rows_block=rows_block, spans_block=spans_block, instruction=instruction)
    return Briefing(answer_md=answer, citations=_extract_citations(answer, spans))


def stakeholder_map(
    repo: GrowthCloudRepo, client: anthropic.Anthropic, *, workspace_id: str
) -> Briefing:
    """'Who's calling the shots on what?' — cluster by company + seniority."""
    people = repo.list_people_with_call_stats(workspace_id)
    spans = repo.fetch_authority_signal_spans(workspace_id, max_chars=4000)

    rows_block = json.dumps(people, indent=2, default=str)
    spans_block = _format_spans(spans)
    instruction = (
        "Produce the stakeholder map for this account. Group by company. "
        "Within each company, order by seniority (highest first). For each person give: "
        "role, seniority, authority signals (what they own or can sign off on), and "
        "average sentiment. Flag anyone whose sentiment is negative or mixed."
    )
    answer = _compose(client, rows_block=rows_block, spans_block=spans_block, instruction=instruction)
    return Briefing(answer_md=answer, citations=_extract_citations(answer, spans))


def onboarding(
    repo: GrowthCloudRepo, client: anthropic.Anthropic, *, workspace_id: str, user_role: str
) -> Briefing:
    """'I just joined the account, where do I fit in?'

    user_role: free text like 'paid search lead' or 'creative strategist'.
    We don't try to be clever — we feed the role to the LLM and let it pick.
    """
    workstreams = repo.list_workstreams(workspace_id)
    open_commitments = repo.list_open_commitments(workspace_id, limit=30)
    open_decisions = repo.list_decisions(workspace_id, status="open", limit=20)
    rows = open_commitments + open_decisions
    spans = repo.fetch_spans_for_rows(rows, max_chars=4000)

    rows_block = json.dumps(
        {
            "workstreams": workstreams,
            "open_commitments": open_commitments,
            "open_decisions": open_decisions,
        },
        indent=2,
        default=str,
    )
    spans_block = _format_spans(spans)
    instruction = (
        f"A new team member is joining this account. Their role is: \"{user_role}\". "
        "Produce a 'where do I fit in' briefing with these sections: "
        "(1) Workstreams that match your role and are active. "
        "(2) Open commitments and decisions in your area, with owners. "
        "(3) Adjacent workstreams you should know about and who runs them. "
        "Keep it operator-readable in under 60 seconds."
    )
    answer = _compose(client, rows_block=rows_block, spans_block=spans_block, instruction=instruction)
    return Briefing(answer_md=answer, citations=_extract_citations(answer, spans))


# --- Helpers -----------------------------------------------------------------


def _format_spans(spans: list[dict]) -> str:
    """Render transcript spans for the LLM, with explicit citation chips."""
    if not spans:
        return "(no transcript spans available)"
    lines = []
    for s in spans:
        chip = f"[{s['call_id']}:{s['t_start_s']}]"
        lines.append(f"{chip} {s.get('speaker') or 'Unknown'}: {s['content']}")
    return "\n".join(lines)


def _extract_citations(answer_md: str, spans: list[dict]) -> list[Citation]:
    """Pull `[call_id:t_start]` chips out of the answer and resolve them to spans.

    The renderer turns these into clickable links to wiki/calls/<id>.md#tNNN.
    """
    import re

    chip_re = re.compile(r"\[([a-z0-9\-]+):(\d+)\]")
    by_key = {(s["call_id"], int(s["t_start_s"])): s for s in spans}
    seen = set()
    out: list[Citation] = []
    for m in chip_re.finditer(answer_md):
        key = (m.group(1), int(m.group(2)))
        if key in seen:
            continue
        seen.add(key)
        s = by_key.get(key)
        if not s:
            # Citation referenced a span we didn't include in the prompt — skip rather
            # than fabricate. The UI shows it as an unresolved chip.
            continue
        out.append(
            Citation(
                call_id=s["call_id"],
                t_start_s=int(s["t_start_s"]),
                t_end_s=int(s.get("t_end_s", s["t_start_s"])),
                quote=s["content"][:200],
            )
        )
    return out
