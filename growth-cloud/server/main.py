"""Growth Cloud MCP server.

Wraps llmwiki's local MCP server with Growth-Cloud-specific tools and guide.
Run this *instead* of `llmwiki mcp` when Claude connects to a Growth Cloud
workspace.

The substrate is unchanged:
- filesystem is the source of truth (workspace path)
- SQLite is the rebuildable index (.llmwiki/index.db)
- llmwiki's read/write/search/delete tools are still registered

Growth Cloud adds:
- `guide` is overridden with Growth-Cloud instructions
- `briefing`, `stakeholders`, `commitments`, `decisions`, `clients` tools

Usage:
    python -m server.main --workspace ~/swell-growth-cloud
    python -m server.main --workspace ~/swell-growth-cloud --llmwiki-root /path/to/llmwiki
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys
import uuid
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("growth-cloud")


def _parse() -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument("--workspace", required=True)
    p.add_argument(
        "--llmwiki-root",
        default=None,
        help=(
            "Path to the llmwiki checkout. If unset, falls back to "
            "$LLMWIKI_ROOT, then to a sibling `../llmwiki/` directory."
        ),
    )
    return p.parse_args()


def resolve_llmwiki_root(explicit: str | None) -> Path:
    """Resolve the llmwiki checkout path. Validates structure before returning.

    Priority:
      1. ``--llmwiki-root`` CLI flag (``explicit``)
      2. ``LLMWIKI_ROOT`` environment variable
      3. Sibling ``../llmwiki/`` relative to this file (repo-layout default)

    Raises ``SystemExit`` with an actionable message if no valid root is found.
    """
    candidates: list[tuple[str, Path]] = []
    if explicit:
        candidates.append(("--llmwiki-root", Path(explicit).expanduser().resolve()))
    if os.environ.get("LLMWIKI_ROOT"):
        candidates.append(
            ("$LLMWIKI_ROOT", Path(os.environ["LLMWIKI_ROOT"]).expanduser().resolve())
        )
    candidates.append(
        ("sibling default", (Path(__file__).resolve().parents[2] / "llmwiki").resolve())
    )

    required_files = ("mcp/vaultfs/__init__.py", "shared/sqlite_schema.sql")
    tried: list[str] = []
    for source, path in candidates:
        missing = [f for f in required_files if not (path / f).is_file()]
        if not missing:
            logger.info("Using llmwiki root from %s: %s", source, path)
            return path
        tried.append(f"  {source} -> {path}  (missing: {', '.join(missing)})")

    sys.stderr.write(
        "ERROR: could not locate a valid llmwiki checkout. Tried:\n"
        + "\n".join(tried)
        + "\n\nSet LLMWIKI_ROOT, pass --llmwiki-root, or clone llmwiki as a "
        "sibling of growth-cloud/.\n"
    )
    raise SystemExit(2)


async def _init(workspace: Path, llmwiki_root: Path) -> None:
    (workspace / "wiki").mkdir(parents=True, exist_ok=True)
    (workspace / "clients").mkdir(parents=True, exist_ok=True)
    (workspace / ".llmwiki").mkdir(parents=True, exist_ok=True)
    (workspace / ".llmwiki" / "cache").mkdir(parents=True, exist_ok=True)

    # Reuse llmwiki's SQLite vault init
    sys.path.insert(0, str(llmwiki_root / "mcp"))
    from vaultfs import SqliteVaultFS  # type: ignore

    await SqliteVaultFS.init(str(workspace))
    fs = SqliteVaultFS(os.environ["SUPAVAULT_USER_ID"])
    if not await fs.get_workspace():
        await fs.ensure_workspace(workspace.name)
        logger.info("Initialized workspace at %s", workspace)


def main() -> None:
    args = _parse()
    workspace = Path(args.workspace).expanduser().resolve()
    workspace.mkdir(parents=True, exist_ok=True)
    llmwiki_root = resolve_llmwiki_root(args.llmwiki_root)

    local_user_id = os.environ.get("LLMWIKI_USER_ID") or str(uuid.uuid5(uuid.NAMESPACE_DNS, "local"))
    os.environ["SUPAVAULT_USER_ID"] = local_user_id
    os.environ["LLMWIKI_USER_ID"] = local_user_id

    loop = asyncio.new_event_loop()
    loop.run_until_complete(_init(workspace, llmwiki_root))

    # llmwiki imports (only available after sys.path injection in _init)
    from mcp.server.fastmcp import FastMCP
    from tools import register as register_llmwiki  # type: ignore
    from vaultfs import SqliteVaultFS  # type: ignore

    # Growth Cloud imports
    from mcp_tools.guide import register as register_gc_guide
    from mcp_tools.tools import register as register_gc_tools

    mcp = FastMCP(
        name="Swell Growth Cloud",
        instructions=(
            "You are connected to the Swell Growth Cloud. Call `guide` first. "
            "Use `briefing`, `stakeholders`, `commitments`, `decisions` for the "
            "MVP queries; use `search`/`read`/`write` for everything else. "
            "Every claim must cite a specific AID file with a timestamp."
        ),
    )

    def _get_user_id(ctx):
        return local_user_id

    # llmwiki base tools — skip `guide`; we register the Growth Cloud `guide`
    # below. This avoids FastMCP's "Tool already exists" warning and the
    # version-dependent last-writer-wins behaviour.
    register_llmwiki(mcp, _get_user_id, lambda uid: SqliteVaultFS(uid), skip=("guide",))

    register_gc_guide(mcp, workspace)
    register_gc_tools(mcp, workspace)

    logger.info("Growth Cloud MCP ready — workspace=%s", workspace)
    asyncio.run(mcp.run_stdio_async())


if __name__ == "__main__":
    main()
