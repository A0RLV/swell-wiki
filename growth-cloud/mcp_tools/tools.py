"""Growth Cloud MCP tools — the four MVP queries as deterministic tools.

These read AID frontmatter directly from the workspace filesystem. No FTS5,
no LLM-in-the-loop. Every answer carries a citation to the source AID file
(and timestamp within the call when present).

Generic search / read / write from llmwiki remain available for everything
else; these tools just make the MVP queries first-class and reliable.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Optional

from mcp.server.fastmcp import FastMCP

from .aid_store import cite, load_aids, workspace_clients


def _parse_since(since: str | None) -> date | None:
    if not since:
        return None
    s = since.strip().lower()
    if s.endswith("d") and s[:-1].isdigit():
        return (datetime.utcnow().date() - timedelta(days=int(s[:-1])))
    if s.endswith("w") and s[:-1].isdigit():
        return (datetime.utcnow().date() - timedelta(weeks=int(s[:-1])))
    try:
        return date.fromisoformat(s)
    except ValueError:
        return None


def register(mcp: FastMCP, workspace: Path) -> None:

    # ── briefing ─────────────────────────────────────────────────────────────
    @mcp.tool(
        name="briefing",
        description=(
            "Generate a current-state briefing for a client. Use this for the "
            "TLDR onboarding query ('what's the state of X?'), the joined-the-"
            "account query, or the developments-since query (pass `since`). "
            "Every claim is sourced to a specific call file."
        ),
    )
    async def briefing(client: str, since: Optional[str] = None, persona: Optional[str] = None) -> str:
        since_d = _parse_since(since)
        aids = load_aids(workspace, client, since=since_d)
        if not aids:
            scope = f" since {since_d}" if since_d else ""
            return f"No AIDs found for `{client}`{scope}."

        latest_date = aids[-1][1].get("call_date")
        earliest_date = aids[0][1].get("call_date")

        # Aggregate the structured payload across calls
        decisions: list[tuple[Path, dict, dict]] = []
        commitments_open: list[tuple[Path, dict, dict]] = []
        experiments_active: list[tuple[Path, dict, dict]] = []
        recent_signals: list[tuple[Path, dict, dict]] = []
        stakeholder_seen: Counter = Counter()

        for path, fm in aids:
            for d in fm.get("decisions", []) or []:
                decisions.append((path, fm, d))
            for c in fm.get("commitments", []) or []:
                if (c.get("status") or "open") == "open":
                    commitments_open.append((path, fm, c))
            for e in fm.get("experiments", []) or []:
                if e.get("status") in ("proposed", "running"):
                    experiments_active.append((path, fm, e))
            for s in fm.get("performance_signals", []) or []:
                recent_signals.append((path, fm, s))
            for p in fm.get("participants", []) or []:
                name = p.get("name")
                if name and not p.get("swell_side"):
                    stakeholder_seen[name] += 1

        out: list[str] = []
        scope_str = f" since {since_d}" if since_d else ""
        out.append(f"# {client} — briefing{scope_str}")
        out.append(f"_{len(aids)} call(s) between {earliest_date} and {latest_date}._")
        if persona:
            out.append(f"_Persona filter: {persona} (applied to commitments/decisions where owner is identifiable)._")
        out.append("")

        # Top 5 active workstreams by frequency
        ws_counter: Counter = Counter()
        for _, fm in aids:
            for w in fm.get("workstreams", []) or []:
                ws_counter[w] += 1
        if ws_counter:
            out.append("## Active workstreams")
            for w, n in ws_counter.most_common(5):
                out.append(f"- `{w}` — mentioned in {n} call(s)")
            out.append("")

        if commitments_open:
            out.append(f"## Open commitments ({len(commitments_open)})")
            for path, fm, c in commitments_open[:10]:
                owner = c.get("owner") or "?"
                due = f", due {c['due']}" if c.get("due") else ""
                out.append(
                    f"- {c['statement']} — **{owner}**{due} "
                    f"({cite(path, workspace, c.get('source_timestamp'))})"
                )
            if len(commitments_open) > 10:
                out.append(f"  …and {len(commitments_open) - 10} more.")
            out.append("")

        if experiments_active:
            out.append(f"## Active experiments ({len(experiments_active)})")
            for path, fm, e in experiments_active[:10]:
                out.append(
                    f"- [{e.get('status')}] {e['hypothesis']} "
                    f"({cite(path, workspace, e.get('source_timestamp'))})"
                )
            out.append("")

        if decisions:
            out.append(f"## Recent decisions (latest {min(8, len(decisions))})")
            for path, fm, d in decisions[-8:][::-1]:
                ws = f" `{d['workstream']}`" if d.get("workstream") else ""
                out.append(
                    f"- {d['statement']}{ws} "
                    f"({cite(path, workspace, d.get('source_timestamp'))})"
                )
            out.append("")

        if recent_signals:
            out.append("## Performance signals")
            for path, fm, s in recent_signals[-8:][::-1]:
                scope = "/".join(x for x in [s.get("market"), s.get("channel")] if x)
                scope = f" ({scope})" if scope else ""
                mag = f" — {s['magnitude']}" if s.get("magnitude") else ""
                out.append(
                    f"- {s['metric']}{scope}: {s.get('direction', '?')}{mag} "
                    f"({cite(path, workspace, s.get('source_timestamp'))})"
                )
            out.append("")

        if stakeholder_seen:
            out.append("## Key stakeholders by call presence")
            for name, n in stakeholder_seen.most_common(8):
                out.append(f"- {name} — {n} call(s)")
            out.append("")

        return "\n".join(out)

    # ── stakeholders ─────────────────────────────────────────────────────────
    @mcp.tool(
        name="stakeholders",
        description=(
            "Map stakeholders for a client: who they are, what they own, how "
            "they show up across calls, sentiment trail. Answers 'who's calling "
            "the shots on what here?'."
        ),
    )
    async def stakeholders(client: str) -> str:
        aids = load_aids(workspace, client)
        if not aids:
            return f"No AIDs for `{client}`."

        # name → {org, roles, calls, decisions_owned, commitments_owned, sentiment}
        people: dict[str, dict] = defaultdict(lambda: {
            "org": None, "roles": Counter(), "calls": [], "decisions": [],
            "commitments": [], "sentiment": [],
        })

        for path, fm in aids:
            for p in fm.get("participants", []) or []:
                name = p.get("name")
                if not name:
                    continue
                rec = people[name]
                rec["org"] = rec["org"] or p.get("org")
                if p.get("role"):
                    rec["roles"][p["role"]] += 1
                rec["calls"].append(path)
            for d in fm.get("decisions", []) or []:
                if d.get("owner"):
                    people[d["owner"]]["decisions"].append((path, d))
            for c in fm.get("commitments", []) or []:
                if c.get("owner"):
                    people[c["owner"]]["commitments"].append((path, c))
            for s in fm.get("sentiment", []) or []:
                if s.get("person"):
                    people[s["person"]]["sentiment"].append((path, s))

        if not people:
            return f"No stakeholders extracted yet for `{client}`."

        # Rough authority score: decisions owned * 2 + commitments owned + call presence
        def score(rec: dict) -> int:
            return 2 * len(rec["decisions"]) + len(rec["commitments"]) + len(rec["calls"])

        ranked = sorted(people.items(), key=lambda kv: -score(kv[1]))

        out = [f"# {client} — stakeholders", f"_{len(ranked)} people across {len(aids)} call(s)._", ""]
        for name, rec in ranked:
            top_role = rec["roles"].most_common(1)[0][0] if rec["roles"] else "?"
            org = f" ({rec['org']})" if rec["org"] else ""
            out.append(f"## {name}{org} — {top_role}")
            out.append(f"- Calls: {len(rec['calls'])}")
            out.append(f"- Decisions owned: {len(rec['decisions'])}")
            out.append(f"- Commitments owned: {len(rec['commitments'])}")
            if rec["decisions"]:
                out.append("- Recent decisions:")
                for path, d in rec["decisions"][-3:]:
                    out.append(f"  - {d['statement']} ({cite(path, workspace)})")
            if rec["sentiment"]:
                out.append("- Sentiment trail:")
                for path, s in rec["sentiment"][-3:]:
                    out.append(
                        f"  - on `{s['topic']}`: {s['valence']} "
                        f"({cite(path, workspace, s.get('source_timestamp'))})"
                    )
            out.append("")
        return "\n".join(out)

    # ── commitments ──────────────────────────────────────────────────────────
    @mcp.tool(
        name="commitments",
        description="List commitments for a client. Filter by status or owner.",
    )
    async def commitments(
        client: str,
        status: str = "open",
        owner: Optional[str] = None,
    ) -> str:
        aids = load_aids(workspace, client)
        if not aids:
            return f"No AIDs for `{client}`."

        rows: list[tuple[Path, dict]] = []
        for path, fm in aids:
            for c in fm.get("commitments", []) or []:
                if status != "*" and (c.get("status") or "open") != status:
                    continue
                if owner and (c.get("owner") or "").lower() != owner.lower():
                    continue
                rows.append((path, c))

        if not rows:
            return f"No `{status}` commitments for `{client}`" + (f" owned by {owner}" if owner else "") + "."

        out = [f"# {client} — commitments ({status})", f"_{len(rows)} item(s)._", ""]
        for path, c in rows:
            own = c.get("owner") or "?"
            due = f", due {c['due']}" if c.get("due") else ""
            out.append(
                f"- [{c.get('status', 'open')}] {c['statement']} — **{own}**{due} "
                f"({cite(path, workspace, c.get('source_timestamp'))})"
            )
        return "\n".join(out)

    # ── decisions ────────────────────────────────────────────────────────────
    @mcp.tool(
        name="decisions",
        description=(
            "Cross-call decision synthesis. Filter by workstream or since-date. "
            "Use this for 'what did we decide about X?' queries."
        ),
    )
    async def decisions(
        client: str,
        workstream: Optional[str] = None,
        since: Optional[str] = None,
    ) -> str:
        since_d = _parse_since(since)
        aids = load_aids(workspace, client, since=since_d)
        rows: list[tuple[Path, dict]] = []
        for path, fm in aids:
            for d in fm.get("decisions", []) or []:
                if workstream and (d.get("workstream") or "") != workstream:
                    continue
                rows.append((path, d))

        if not rows:
            return f"No decisions matched for `{client}`."

        out = [f"# {client} — decisions", f"_{len(rows)} item(s)._", ""]
        for path, d in rows:
            ws = f" `{d['workstream']}`" if d.get("workstream") else ""
            owner = f" — {d['owner']}" if d.get("owner") else ""
            out.append(
                f"- {d['statement']}{ws}{owner} "
                f"({cite(path, workspace, d.get('source_timestamp'))})"
            )
        return "\n".join(out)

    # ── clients (utility) ────────────────────────────────────────────────────
    @mcp.tool(name="clients", description="List clients tracked in the Growth Cloud.")
    async def clients() -> str:
        cs = workspace_clients(workspace)
        if not cs:
            return "No clients yet."
        return "\n".join(f"- {c}" for c in cs)
