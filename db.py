"""SQLite data layer for the job application tracker.

Single source of truth for the schema and all CRUD helpers used by both the
migration script and the Streamlit app.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

from config import DB_PATH  # noqa: F401  (re-exported for callers as db.DB_PATH)

# Columns the app reads/writes, in display order. `id`, `source_job_id` and the
# timestamps are managed automatically and are not part of this list.
FIELDS = [
    "date_found",
    "title",
    "company",
    "type",
    "rate",
    "location",
    "posted",
    "link",
    "fit_notes",
    "status",
    "cv_version",
    "cover_letter",
    "date_applied",
    "outcome",
]

# App-managed columns — set by the app/agent (follow-ups, archive), never by the
# CSV/xlsx importers, so they are kept out of the importable FIELDS above.
APP_COLUMNS = (
    "contact_email", "contact_source", "follow_up", "follow_up_status",
    "follow_up_draft", "archived",
)

# Canonical pipeline statuses. "etc." in the brief — kept open via free text in
# the UI, but these drive ordering, metrics and the default dropdown.
# "Draft CV" / "Draft CV & Cover Letter" are one-shot action triggers: setting one
# in the To-action queue drafts the document(s) on save, then settles to "CV Drafted".
STATUSES = [
    "Found", "Draft CV", "Draft CV & Cover Letter", "CV Drafted",
    "Applied", "Shortlisted", "Interview", "Offer", "Pass", "Rejected", "Expired",
]

SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    date_found    TEXT,
    title         TEXT NOT NULL,
    company       TEXT,
    type          TEXT,
    rate          TEXT,
    location      TEXT,
    posted        TEXT,
    link          TEXT,
    fit_notes     TEXT,
    status        TEXT NOT NULL DEFAULT 'Found',
    cv_version    TEXT,
    cover_letter  TEXT,
    date_applied  TEXT,
    outcome       TEXT,
    contact_email TEXT,                        -- recruiter contact (Reed applications page)
    contact_source TEXT,                       -- provenance of contact_email (verified only)
    follow_up     INTEGER NOT NULL DEFAULT 0,  -- 0 default (ticked in UI) / 1 ticked / 2 opted out
    follow_up_status TEXT,                     -- '', 'Draft ready', 'Sent <date>', or a note
    follow_up_draft TEXT,                      -- link to the Gmail draft (user reviews & sends)
    archived      INTEGER NOT NULL DEFAULT 0,  -- 1 = 'Ended'/closed -> Archive
    source_job_id TEXT,                       -- numeric job-id parsed from the link, for dedupe
    created_at    TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at    TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Helps importers avoid re-inserting roles already logged.
CREATE INDEX IF NOT EXISTS idx_jobs_source_job_id ON jobs(source_job_id);
CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status);

-- Work sent to a Claude Code Web server (claude_jobs.py, ADR-012). Optional: stays
-- empty unless CLAUDE_WEB_API_KEY is set.
CREATE TABLE IF NOT EXISTS ai_jobs (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    remote_id    TEXT UNIQUE,                  -- job id on the claude-web server
    role_id      INTEGER,                      -- jobs.id it is about (NULL: search / CV)
    profile      TEXT NOT NULL,                -- cv_tailor, cover_letter, job_search, ...
    status       TEXT NOT NULL,                -- queued / running / succeeded / failed / cancelled
    progress     TEXT,                         -- what the agent is doing now
    input        TEXT,                         -- JSON sent (kept so a run can be repeated)
    result       TEXT,                         -- JSON returned
    error        TEXT,
    cost_usd     REAL,
    applied_at   TEXT,                         -- when its result was written back (files / columns)
    applied_note TEXT,
    created_at   TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at   TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_ai_jobs_status ON ai_jobs(status);

-- Interview prep (prep.py, ADR-013). All three cascade when a role is deleted.
CREATE TABLE IF NOT EXISTS prep_notes (
    role_id          INTEGER PRIMARY KEY REFERENCES jobs(id) ON DELETE CASCADE,
    employer         TEXT,                     -- what you know about them (markdown)
    role_focus       TEXT,                     -- what they need to hear, one per line
    questions_to_ask TEXT,                     -- one per line
    talking_points   TEXT,                     -- one per line
    risks            TEXT,                     -- gaps to handle honestly, one per line
    updated_at       TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS prep_questions (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    role_id       INTEGER NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
    question      TEXT NOT NULL,
    why_asked     TEXT,
    answer_outline TEXT,
    evidence      TEXT,                        -- what to draw on from your real experience
    my_answer     TEXT,                        -- your own wording
    status        TEXT NOT NULL DEFAULT 'Needs work',  -- Needs work / Drafted / Ready
    source        TEXT NOT NULL DEFAULT 'manual',      -- manual / ai
    created_at    TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at    TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_prep_questions_role ON prep_questions(role_id);

CREATE TABLE IF NOT EXISTS interview_rounds (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    role_id      INTEGER NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
    round_no     INTEGER NOT NULL DEFAULT 1,
    scheduled_at TEXT,                         -- ISO date or datetime
    format       TEXT,                         -- phone / video / on-site / technical test ...
    interviewers TEXT,
    notes        TEXT,                         -- after-the-fact notes
    outcome      TEXT,                         -- free text: passed, waiting, rejected ...
    created_at   TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at   TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_interview_rounds_role ON interview_rounds(role_id);

-- Story bank (ADR-013, phase 2). Your real examples, reused across roles. Only what
-- you type is stored: nothing here is ever generated, so an answer built from a
-- story can only state what you wrote.
CREATE TABLE IF NOT EXISTS stories (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    title            TEXT NOT NULL,
    employer         TEXT,                     -- which job it comes from
    situation        TEXT,
    task             TEXT,
    action           TEXT,
    result           TEXT,
    figures          TEXT,                     -- real numbers only, in your words
    tags             TEXT,                     -- comma-separated: security, laravel, leadership
    share_with_server INTEGER NOT NULL DEFAULT 1,  -- include when jobs go to the Claude server
    created_at       TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at       TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS question_stories (
    question_id INTEGER NOT NULL REFERENCES prep_questions(id) ON DELETE CASCADE,
    story_id    INTEGER NOT NULL REFERENCES stories(id) ON DELETE CASCADE,
    PRIMARY KEY (question_id, story_id)
);
"""


def connect(db_path: Path | str = DB_PATH) -> sqlite3.Connection:
    # timeout: how long sqlite3 waits on a locked DB before raising.
    conn = sqlite3.connect(str(db_path), timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    # WAL lets the Streamlit app keep reading while a script (e.g. an importer)
    # writes — no whole-file lock like an open spreadsheet. busy_timeout makes a
    # writer wait its turn instead of failing immediately.
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA busy_timeout = 5000")
    return conn


def init_db(db_path: Path | str = DB_PATH) -> None:
    with connect(db_path) as conn:
        conn.executescript(SCHEMA)
        _ensure_columns(conn)


def _ensure_columns(conn: sqlite3.Connection) -> None:
    """Add columns introduced after a database was first created (idempotent)."""
    existing = {row["name"] for row in conn.execute("PRAGMA table_info(jobs)")}
    for column, ddl in (
        ("cover_letter", "TEXT"),
        ("contact_email", "TEXT"),
        ("contact_source", "TEXT"),
        ("follow_up", "INTEGER NOT NULL DEFAULT 0"),
        ("follow_up_status", "TEXT"),
        ("follow_up_draft", "TEXT"),
        ("archived", "INTEGER NOT NULL DEFAULT 0"),
    ):
        if column not in existing:
            conn.execute(f"ALTER TABLE jobs ADD COLUMN {column} {ddl}")


def insert_job(conn: sqlite3.Connection, data: dict[str, Any]) -> int:
    cols = [c for c in (*FIELDS, "source_job_id", *APP_COLUMNS) if c in data]
    placeholders = ", ".join("?" for _ in cols)
    sql = f"INSERT INTO jobs ({', '.join(cols)}) VALUES ({placeholders})"
    cur = conn.execute(sql, [data.get(c) for c in cols])
    return int(cur.lastrowid)


def update_job(conn: sqlite3.Connection, job_id: int, data: dict[str, Any]) -> None:
    cols = [c for c in (*FIELDS, "source_job_id", *APP_COLUMNS) if c in data]
    if not cols:
        return
    assignments = ", ".join(f"{c} = ?" for c in cols)
    sql = f"UPDATE jobs SET {assignments}, updated_at = datetime('now') WHERE id = ?"
    conn.execute(sql, [*(data.get(c) for c in cols), job_id])


def delete_job(conn: sqlite3.Connection, job_id: int) -> None:
    conn.execute("DELETE FROM jobs WHERE id = ?", (job_id,))


def fetch_all(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute("SELECT * FROM jobs ORDER BY date_found DESC, id DESC").fetchall()


def find_by_source_job_id(conn: sqlite3.Connection, source_job_id: str) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM jobs WHERE source_job_id = ?", (source_job_id,)
    ).fetchone()


def upsert_job(conn: sqlite3.Connection, data: dict[str, Any]) -> tuple[int, str]:
    """Insert or update a job keyed on its ``source_job_id``.

    Lets an external script write a role without any fragile row-matching — same
    job-id updates in place, a new job-id inserts. Falls back to a plain insert
    when no ``source_job_id`` is present.
    Returns ``(id, "inserted" | "updated")``.
    """
    sid = data.get("source_job_id")
    if sid:
        existing = find_by_source_job_id(conn, sid)
        if existing is not None:
            update_job(conn, existing["id"], data)
            return int(existing["id"]), "updated"
    return insert_job(conn, data), "inserted"
