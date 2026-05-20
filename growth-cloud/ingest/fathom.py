"""Fathom → AID ingest pipeline.

Pulls call transcripts from Fathom, asks Claude Sonnet 4.5 to extract a
structured AID, validates against the pydantic schema, writes the AID as a
markdown file into the llmwiki workspace, and (optionally) hands the path to
a `on_aid_written` callback (the recompile hook).

Designed to run as a poller (every 15 min) or be invoked by a webhook handler.
Keep the surface area small — the wiki layer is owned by the recompile worker
via MCP, not by this module.

The HTTP shape against Fathom's API is **UNVERIFIED** — see plans/Task 21.
The `FathomTransport` seam lets ingest run end-to-end against fixtures while
the live API is validated.
"""

from __future__ import annotations

import abc
import asyncio
import hashlib
import json
import logging
import os
import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import httpx
from anthropic import AsyncAnthropic

from schema.aid import AID
from ingest.prompts import EXTRACTION_SYSTEM, build_user_prompt
from ingest.writer import write_aid

logger = logging.getLogger(__name__)

FATHOM_API = "https://api.fathom.ai/external/v1"
DEFAULT_MODEL = "claude-sonnet-4-5-20250929"
EXTRACTION_TIMEOUT_S = 120


@dataclass
class FathomCall:
    fathom_id: str
    title: str
    started_at: datetime
    duration_seconds: int
    transcript: str
    invitee_emails: list[str]


# ── Transport seam ────────────────────────────────────────────────────────────

class FathomTransport(abc.ABC):
    """Low-level Fathom IO. Implementations return raw dicts in the shape the
    rest of the pipeline expects. Two impls: HTTP (live, UNVERIFIED) and
    Fixture (deterministic, used by tests and dev runs)."""

    @abc.abstractmethod
    async def list_recent(self, since: datetime) -> list[dict[str, Any]]: ...

    @abc.abstractmethod
    async def fetch_call(self, fathom_id: str) -> dict[str, Any]: ...


class HTTPFathomTransport(FathomTransport):
    """Hits Fathom's external API. **UNVERIFIED shape** — pending Task 21."""

    def __init__(self, api_key: str, http: httpx.AsyncClient | None = None):
        self._key = api_key
        self._http = http or httpx.AsyncClient(timeout=30.0)

    async def list_recent(self, since: datetime) -> list[dict[str, Any]]:
        r = await self._http.get(
            f"{FATHOM_API}/calls",
            params={"recorded_after": since.isoformat()},
            headers={"X-Api-Key": self._key},
        )
        r.raise_for_status()
        return r.json().get("items", [])

    async def fetch_call(self, fathom_id: str) -> dict[str, Any]:
        r = await self._http.get(
            f"{FATHOM_API}/calls/{fathom_id}",
            headers={"X-Api-Key": self._key},
            params={"include": "transcript,invitees"},
        )
        r.raise_for_status()
        return r.json()


class FixtureFathomTransport(FathomTransport):
    """Reads JSON fixtures from a directory.

    Layout::

        <root>/
          list.json              # array of {"id": "...", "started_at": "...", "invitees": [...]}
          calls/<fathom_id>.json # one file per call detail (transcript, title, ...)

    Used by `growth-cloud ingest --fixtures <dir>` and by tests.
    """

    def __init__(self, root: Path):
        self.root = Path(root)
        if not self.root.is_dir():
            raise FileNotFoundError(f"Fathom fixture root not found: {self.root}")

    async def list_recent(self, since: datetime) -> list[dict[str, Any]]:
        listing = self.root / "list.json"
        if not listing.is_file():
            return []
        items = json.loads(listing.read_text())
        # Mirror the API contract: filter by `started_at >= since`.
        keep: list[dict[str, Any]] = []
        for item in items:
            ts_str = item.get("started_at")
            if not ts_str:
                continue
            ts = datetime.fromisoformat(ts_str)
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            if ts >= since:
                keep.append(item)
        return keep

    async def fetch_call(self, fathom_id: str) -> dict[str, Any]:
        path = self.root / "calls" / f"{fathom_id}.json"
        if not path.is_file():
            raise FileNotFoundError(f"No fixture for call {fathom_id}: {path}")
        return json.loads(path.read_text())


# ── Client (transport-agnostic) ───────────────────────────────────────────────

class FathomClient:
    """Thin parser over a FathomTransport. Returns typed `FathomCall`s."""

    def __init__(self, transport: FathomTransport):
        self._transport = transport

    async def list_recent(self, since: datetime) -> list[dict[str, Any]]:
        return await self._transport.list_recent(since)

    async def fetch_transcript(self, fathom_id: str) -> FathomCall:
        data = await self._transport.fetch_call(fathom_id)
        started = datetime.fromisoformat(data["started_at"])
        if started.tzinfo is None:
            started = started.replace(tzinfo=timezone.utc)
        return FathomCall(
            fathom_id=fathom_id,
            title=data["title"],
            started_at=started,
            duration_seconds=int(data.get("duration_seconds", 0)),
            transcript=data["transcript"]["text"] if isinstance(data.get("transcript"), dict) else data.get("transcript", ""),
            invitee_emails=[i["email"] for i in data.get("invitees", [])],
        )


# ── Extraction ────────────────────────────────────────────────────────────────

class AIDExtractor:
    """Calls Anthropic and validates the response against the AID schema.

    Accepts either a `Settings`-like object (with `ANTHROPIC_API_KEY` and
    `ANTHROPIC_MODEL`) or an explicit `AsyncAnthropic`+model pair. The
    settings path is preferred at the CLI; the explicit path is preserved
    for tests that swap the client.
    """

    def __init__(
        self,
        settings_or_client,
        *,
        model: str | None = None,
    ):
        if hasattr(settings_or_client, "ANTHROPIC_API_KEY"):
            settings = settings_or_client
            self._anthropic = AsyncAnthropic(api_key=settings.ANTHROPIC_API_KEY)
            self._model = model or settings.ANTHROPIC_MODEL
        else:
            self._anthropic = settings_or_client
            self._model = model or DEFAULT_MODEL

    async def extract(self, client_slug: str, call: FathomCall) -> AID:
        resp = await self._anthropic.messages.create(
            model=self._model,
            max_tokens=8192,
            system=EXTRACTION_SYSTEM,
            messages=[{
                "role": "user",
                "content": build_user_prompt(client_slug, call.fathom_id, call.transcript),
            }],
            timeout=EXTRACTION_TIMEOUT_S,
        )
        raw = "".join(b.text for b in resp.content if b.type == "text")
        payload = _strip_json_fence(raw)
        data = json.loads(payload)

        # Inject fields the model shouldn't have to guess
        data.setdefault("client", client_slug)
        data.setdefault("fathom_id", call.fathom_id)
        data.setdefault("title", call.title)
        data.setdefault("call_date", call.started_at.date().isoformat())
        data.setdefault("duration_seconds", call.duration_seconds)

        # Backfill stable IDs for items the model may have left bare
        _ensure_ids(data, "decisions", call.fathom_id)
        _ensure_ids(data, "commitments", call.fathom_id)
        _ensure_ids(data, "experiments", call.fathom_id)

        return AID.model_validate(data)


def _strip_json_fence(s: str) -> str:
    m = re.search(r"```(?:json)?\s*(.*?)```", s, re.S)
    return (m.group(1) if m else s).strip()


def _ensure_ids(data: dict, key: str, call_id: str) -> None:
    for i, item in enumerate(data.get(key, [])):
        if not item.get("id"):
            seed = f"{call_id}:{key}:{i}:{item.get('statement') or item.get('hypothesis') or ''}"
            item["id"] = hashlib.sha1(seed.encode()).hexdigest()[:10]


# ── Orchestrator ──────────────────────────────────────────────────────────────

class GrowthCloudIngest:
    """Top-level orchestrator. One instance per workspace."""

    def __init__(
        self,
        workspace: Path,
        client_router: "ClientRouter",
        fathom: FathomClient,
        extractor: AIDExtractor,
        on_aid_written=None,
    ):
        self.workspace = workspace
        self.client_router = client_router
        self.fathom = fathom
        self.extractor = extractor
        # async callable: (client_slug, aid_path) -> None
        self.on_aid_written = on_aid_written

    async def poll_once(self, lookback: timedelta = timedelta(hours=24)) -> list[Path]:
        since = datetime.now(tz=timezone.utc) - lookback
        items = await self.fathom.list_recent(since)
        written: list[Path] = []
        for item in items:
            fathom_id = item["id"]
            client_slug = self.client_router.route(item)
            if client_slug is None:
                logger.info("Skipping %s — no client route", fathom_id)
                continue
            if _already_ingested(self.workspace, client_slug, fathom_id):
                continue
            try:
                path = await self._ingest_one(client_slug, fathom_id)
                written.append(path)
                if self.on_aid_written:
                    await self.on_aid_written(client_slug, path)
            except Exception:
                logger.exception("Ingest failed for %s", fathom_id)
        return written

    async def _ingest_one(self, client_slug: str, fathom_id: str) -> Path:
        call = await self.fathom.fetch_transcript(fathom_id)
        aid = await self.extractor.extract(client_slug, call)
        return write_aid(self.workspace, aid)


class ClientRouter:
    """Maps a Fathom call to a client slug.

    MVP: route by invitee email domain (`@target-darts.com` → `target-darts`).
    Production: combine domain + calendar metadata + manual override file.
    """

    def __init__(self, domain_map: dict[str, str], default: str | None = None):
        self._domains = {d.lower(): slug for d, slug in domain_map.items()}
        self._default = default

    def route(self, fathom_item: dict[str, Any]) -> str | None:
        for inv in fathom_item.get("invitees", []):
            email = (inv.get("email") or "").lower()
            if "@" not in email:
                continue
            domain = email.split("@", 1)[1]
            if domain in self._domains:
                return self._domains[domain]
        return self._default


def _already_ingested(workspace: Path, client_slug: str, fathom_id: str) -> bool:
    calls_dir = workspace / "clients" / client_slug / "calls"
    if not calls_dir.exists():
        return False
    needle = f"fathom_id: {fathom_id}"
    for p in calls_dir.glob("*.md"):
        head = p.read_text(errors="ignore").split("\n---", 2)
        if len(head) >= 2 and needle in head[0]:
            return True
    return False
