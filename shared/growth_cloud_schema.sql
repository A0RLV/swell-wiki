-- Growth Cloud schema additions.
-- Loaded after llmwiki's `shared/sqlite_schema.sql`. Every entity row points at a call
-- + transcript timestamp range so the briefings layer can render sourced citations.

PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS calls (
    id            TEXT PRIMARY KEY,                -- e.g. "td-2025-02-18-paid-search"
    workspace_id  TEXT NOT NULL REFERENCES workspace(id) ON DELETE CASCADE,
    date          TEXT NOT NULL,                   -- ISO-8601 date
    title         TEXT NOT NULL,
    fathom_url    TEXT,
    attendees     TEXT NOT NULL DEFAULT '[]',      -- JSON array of {name, email?}
    duration_s    INTEGER,
    document_id   TEXT REFERENCES documents(id) ON DELETE SET NULL,  -- the wiki/calls/<id>.md AID doc
    raw_path      TEXT,                            -- sources/calls/<date>-<slug>.md
    created_at    TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_calls_workspace_date ON calls(workspace_id, date DESC);

-- Speaker-labeled, timestamped chunks. Feed FTS and citation rendering.
CREATE TABLE IF NOT EXISTS transcript_segments (
    id          TEXT PRIMARY KEY DEFAULT (lower(hex(randomblob(16)))),
    call_id     TEXT NOT NULL REFERENCES calls(id) ON DELETE CASCADE,
    seg_index   INTEGER NOT NULL,
    t_start_s   INTEGER NOT NULL,
    t_end_s     INTEGER NOT NULL,
    speaker     TEXT,
    content     TEXT NOT NULL,
    UNIQUE(call_id, seg_index)
);
CREATE INDEX IF NOT EXISTS idx_segments_call ON transcript_segments(call_id, t_start_s);

CREATE VIRTUAL TABLE IF NOT EXISTS transcript_fts USING fts5(
    content,
    content='transcript_segments',
    content_rowid='rowid',
    tokenize='porter unicode61'
);
CREATE TRIGGER IF NOT EXISTS transcript_fts_insert AFTER INSERT ON transcript_segments BEGIN
    INSERT INTO transcript_fts(rowid, content) VALUES (new.rowid, new.content);
END;
CREATE TRIGGER IF NOT EXISTS transcript_fts_delete AFTER DELETE ON transcript_segments BEGIN
    INSERT INTO transcript_fts(transcript_fts, rowid, content) VALUES ('delete', old.rowid, old.content);
END;

-- Cross-call person registry. AID extractor upserts by (workspace_id, normalized_name).
CREATE TABLE IF NOT EXISTS people (
    id               TEXT PRIMARY KEY DEFAULT (lower(hex(randomblob(16)))),
    workspace_id     TEXT NOT NULL REFERENCES workspace(id) ON DELETE CASCADE,
    name             TEXT NOT NULL,
    name_normalized  TEXT NOT NULL,
    company          TEXT,
    role             TEXT,
    seniority        TEXT CHECK (seniority IN ('ic', 'lead', 'manager', 'director', 'vp', 'cxo', 'founder', 'unknown')),
    authority_score  REAL DEFAULT 0,              -- 0–1, inferred from decisions owned
    first_seen_call  TEXT REFERENCES calls(id) ON DELETE SET NULL,
    last_seen_call   TEXT REFERENCES calls(id) ON DELETE SET NULL,
    UNIQUE(workspace_id, name_normalized)
);

CREATE TABLE IF NOT EXISTS call_people (
    call_id        TEXT NOT NULL REFERENCES calls(id) ON DELETE CASCADE,
    person_id      TEXT NOT NULL REFERENCES people(id) ON DELETE CASCADE,
    talk_time_pct  REAL,                          -- 0–1
    sentiment      TEXT CHECK (sentiment IN ('positive', 'neutral', 'negative', 'mixed', 'unknown')),
    PRIMARY KEY (call_id, person_id)
);

-- "We decided to …" — the decision unit. Owner is optional; resolves to people.id.
CREATE TABLE IF NOT EXISTS decisions (
    id          TEXT PRIMARY KEY DEFAULT (lower(hex(randomblob(16)))),
    call_id     TEXT NOT NULL REFERENCES calls(id) ON DELETE CASCADE,
    summary     TEXT NOT NULL,
    owner_id    TEXT REFERENCES people(id) ON DELETE SET NULL,
    deadline    TEXT,
    status      TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'in_progress', 'done', 'superseded', 'dropped')),
    workstream  TEXT,
    t_start_s   INTEGER NOT NULL,
    t_end_s     INTEGER NOT NULL,
    confidence  REAL DEFAULT 0.8,
    superseded_by TEXT REFERENCES decisions(id) ON DELETE SET NULL
);
CREATE INDEX IF NOT EXISTS idx_decisions_call ON decisions(call_id);
CREATE INDEX IF NOT EXISTS idx_decisions_status ON decisions(status);

-- "X will do Y by Z" — narrower than a decision.
CREATE TABLE IF NOT EXISTS commitments (
    id          TEXT PRIMARY KEY DEFAULT (lower(hex(randomblob(16)))),
    call_id     TEXT NOT NULL REFERENCES calls(id) ON DELETE CASCADE,
    owner_id    TEXT REFERENCES people(id) ON DELETE SET NULL,
    summary     TEXT NOT NULL,
    due         TEXT,
    status      TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'done', 'overdue', 'dropped')),
    workstream  TEXT,
    t_start_s   INTEGER NOT NULL,
    t_end_s     INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_commitments_status ON commitments(status);
CREATE INDEX IF NOT EXISTS idx_commitments_owner ON commitments(owner_id);

CREATE TABLE IF NOT EXISTS experiments (
    id          TEXT PRIMARY KEY DEFAULT (lower(hex(randomblob(16)))),
    workspace_id TEXT NOT NULL REFERENCES workspace(id) ON DELETE CASCADE,
    name        TEXT NOT NULL,
    hypothesis  TEXT,
    market      TEXT,
    channel     TEXT,
    status      TEXT NOT NULL DEFAULT 'proposed' CHECK (status IN ('proposed', 'running', 'concluded', 'killed')),
    started_call_id TEXT REFERENCES calls(id) ON DELETE SET NULL,
    last_update_call_id TEXT REFERENCES calls(id) ON DELETE SET NULL,
    UNIQUE(workspace_id, name)
);

CREATE TABLE IF NOT EXISTS workstreams (
    id           TEXT PRIMARY KEY DEFAULT (lower(hex(randomblob(16)))),
    workspace_id TEXT NOT NULL REFERENCES workspace(id) ON DELETE CASCADE,
    name         TEXT NOT NULL,
    status       TEXT,
    summary      TEXT,
    last_update_call_id TEXT REFERENCES calls(id) ON DELETE SET NULL,
    UNIQUE(workspace_id, name)
);

CREATE TABLE IF NOT EXISTS performance_signals (
    id          TEXT PRIMARY KEY DEFAULT (lower(hex(randomblob(16)))),
    call_id     TEXT NOT NULL REFERENCES calls(id) ON DELETE CASCADE,
    market      TEXT,
    channel     TEXT,
    metric      TEXT NOT NULL,
    value       TEXT,
    direction   TEXT CHECK (direction IN ('up', 'down', 'flat', 'unknown')),
    note        TEXT,
    t_start_s   INTEGER NOT NULL,
    t_end_s     INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS open_questions (
    id          TEXT PRIMARY KEY DEFAULT (lower(hex(randomblob(16)))),
    call_id     TEXT NOT NULL REFERENCES calls(id) ON DELETE CASCADE,
    question    TEXT NOT NULL,
    who_to_ask  TEXT REFERENCES people(id) ON DELETE SET NULL,
    status      TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'answered', 'dropped')),
    t_start_s   INTEGER NOT NULL,
    t_end_s     INTEGER NOT NULL
);
