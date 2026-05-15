"""FastAPI router for briefings — mounts as `/briefings` under llmwiki's main app.

In llmwiki's `api/main.py` add:

    from .routes import briefings as briefings_routes
    app.include_router(briefings_routes.router)

Endpoints:
  GET /briefings/{workspace_id}/tldr
  GET /briefings/{workspace_id}/delta?since=YYYY-MM-DD&person=name
  GET /briefings/{workspace_id}/stakeholders
  GET /briefings/{workspace_id}/onboarding?role=...
"""

from __future__ import annotations

from dataclasses import asdict
from datetime import date

import anthropic
from fastapi import APIRouter, Depends, HTTPException, Query

from ..db.growth_cloud import GrowthCloudRepo
from ..services import briefings as briefings_svc

# Both deps live in llmwiki — we depend on its conventions, not re-define them.
# `get_repo` returns a GrowthCloudRepo against the workspace's index.db.
# `get_anthropic` returns an `anthropic.Anthropic` client using the workspace's key.
# Wire these into llmwiki's existing dependency injection (api/deps.py).
from ..deps import get_repo, get_anthropic  # type: ignore  # noqa: F401

router = APIRouter(prefix="/briefings", tags=["briefings"])


@router.get("/{workspace_id}/tldr")
def get_tldr(
    workspace_id: str,
    repo: GrowthCloudRepo = Depends(get_repo),
    client: anthropic.Anthropic = Depends(get_anthropic),
):
    briefing = briefings_svc.tldr(repo, client, workspace_id=workspace_id)
    return {"answer_md": briefing.answer_md,
            "citations": [asdict(c) for c in briefing.citations]}


@router.get("/{workspace_id}/delta")
def get_delta(
    workspace_id: str,
    since: date = Query(..., description="ISO-8601 date"),
    person: str | None = Query(default=None),
    repo: GrowthCloudRepo = Depends(get_repo),
    client: anthropic.Anthropic = Depends(get_anthropic),
):
    briefing = briefings_svc.delta(repo, client, workspace_id=workspace_id,
                                   since=since, person=person)
    return {"answer_md": briefing.answer_md,
            "citations": [asdict(c) for c in briefing.citations]}


@router.get("/{workspace_id}/stakeholders")
def get_stakeholders(
    workspace_id: str,
    repo: GrowthCloudRepo = Depends(get_repo),
    client: anthropic.Anthropic = Depends(get_anthropic),
):
    briefing = briefings_svc.stakeholder_map(repo, client, workspace_id=workspace_id)
    return {"answer_md": briefing.answer_md,
            "citations": [asdict(c) for c in briefing.citations]}


@router.get("/{workspace_id}/onboarding")
def get_onboarding(
    workspace_id: str,
    role: str = Query(..., description="The new team member's role"),
    repo: GrowthCloudRepo = Depends(get_repo),
    client: anthropic.Anthropic = Depends(get_anthropic),
):
    if not role.strip():
        raise HTTPException(400, "role is required")
    briefing = briefings_svc.onboarding(repo, client, workspace_id=workspace_id, user_role=role)
    return {"answer_md": briefing.answer_md,
            "citations": [asdict(c) for c in briefing.citations]}
