"""Atomic Insight Document — the marketing-ops schema Cyril described.

This is the typed output the extractor emits per Fathom call. Every entity
includes a (t_start_s, t_end_s) anchor pointing back into the transcript so
the briefings layer can render sourced citations.

Used three ways:
  1. As the `strict: true` tool input_schema for the Sonnet 4.6 extractor.
  2. As the validation layer between extractor output and the SQLite upsert.
  3. As the wire format for the briefings API responses (subset thereof).
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


Seniority = Literal[
    "ic", "lead", "manager", "director", "vp", "cxo", "founder", "unknown"
]
Sentiment = Literal["positive", "neutral", "negative", "mixed", "unknown"]


class CallMetadata(BaseModel):
    id: str
    date: str = Field(description="ISO-8601 date")
    title: str
    attendees: list[str] = Field(default_factory=list)
    duration_s: int | None = None
    fathom_url: str | None = None


class Stakeholder(BaseModel):
    name: str
    company: str | None = None
    role: str | None = None
    seniority: Seniority = "unknown"
    sentiment: Sentiment = "unknown"
    talk_time_pct: float | None = Field(
        default=None, ge=0, le=1, description="Fraction of total speaking time on this call"
    )
    authority_signals: list[str] = Field(
        default_factory=list,
        description="Short phrases from the call that indicate decision authority",
    )


class Decision(BaseModel):
    summary: str = Field(description="One sentence. Active voice. State the decision, not the discussion.")
    owner: str | None = Field(default=None, description="Stakeholder name if a clear owner was named")
    deadline: str | None = Field(default=None, description="ISO-8601 if a date was given")
    status: Literal["open", "in_progress", "done", "superseded", "dropped"] = "open"
    workstream: str | None = None
    t_start_s: int
    t_end_s: int
    confidence: float = Field(default=0.8, ge=0, le=1)


class Commitment(BaseModel):
    summary: str = Field(description='Format: "{owner} will {do thing}". One sentence.')
    owner: str | None = None
    due: str | None = None
    status: Literal["open", "done", "overdue", "dropped"] = "open"
    workstream: str | None = None
    t_start_s: int
    t_end_s: int


class Experiment(BaseModel):
    name: str = Field(description="Slug-ish, reusable across calls (e.g. 'de-paid-search-alarmanlage-test')")
    hypothesis: str | None = None
    market: str | None = None
    channel: str | None = None
    status: Literal["proposed", "running", "concluded", "killed"] = "proposed"
    t_start_s: int
    t_end_s: int


class Workstream(BaseModel):
    name: str
    status: str | None = Field(default=None, description="Free text, e.g. 'on track', 'blocked on creative'")
    key_update: str | None = None
    t_start_s: int
    t_end_s: int


class PerformanceSignal(BaseModel):
    metric: str = Field(description="e.g. 'CPA', 'ROAS', 'CTR'")
    value: str | None = Field(default=None, description="Raw value as stated (string to keep units)")
    direction: Literal["up", "down", "flat", "unknown"] = "unknown"
    market: str | None = None
    channel: str | None = None
    note: str | None = None
    t_start_s: int
    t_end_s: int


class OpenQuestion(BaseModel):
    question: str
    who_to_ask: str | None = None
    t_start_s: int
    t_end_s: int


class AID(BaseModel):
    """Atomic Insight Document — one per Fathom call."""

    call: CallMetadata
    summary_bullets: list[str] = Field(
        description="3 bullets, each one sentence. The TLDR of this call.",
        min_length=1,
        max_length=5,
    )
    stakeholders: list[Stakeholder] = Field(default_factory=list)
    decisions: list[Decision] = Field(default_factory=list)
    commitments: list[Commitment] = Field(default_factory=list)
    experiments: list[Experiment] = Field(default_factory=list)
    workstreams: list[Workstream] = Field(default_factory=list)
    performance_signals: list[PerformanceSignal] = Field(default_factory=list)
    open_questions: list[OpenQuestion] = Field(default_factory=list)


def aid_tool_input_schema() -> dict:
    """JSON Schema for the `record_aid` tool the extractor calls.

    Pydantic's `.model_json_schema()` is close but emits `$defs`/`$ref` and a few
    keywords (`title`, `default`, integer `minimum`/`maximum`, `minLength`/`maxLength`)
    that Anthropic's strict-tool-use validator rejects. We inline refs and strip
    unsupported keywords so the schema lands clean.
    """
    raw = AID.model_json_schema()
    defs = raw.pop("$defs", {})

    def _inline(node):
        if isinstance(node, dict):
            if "$ref" in node:
                ref = node["$ref"].split("/")[-1]
                return _inline(defs[ref])
            out = {}
            for k, v in node.items():
                if k in {
                    "title",
                    "default",
                    "minimum",
                    "maximum",
                    "exclusiveMinimum",
                    "exclusiveMaximum",
                    "minLength",
                    "maxLength",
                    "minItems",
                    "maxItems",
                }:
                    continue
                out[k] = _inline(v)
            # Strict mode requires explicit additionalProperties: false on objects.
            if out.get("type") == "object" and "additionalProperties" not in out:
                out["additionalProperties"] = False
            # Strict mode requires every property to be in `required`. Pydantic-
            # optional fields are already typed as nullable via anyOf, so this
            # doesn't make them mandatory at the value level — just present-as-null.
            if "properties" in out:
                out["required"] = list(out["properties"].keys())
            return out
        if isinstance(node, list):
            return [_inline(v) for v in node]
        return node

    return _inline(raw)
