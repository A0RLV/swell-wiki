"""Filesystem-level AID loader. Pure functions over the workspace, no DB."""

from __future__ import annotations

import re
from datetime import date, datetime
from pathlib import Path
from typing import Iterator

import yaml


def workspace_clients(workspace: Path) -> list[str]:
    root = workspace / "clients"
    if not root.exists():
        return []
    return sorted(p.name for p in root.iterdir() if p.is_dir())


def iter_aids(workspace: Path, client: str) -> Iterator[tuple[Path, dict]]:
    """Yield (path, frontmatter_dict) for each AID under a client."""
    calls_dir = workspace / "clients" / client / "calls"
    if not calls_dir.exists():
        return
    for p in sorted(calls_dir.glob("*.md")):
        fm = _read_frontmatter(p)
        if fm is not None:
            yield p, fm


def load_aids(
    workspace: Path,
    client: str,
    since: date | None = None,
    until: date | None = None,
) -> list[tuple[Path, dict]]:
    out: list[tuple[Path, dict]] = []
    for path, fm in iter_aids(workspace, client):
        call_date = _parse_date(fm.get("call_date"))
        if call_date is None:
            continue
        if since and call_date < since:
            continue
        if until and call_date > until:
            continue
        out.append((path, fm))
    out.sort(key=lambda x: _parse_date(x[1].get("call_date")) or date.min)
    return out


def _read_frontmatter(path: Path) -> dict | None:
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return None
    m = re.match(r"^---\n(.*?)\n---\n", text, re.S)
    if not m:
        return None
    try:
        data = yaml.safe_load(m.group(1))
    except yaml.YAMLError:
        return None
    return data if isinstance(data, dict) else None


def _parse_date(v) -> date | None:
    if isinstance(v, date) and not isinstance(v, datetime):
        return v
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, str):
        try:
            return date.fromisoformat(v[:10])
        except ValueError:
            return None
    return None


def cite(path: Path, workspace: Path, timestamp: str | None = None) -> str:
    """Render a footnote-style citation pointing back to an AID."""
    rel = path.relative_to(workspace).as_posix()
    ts = f" @ {timestamp}" if timestamp else ""
    return f"[{rel}{ts}]({rel})"
