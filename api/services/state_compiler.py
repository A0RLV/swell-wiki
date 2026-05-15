"""KB hygiene — recompile wiki state files when new AIDs land.

Three small Sonnet 4.6 merge passes, one per state file. Each pass takes the
current `wiki/*.md` + the new AID and emits the next version of that file.
Contradiction handling: newer wins, older claim is moved to a `superseded`
section if it was previously load-bearing.

The actual call surface here is intentionally small — the prompts in
`prompts/state_*.md` do the heavy lifting. Wire into llmwiki's existing
watcher (`api/domain/watcher.py`) so this runs whenever a new AID file lands
under `wiki/calls/`.

Demo-state caveat: the merge prompts in `prompts/` are stubs. They produce
reasonable output but haven't been tuned against the full Target Darts
corpus yet — that's the highest-leverage next step.
"""

from __future__ import annotations

import logging
from pathlib import Path

import anthropic

from ..schemas.aid import AID

logger = logging.getLogger(__name__)

STATE_COMPILER_MODEL = "claude-sonnet-4-6"

_MERGE_PROMPT = """You are maintaining a single state file in a knowledge wiki.
The wiki is the durable, human-readable view of the work.
A new call has produced an AID with structured entities.
Your job: emit the next version of this state file.

Rules:
- Newer information wins. If the AID contradicts the existing file on something
  load-bearing, update the claim and move the old claim into a `## Superseded`
  section at the bottom with the old date.
- Preserve markdown structure. Keep headings, lists, citation chips intact.
- Citations look like `[call_id:t_start_s]`. Add new ones from the AID where
  they support new claims. Don't fabricate citations.
- If nothing in the AID is relevant to this state file, return the file unchanged.

Return ONLY the new file contents. No commentary, no code fences.
"""


def _merge(
    client: anthropic.Anthropic,
    current_md: str,
    aid_md: str,
    file_label: str,
) -> str:
    response = client.messages.create(
        model=STATE_COMPILER_MODEL,
        max_tokens=4096,
        thinking={"type": "adaptive"},
        system=[{"type": "text", "text": _MERGE_PROMPT, "cache_control": {"type": "ephemeral"}}],
        messages=[
            {
                "role": "user",
                "content": (
                    f"State file: `{file_label}`\n\n"
                    "## Current contents\n\n"
                    f"{current_md}\n\n"
                    "## New AID (markdown form)\n\n"
                    f"{aid_md}\n\n"
                    "Emit the new contents of the state file now."
                ),
            }
        ],
    )
    for b in response.content:
        if b.type == "text":
            return b.text.strip() + "\n"
    raise RuntimeError("state compiler returned no text content")


def recompile_state(
    client: anthropic.Anthropic,
    workspace_root: Path,
    aid: AID,
    aid_markdown: str,
) -> dict[str, str]:
    """Recompile the three core state files. Returns {path: new_contents}.

    Caller is responsible for writing the files (let llmwiki's `write` tool do
    it via MCP so the existing audit trail and FTS reindex fire).
    """
    targets = {
        "wiki/overview.md": "Account overview — durable snapshot of the current state",
        "wiki/stakeholders.md": "Who's calling the shots, grouped by company",
    }
    # One workstream file per workstream touched by this AID.
    for w in aid.workstreams:
        targets[f"wiki/workstreams/{w.name}.md"] = f"Workstream: {w.name}"

    out: dict[str, str] = {}
    for rel_path, label in targets.items():
        full = workspace_root / rel_path
        current = full.read_text(encoding="utf-8") if full.exists() else ""
        try:
            out[rel_path] = _merge(client, current, aid_markdown, label)
        except Exception:
            logger.exception("state_compiler failed for %s", rel_path)
    return out
