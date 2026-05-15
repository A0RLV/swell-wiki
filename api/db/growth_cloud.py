"""SQLite repository for the Growth Cloud entity tables.

Thin wrapper around aiosqlite (the same connection llmwiki uses). All methods
return plain dicts so the briefings layer can pass them straight to the LLM
without typing gymnastics.

Schema is in `shared/growth_cloud_schema.sql` — loaded at workspace init by
extending the existing schema-loader in `api/infra/db/sqlite.py`.

Async-readable later; kept sync here so the prose lands in <200 lines.
"""

from __future__ import annotations

import sqlite3
from datetime import date
from typing import Any

from ..schemas.aid import AID

Row = dict[str, Any]


def _normalize_name(name: str) -> str:
    return " ".join(name.lower().split())


class GrowthCloudRepo:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn
        self.conn.row_factory = sqlite3.Row

    # --- Upsert (AID → tables) ----------------------------------------------

    def upsert_aid(self, workspace_id: str, aid: AID, *, raw_path: str | None = None) -> None:
        """Insert/replace a call and all its derived entities.

        Idempotent on call_id — re-running extraction overwrites entities for that call.
        """
        cur = self.conn.cursor()
        # Wipe prior entities for this call so re-extracts don't double-count.
        cur.execute("DELETE FROM transcript_segments WHERE call_id = ?", (aid.call.id,))
        cur.execute("DELETE FROM call_people WHERE call_id = ?", (aid.call.id,))
        cur.execute("DELETE FROM decisions WHERE call_id = ?", (aid.call.id,))
        cur.execute("DELETE FROM commitments WHERE call_id = ?", (aid.call.id,))
        cur.execute("DELETE FROM performance_signals WHERE call_id = ?", (aid.call.id,))
        cur.execute("DELETE FROM open_questions WHERE call_id = ?", (aid.call.id,))

        cur.execute(
            "INSERT OR REPLACE INTO calls(id, workspace_id, date, title, fathom_url, "
            "attendees, duration_s, raw_path) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                aid.call.id, workspace_id, aid.call.date, aid.call.title,
                aid.call.fathom_url,
                _json_list(aid.call.attendees),
                aid.call.duration_s, raw_path,
            ),
        )

        # People — upsert by normalized name, keep latest role/seniority.
        person_ids: dict[str, str] = {}
        for s in aid.stakeholders:
            norm = _normalize_name(s.name)
            cur.execute(
                "SELECT id FROM people WHERE workspace_id = ? AND name_normalized = ?",
                (workspace_id, norm),
            )
            row = cur.fetchone()
            if row:
                pid = row["id"]
                cur.execute(
                    "UPDATE people SET role = COALESCE(?, role), seniority = ?, "
                    "company = COALESCE(?, company), last_seen_call = ? WHERE id = ?",
                    (s.role, s.seniority, s.company, aid.call.id, pid),
                )
            else:
                cur.execute(
                    "INSERT INTO people(workspace_id, name, name_normalized, company, "
                    "role, seniority, first_seen_call, last_seen_call) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (workspace_id, s.name, norm, s.company, s.role, s.seniority,
                     aid.call.id, aid.call.id),
                )
                pid = cur.execute("SELECT last_insert_rowid()").fetchone()[0]
                # last_insert_rowid is the SQLite rowid; we use a TEXT PK with default,
                # so re-fetch the id by name.
                pid = cur.execute(
                    "SELECT id FROM people WHERE workspace_id = ? AND name_normalized = ?",
                    (workspace_id, norm),
                ).fetchone()["id"]
            person_ids[s.name] = pid

            cur.execute(
                "INSERT OR REPLACE INTO call_people(call_id, person_id, talk_time_pct, sentiment) "
                "VALUES (?, ?, ?, ?)",
                (aid.call.id, pid, s.talk_time_pct, s.sentiment),
            )

        for d in aid.decisions:
            cur.execute(
                "INSERT INTO decisions(call_id, summary, owner_id, deadline, status, "
                "workstream, t_start_s, t_end_s, confidence) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (aid.call.id, d.summary, person_ids.get(d.owner) if d.owner else None,
                 d.deadline, d.status, d.workstream, d.t_start_s, d.t_end_s, d.confidence),
            )

        for c in aid.commitments:
            cur.execute(
                "INSERT INTO commitments(call_id, owner_id, summary, due, status, "
                "workstream, t_start_s, t_end_s) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (aid.call.id, person_ids.get(c.owner) if c.owner else None,
                 c.summary, c.due, c.status, c.workstream, c.t_start_s, c.t_end_s),
            )

        for e in aid.experiments:
            cur.execute(
                "INSERT INTO experiments(workspace_id, name, hypothesis, market, channel, "
                "status, started_call_id, last_update_call_id) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(workspace_id, name) DO UPDATE SET "
                "status = excluded.status, last_update_call_id = excluded.last_update_call_id, "
                "hypothesis = COALESCE(excluded.hypothesis, experiments.hypothesis)",
                (workspace_id, e.name, e.hypothesis, e.market, e.channel,
                 e.status, aid.call.id, aid.call.id),
            )

        for w in aid.workstreams:
            cur.execute(
                "INSERT INTO workstreams(workspace_id, name, status, summary, last_update_call_id) "
                "VALUES (?, ?, ?, ?, ?) "
                "ON CONFLICT(workspace_id, name) DO UPDATE SET "
                "status = COALESCE(excluded.status, workstreams.status), "
                "summary = COALESCE(excluded.summary, workstreams.summary), "
                "last_update_call_id = excluded.last_update_call_id",
                (workspace_id, w.name, w.status, w.key_update, aid.call.id),
            )

        for p in aid.performance_signals:
            cur.execute(
                "INSERT INTO performance_signals(call_id, market, channel, metric, value, "
                "direction, note, t_start_s, t_end_s) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (aid.call.id, p.market, p.channel, p.metric, p.value,
                 p.direction, p.note, p.t_start_s, p.t_end_s),
            )

        for q in aid.open_questions:
            cur.execute(
                "INSERT INTO open_questions(call_id, question, who_to_ask, t_start_s, t_end_s) "
                "VALUES (?, ?, ?, ?, ?)",
                (aid.call.id, q.question, person_ids.get(q.who_to_ask) if q.who_to_ask else None,
                 q.t_start_s, q.t_end_s),
            )

        self.conn.commit()

    def upsert_segments(self, call_id: str, segments: list[dict]) -> None:
        cur = self.conn.cursor()
        cur.executemany(
            "INSERT OR REPLACE INTO transcript_segments(call_id, seg_index, t_start_s, "
            "t_end_s, speaker, content) VALUES (?, ?, ?, ?, ?, ?)",
            [(call_id, s["seg_index"], s["t_start_s"], s["t_end_s"],
              s.get("speaker"), s["content"]) for s in segments],
        )
        self.conn.commit()

    # --- Read queries used by briefings ------------------------------------

    def list_decisions(
        self, workspace_id: str, *, status: str | None = None,
        since: date | None = None, limit: int = 20,
    ) -> list[Row]:
        q = ("SELECT d.id, d.summary, d.deadline, d.status, d.workstream, "
             "d.call_id, d.t_start_s, d.t_end_s, p.name AS owner, c.date "
             "FROM decisions d JOIN calls c ON c.id = d.call_id "
             "LEFT JOIN people p ON p.id = d.owner_id "
             "WHERE c.workspace_id = ?")
        params: list[Any] = [workspace_id]
        if status:
            q += " AND d.status = ?"; params.append(status)
        if since:
            q += " AND c.date >= ?"; params.append(since.isoformat())
        q += " ORDER BY c.date DESC LIMIT ?"; params.append(limit)
        return [dict(r) for r in self.conn.execute(q, params).fetchall()]

    def list_commitments(
        self, workspace_id: str, *, since: date | None = None, limit: int = 20,
    ) -> list[Row]:
        q = ("SELECT cm.id, cm.summary, cm.due, cm.status, cm.workstream, "
             "cm.call_id, cm.t_start_s, cm.t_end_s, p.name AS owner, c.date "
             "FROM commitments cm JOIN calls c ON c.id = cm.call_id "
             "LEFT JOIN people p ON p.id = cm.owner_id "
             "WHERE c.workspace_id = ?")
        params: list[Any] = [workspace_id]
        if since:
            q += " AND c.date >= ?"; params.append(since.isoformat())
        q += " ORDER BY c.date DESC LIMIT ?"; params.append(limit)
        return [dict(r) for r in self.conn.execute(q, params).fetchall()]

    def list_open_commitments(self, workspace_id: str, limit: int = 20) -> list[Row]:
        q = ("SELECT cm.id, cm.summary, cm.due, cm.status, cm.workstream, "
             "cm.call_id, cm.t_start_s, cm.t_end_s, p.name AS owner, c.date "
             "FROM commitments cm JOIN calls c ON c.id = cm.call_id "
             "LEFT JOIN people p ON p.id = cm.owner_id "
             "WHERE c.workspace_id = ? AND cm.status IN ('open', 'overdue') "
             "ORDER BY cm.due IS NULL, cm.due ASC LIMIT ?")
        return [dict(r) for r in self.conn.execute(q, (workspace_id, limit)).fetchall()]

    def list_experiments(
        self, workspace_id: str, *, status: str | None = None, limit: int = 20,
    ) -> list[Row]:
        q = ("SELECT name, hypothesis, market, channel, status, "
             "started_call_id AS call_id, last_update_call_id "
             "FROM experiments WHERE workspace_id = ?")
        params: list[Any] = [workspace_id]
        if status:
            q += " AND status = ?"; params.append(status)
        q += " LIMIT ?"; params.append(limit)
        rows = [dict(r) for r in self.conn.execute(q, params).fetchall()]
        # Briefings need a t_start_s for citation; pull from started_call segment 0.
        for r in rows:
            r["t_start_s"] = 0
            r["t_end_s"] = 0
        return rows

    def list_experiment_updates(
        self, workspace_id: str, *, since: date, limit: int = 20,
    ) -> list[Row]:
        # An "update" = the experiment was discussed on a call after `since`.
        # We approximate by joining last_update_call_id → calls.date.
        q = ("SELECT e.name, e.status, e.market, e.channel, "
             "e.last_update_call_id AS call_id, c.date "
             "FROM experiments e LEFT JOIN calls c ON c.id = e.last_update_call_id "
             "WHERE e.workspace_id = ? AND c.date >= ? "
             "ORDER BY c.date DESC LIMIT ?")
        rows = [dict(r) for r in self.conn.execute(q, (workspace_id, since.isoformat(), limit)).fetchall()]
        for r in rows:
            r["t_start_s"] = 0
            r["t_end_s"] = 0
        return rows

    def list_performance_signals(
        self, workspace_id: str, *, since: date | None = None, limit: int = 30,
    ) -> list[Row]:
        q = ("SELECT ps.metric, ps.value, ps.direction, ps.market, ps.channel, ps.note, "
             "ps.call_id, ps.t_start_s, ps.t_end_s, c.date "
             "FROM performance_signals ps JOIN calls c ON c.id = ps.call_id "
             "WHERE c.workspace_id = ?")
        params: list[Any] = [workspace_id]
        if since:
            q += " AND c.date >= ?"; params.append(since.isoformat())
        q += " ORDER BY c.date DESC LIMIT ?"; params.append(limit)
        return [dict(r) for r in self.conn.execute(q, params).fetchall()]

    def list_workstreams(self, workspace_id: str) -> list[Row]:
        q = ("SELECT name, status, summary, last_update_call_id AS call_id "
             "FROM workstreams WHERE workspace_id = ? ORDER BY name")
        return [dict(r) for r in self.conn.execute(q, (workspace_id,)).fetchall()]

    def list_top_stakeholders(self, workspace_id: str, limit: int = 8) -> list[Row]:
        q = ("SELECT p.id, p.name, p.company, p.role, p.seniority, p.authority_score, "
             "COUNT(cp.call_id) AS call_count "
             "FROM people p LEFT JOIN call_people cp ON cp.person_id = p.id "
             "WHERE p.workspace_id = ? GROUP BY p.id "
             "ORDER BY p.authority_score DESC, call_count DESC LIMIT ?")
        return [dict(r) for r in self.conn.execute(q, (workspace_id, limit)).fetchall()]

    def list_people_with_call_stats(self, workspace_id: str) -> list[Row]:
        q = ("SELECT p.id, p.name, p.company, p.role, p.seniority, p.authority_score, "
             "COUNT(cp.call_id) AS call_count, "
             "AVG(CASE cp.sentiment "
             "  WHEN 'positive' THEN 1.0 WHEN 'neutral' THEN 0.0 "
             "  WHEN 'negative' THEN -1.0 WHEN 'mixed' THEN 0.0 ELSE NULL END) AS sentiment_avg "
             "FROM people p LEFT JOIN call_people cp ON cp.person_id = p.id "
             "WHERE p.workspace_id = ? GROUP BY p.id ORDER BY p.company, p.seniority DESC")
        return [dict(r) for r in self.conn.execute(q, (workspace_id,)).fetchall()]

    # --- Span fetch (for citations) ----------------------------------------

    def fetch_spans_for_rows(self, rows: list[Row], max_chars: int = 4000) -> list[Row]:
        """Pull transcript segments for the (call_id, t_start_s) anchors on each row.

        We grab ±1 segment around each anchor for a bit of context, budget-capped.
        """
        if not rows:
            return []
        seen = set()
        out: list[Row] = []
        used = 0
        for row in rows:
            call_id = row.get("call_id")
            t = row.get("t_start_s")
            if not call_id or t is None:
                continue
            q = ("SELECT call_id, seg_index, t_start_s, t_end_s, speaker, content "
                 "FROM transcript_segments WHERE call_id = ? "
                 "AND t_start_s BETWEEN ? AND ? ORDER BY t_start_s")
            window = self.conn.execute(q, (call_id, max(0, t - 5), t + 60)).fetchall()
            for seg in window:
                key = (seg["call_id"], seg["t_start_s"])
                if key in seen:
                    continue
                seen.add(key)
                content = seg["content"]
                if used + len(content) > max_chars:
                    return out
                out.append(dict(seg))
                used += len(content)
        return out

    def fetch_authority_signal_spans(self, workspace_id: str, max_chars: int = 4000) -> list[Row]:
        """For stakeholder map: pull spans where decisions had owners (the load-bearing moments)."""
        q = ("SELECT s.call_id, s.seg_index, s.t_start_s, s.t_end_s, s.speaker, s.content "
             "FROM transcript_segments s JOIN decisions d "
             "  ON d.call_id = s.call_id AND s.t_start_s BETWEEN d.t_start_s AND d.t_end_s "
             "JOIN calls c ON c.id = s.call_id "
             "WHERE c.workspace_id = ? AND d.owner_id IS NOT NULL "
             "ORDER BY c.date DESC LIMIT 30")
        rows = [dict(r) for r in self.conn.execute(q, (workspace_id,)).fetchall()]
        out, used = [], 0
        for r in rows:
            if used + len(r["content"]) > max_chars:
                break
            out.append(r); used += len(r["content"])
        return out


def _json_list(xs: list[str]) -> str:
    import json
    return json.dumps(xs)
