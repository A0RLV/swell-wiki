"""Fathom transcript ingestion.

Two input shapes supported:
  1. JSON export from Fathom (or its API):
       {"id": "...", "title": "...", "started_at": "...", "duration_seconds": ...,
        "fathom_url": "...", "attendees": [{"name": "..."}],
        "transcript": [{"start_seconds": 12, "end_seconds": 18,
                        "speaker": "Mar", "text": "..."}]}
  2. Cyril's normalized form — already in the segment shape below — passed in directly.

Output:
  - A list of transcript segments with `seg_index`, `t_start_s`, `t_end_s`,
    `speaker`, `content`. Fed to the extractor and to SQLite.
  - A markdown rendering of the raw transcript at `sources/calls/<date>-<slug>.md`
    that llmwiki's existing indexer will chunk and FTS for free.

We deliberately keep this thin — the extractor + state compiler do all the
interesting work. This is just normalization.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any


@dataclass
class IngestedCall:
    call_id: str
    title: str
    date: str
    duration_s: int | None
    fathom_url: str | None
    attendees: list[str]
    segments: list[dict]   # [{seg_index, t_start_s, t_end_s, speaker, content}]
    raw_markdown: str      # for sources/calls/<date>-<slug>.md
    raw_path: str          # relative path under sources/


_SLUG_RE = re.compile(r"[^a-z0-9]+")


def _slugify(s: str) -> str:
    return _SLUG_RE.sub("-", s.lower()).strip("-")[:60] or "untitled"


def normalize_transcript(fathom_export: dict[str, Any]) -> IngestedCall:
    """Convert a Fathom JSON export into the canonical IngestedCall shape."""
    title = fathom_export.get("title", "Untitled call")
    started_at = fathom_export.get("started_at") or fathom_export.get("date")
    if not started_at:
        raise ValueError("Fathom export missing started_at/date")
    date = datetime.fromisoformat(started_at.replace("Z", "+00:00")).date().isoformat()

    call_id = fathom_export.get("id") or f"{date}-{_slugify(title)}"
    duration_s = fathom_export.get("duration_seconds")
    fathom_url = fathom_export.get("fathom_url")

    attendees = []
    for a in fathom_export.get("attendees") or []:
        if isinstance(a, str):
            attendees.append(a)
        else:
            name = a.get("name") or a.get("email")
            if name:
                attendees.append(name)

    segments: list[dict] = []
    for i, seg in enumerate(fathom_export.get("transcript") or []):
        content = (seg.get("text") or "").strip()
        if not content:
            continue
        segments.append({
            "seg_index": i,
            "t_start_s": int(seg.get("start_seconds", 0)),
            "t_end_s": int(seg.get("end_seconds", seg.get("start_seconds", 0))),
            "speaker": seg.get("speaker"),
            "content": content,
        })

    raw_lines = [
        f"# {title}",
        f"_Recorded {date}._",
        "",
    ]
    if fathom_url:
        raw_lines.append(f"[Watch in Fathom]({fathom_url})")
        raw_lines.append("")
    for s in segments:
        mins, secs = divmod(s["t_start_s"], 60)
        speaker = s["speaker"] or "Unknown"
        raw_lines.append(f"**[{mins:02d}:{secs:02d}] {speaker}:** {s['content']}")
        raw_lines.append("")
    raw_markdown = "\n".join(raw_lines)
    raw_path = f"sources/calls/{date}-{_slugify(title)}.md"

    return IngestedCall(
        call_id=call_id,
        title=title,
        date=date,
        duration_s=duration_s,
        fathom_url=fathom_url,
        attendees=attendees,
        segments=segments,
        raw_markdown=raw_markdown,
        raw_path=raw_path,
    )


def write_raw_transcript(workspace_root: Path, call: IngestedCall) -> Path:
    """Persist the raw transcript so llmwiki's indexer picks it up.

    Lives under `sources/calls/` rather than `wiki/` — llmwiki treats anything
    outside `wiki/` as a source rather than a generated page.
    """
    path = workspace_root / call.raw_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(call.raw_markdown, encoding="utf-8")
    return path
