"""Growth Cloud CLI — single entry point for end users and Claude Desktop.

Subcommands:
  init        Create workspace folders + SQLite index
  mcp         Run the stdio MCP server (used by Claude Desktop / Code)
  mcp-config  Print a Claude Desktop config snippet
  ingest      Pull Fathom calls, extract AIDs, recompile wiki (--once|--watch)
  recompile   Re-derive wiki pages for one AID

This module is exposed as the `growth-cloud` console script via
``[project.scripts]`` in ``pyproject.toml``. The repo-root ``growth-cloud``
shell wrapper exec's it for users who haven't `pip install`-ed the package.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import re
import shutil
import sys
from pathlib import Path

logger = logging.getLogger("growth-cloud.cli")

REPO_ROOT = Path(__file__).resolve().parent.parent  # growth-cloud/


def _sanitize(name: str) -> str:
    slug = re.sub(r"[^a-z0-9\s-]", "", name.lower().strip())
    slug = re.sub(r"[\s-]+", "-", slug).strip("-")
    return slug or "workspace"


def _resolve_llmwiki_for_help() -> Path | None:
    """Best-effort lookup — used only for the help text in `mcp-config`."""
    try:
        from server.main import resolve_llmwiki_root
        return resolve_llmwiki_root(None)
    except SystemExit:
        return None


# ── init ──────────────────────────────────────────────────────────────────────

def cmd_init(args: argparse.Namespace) -> int:
    """Scaffold a Growth Cloud workspace via the same SqliteVaultFS path used
    by the MCP server. Idempotent."""
    import asyncio
    import uuid as _uuid

    workspace = Path(args.workspace).expanduser().resolve()
    workspace.mkdir(parents=True, exist_ok=True)
    (workspace / "wiki").mkdir(exist_ok=True)
    (workspace / "clients").mkdir(exist_ok=True)
    (workspace / ".llmwiki").mkdir(exist_ok=True)
    (workspace / ".llmwiki" / "cache").mkdir(exist_ok=True)

    from server.main import resolve_llmwiki_root
    llmwiki_root = resolve_llmwiki_root(args.llmwiki_root)
    sys.path.insert(0, str(llmwiki_root / "mcp"))

    local_user_id = os.environ.get("LLMWIKI_USER_ID") or str(_uuid.uuid5(_uuid.NAMESPACE_DNS, "local"))
    os.environ["SUPAVAULT_USER_ID"] = local_user_id

    from vaultfs import SqliteVaultFS  # type: ignore

    async def _go() -> None:
        await SqliteVaultFS.init(str(workspace))
        try:
            fs = SqliteVaultFS(local_user_id)
            if not await fs.get_workspace():
                await fs.ensure_workspace(workspace.name)
                print(f"✓ Initialized workspace: {workspace}")
            else:
                print(f"Workspace already initialized: {workspace}")
        finally:
            await SqliteVaultFS.close()

    asyncio.run(_go())
    print(f"  clients/        — drop AIDs under clients/<slug>/calls/")
    print(f"  wiki/           — Claude writes compounded wiki pages here")
    print(f"  .llmwiki/index.db — derived index (rebuildable)")
    return 0


# ── mcp ───────────────────────────────────────────────────────────────────────

def cmd_mcp(args: argparse.Namespace) -> int:
    """Exec the stdio MCP server. This is what Claude Desktop's `command`
    field invokes."""
    workspace = str(Path(args.workspace).expanduser().resolve())
    cmd_argv = [sys.executable, "-m", "server.main", "--workspace", workspace]
    if args.llmwiki_root:
        cmd_argv += ["--llmwiki-root", args.llmwiki_root]
    env = os.environ.copy()
    # Make `server` and `mcp_tools` importable when the user didn't pip install.
    pp = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = (str(REPO_ROOT) + (os.pathsep + pp if pp else ""))
    os.execvpe(cmd_argv[0], cmd_argv, env)


# ── mcp-config ────────────────────────────────────────────────────────────────

def cmd_mcp_config(args: argparse.Namespace) -> int:
    workspace = Path(args.workspace).expanduser().resolve()
    server_name = args.name or f"growth-cloud-{_sanitize(workspace.name)}"

    # Prefer the installed `growth-cloud` script if present; otherwise point
    # at the in-repo shell wrapper.
    cmd_path = shutil.which("growth-cloud") or str(REPO_ROOT / "growth-cloud")
    config = {
        "mcpServers": {
            server_name: {
                "command": cmd_path,
                "args": ["mcp", "--workspace", str(workspace)],
                "env": {
                    # Honoured by server/main.py:resolve_llmwiki_root
                    "LLMWIKI_ROOT": str(_resolve_llmwiki_for_help() or "/path/to/llmwiki"),
                },
            }
        }
    }
    print("# Add to claude_desktop_config.json (or .claude/settings.json):")
    print(f"# This MCP server is scoped to: {workspace}")
    print()
    print(json.dumps(config, indent=2))
    return 0


# ── ingest ────────────────────────────────────────────────────────────────────

def cmd_ingest(args: argparse.Namespace) -> int:
    """Pull recent Fathom calls and write AIDs into the workspace."""
    import asyncio

    os.environ.setdefault("GROWTH_CLOUD_WORKSPACE", str(Path(args.workspace).expanduser().resolve()))

    from ingest.config import Settings
    from ingest.fathom import (
        AIDExtractor,
        ClientRouter,
        FathomClient,
        GrowthCloudIngest,
        HTTPFathomTransport,
        FixtureFathomTransport,
    )
    from recompile.worker import build_recompile_prompt
    from ingest.runner import build_claude_runner

    settings = Settings()  # validates required env

    if args.fixtures:
        transport = FixtureFathomTransport(Path(args.fixtures).expanduser().resolve())
    else:
        transport = HTTPFathomTransport(settings.FATHOM_API_KEY)

    fathom = FathomClient(transport)
    extractor = AIDExtractor(settings)
    router = ClientRouter(domain_map=settings.CLIENT_DOMAIN_MAP, default=settings.CLIENT_DEFAULT)
    claude_runner = build_claude_runner(settings, args.dry_run)

    async def _notify(client_slug: str, path: Path) -> None:
        prompt = build_recompile_prompt(Path(settings.GROWTH_CLOUD_WORKSPACE), path)
        result = await claude_runner(prompt)
        logger.info("Recompile result for %s: %s", client_slug, result[:200])

    workspace = Path(settings.GROWTH_CLOUD_WORKSPACE)
    ingest = GrowthCloudIngest(workspace, router, fathom, extractor, on_aid_written=_notify)

    async def _once() -> int:
        from datetime import timedelta
        written = await ingest.poll_once(lookback=timedelta(hours=settings.INGEST_LOOKBACK_HOURS))
        print(f"✓ Wrote {len(written)} AID(s)")
        for p in written:
            print(f"  - {p.relative_to(workspace)}")
        return 0

    async def _watch() -> int:
        from datetime import timedelta
        interval = settings.INGEST_POLL_INTERVAL_MIN * 60
        while True:
            try:
                written = await ingest.poll_once(lookback=timedelta(hours=settings.INGEST_LOOKBACK_HOURS))
                if written:
                    print(f"✓ Wrote {len(written)} AID(s)")
            except Exception:
                logger.exception("poll_once failed")
            await asyncio.sleep(interval)

    if args.watch:
        return asyncio.run(_watch())
    return asyncio.run(_once())


# ── recompile ─────────────────────────────────────────────────────────────────

def cmd_recompile(args: argparse.Namespace) -> int:
    """Manually trigger a recompile for one AID file."""
    import asyncio

    os.environ.setdefault("GROWTH_CLOUD_WORKSPACE", str(Path(args.workspace).expanduser().resolve()))

    from ingest.config import Settings
    from ingest.runner import build_claude_runner
    from recompile.worker import build_recompile_prompt

    settings = Settings()
    workspace = Path(settings.GROWTH_CLOUD_WORKSPACE)
    aid_path = Path(args.aid).expanduser().resolve()
    if not aid_path.is_file():
        sys.stderr.write(f"AID not found: {aid_path}\n")
        return 2

    runner = build_claude_runner(settings, args.dry_run)
    prompt = build_recompile_prompt(workspace, aid_path)

    async def _go() -> int:
        result = await runner(prompt)
        print(result)
        return 0

    return asyncio.run(_go())


# ── parser ────────────────────────────────────────────────────────────────────

def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="growth-cloud",
        description="Swell Growth Cloud — Fathom → AID → compounded wiki.",
    )
    sub = p.add_subparsers(dest="command", required=True)

    p_init = sub.add_parser("init", help="Scaffold a workspace")
    p_init.add_argument("workspace")
    p_init.add_argument("--llmwiki-root", default=None)
    p_init.set_defaults(func=cmd_init)

    p_mcp = sub.add_parser("mcp", help="Run stdio MCP server (for Claude Desktop)")
    p_mcp.add_argument("--workspace", required=True)
    p_mcp.add_argument("--llmwiki-root", default=None)
    p_mcp.set_defaults(func=cmd_mcp)

    p_cfg = sub.add_parser("mcp-config", help="Print Claude Desktop config JSON")
    p_cfg.add_argument("workspace")
    p_cfg.add_argument("--name", default=None)
    p_cfg.set_defaults(func=cmd_mcp_config)

    p_ing = sub.add_parser("ingest", help="Pull Fathom calls and write AIDs")
    p_ing.add_argument("workspace")
    p_ing.add_argument("--once", action="store_true", default=True, help="Run one poll and exit (default)")
    p_ing.add_argument("--watch", action="store_true", default=False, help="Loop with INGEST_POLL_INTERVAL_MIN cadence")
    p_ing.add_argument("--fixtures", default=None, help="Path to a Fathom fixture directory (bypasses HTTP)")
    p_ing.add_argument("--dry-run", action="store_true", help="Use StdoutClaudeRunner instead of calling Anthropic")
    p_ing.set_defaults(func=cmd_ingest)

    p_rec = sub.add_parser("recompile", help="Re-derive wiki pages for one AID")
    p_rec.add_argument("workspace")
    p_rec.add_argument("aid", help="Path to the AID markdown file")
    p_rec.add_argument("--dry-run", action="store_true")
    p_rec.set_defaults(func=cmd_recompile)

    return p


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    parser = _build_parser()
    args = parser.parse_args(argv)
    return args.func(args) or 0


if __name__ == "__main__":
    raise SystemExit(main())
