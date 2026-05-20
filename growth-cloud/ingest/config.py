"""Centralized settings for Growth Cloud ingest + recompile.

Replaces scattered `os.environ[...]` reads with one pydantic-settings model,
mirroring llmwiki/api/config.py:1-43. Loads .env from growth-cloud/.env.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_REPO_ROOT = Path(__file__).resolve().parent.parent  # growth-cloud/


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(_REPO_ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Required
    GROWTH_CLOUD_WORKSPACE: str

    # Required for live ingest; not required for fixture-only runs (the CLI
    # tolerates an empty value when --fixtures is passed).
    ANTHROPIC_API_KEY: str = ""
    FATHOM_API_KEY: str = ""

    # Optional with defaults
    ANTHROPIC_MODEL: str = "claude-sonnet-4-5-20250929"
    CLIENT_DOMAIN_MAP: dict[str, str] = Field(default_factory=dict)
    CLIENT_DEFAULT: str | None = None
    INGEST_LOOKBACK_HOURS: int = 24
    INGEST_POLL_INTERVAL_MIN: int = 15

    @field_validator("CLIENT_DOMAIN_MAP", mode="before")
    @classmethod
    def _parse_domain_map(cls, v: Any) -> Any:
        if isinstance(v, str):
            v = v.strip()
            if not v:
                return {}
            return json.loads(v)
        return v
