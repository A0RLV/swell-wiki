"""AID (Augmented Interaction Document) schema.

One AID = one Fathom call processed into a structured document. AIDs live in the
llmwiki workspace under `/clients/<client>/calls/YYYY-MM-DD-<slug>.md` and are the
unit the wiki layer compounds over.

The schema is intentionally narrow and marketing-ops-shaped — every field maps to
a downstream MVP query. If a field doesn't power briefing/stakeholders/commitments/
decisions, it doesn't belong here.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field


Direction = Literal["up", "down", "flat", "unknown"]
Valence = Literal["positive", "neutral", "negative"]
CommitmentStatus = Literal["open", "done", "blocked", "dropped"]
DecisionStatus = Literal["proposed", "agreed", "reversed"]
ExperimentStatus = Literal["proposed", "running", "concluded", "dropped"]


class Participant(BaseModel):
    name: str
    role: Optional[str] = None
    org: Optional[str] = None
    swell_side: bool = False


class Decision(BaseModel):
    id: str  # stable hash of (call_id, ordinal)
    statement: str
    owner: Optional[str] = None
    status: DecisionStatus = "agreed"
    workstream: Optional[str] = None
    source_timestamp: Optional[str] = None  # "HH:MM:SS" into call


class Commitment(BaseModel):
    id: str
    statement: str
    owner: Optional[str] = None
    due: Optional[date] = None
    status: CommitmentStatus = "open"
    source_timestamp: Optional[str] = None


class Experiment(BaseModel):
    id: str
    hypothesis: str
    status: ExperimentStatus = "proposed"
    owner: Optional[str] = None
    workstream: Optional[str] = None
    source_timestamp: Optional[str] = None


class PerformanceSignal(BaseModel):
    metric: str
    market: Optional[str] = None
    channel: Optional[str] = None
    direction: Direction = "unknown"
    magnitude: Optional[str] = None  # free text: "16M impressions", "+12% CTR"
    source_timestamp: Optional[str] = None


class OpenQuestion(BaseModel):
    question: str
    owner: Optional[str] = None
    source_timestamp: Optional[str] = None


class SentimentBeat(BaseModel):
    person: str
    topic: str
    valence: Valence
    note: Optional[str] = None
    source_timestamp: Optional[str] = None


class AID(BaseModel):
    """Top-level call document. Serialises 1:1 to YAML frontmatter."""

    client: str
    call_date: date
    fathom_id: str
    title: str
    duration_seconds: Optional[int] = None
    participants: list[Participant] = Field(default_factory=list)
    workstreams: list[str] = Field(default_factory=list)
    markets: list[str] = Field(default_factory=list)
    channels: list[str] = Field(default_factory=list)
    decisions: list[Decision] = Field(default_factory=list)
    commitments: list[Commitment] = Field(default_factory=list)
    experiments: list[Experiment] = Field(default_factory=list)
    performance_signals: list[PerformanceSignal] = Field(default_factory=list)
    open_questions: list[OpenQuestion] = Field(default_factory=list)
    sentiment: list[SentimentBeat] = Field(default_factory=list)
    summary: str = ""  # one-paragraph synthesis, goes in the markdown body
    extracted_at: datetime = Field(default_factory=datetime.utcnow)
    schema_version: str = "1.0"
