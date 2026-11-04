"""Interview prep: per-role questions, notes and interview rounds (ADR-013).

Plain sqlite3 helpers, no Streamlit, so the page stays thin and this is testable.
Everything works without the Claude server; ``import_ai_prep`` only reads an
``interview_prep`` result the server already returned (ai_jobs) and copies it into
rows you can edit. Importing never overwrites text you wrote, and importing the
same result twice adds nothing.
"""

from __future__ import annotations

import json
import re
import sqlite3
from typing import Any

QUESTION_STATUSES = ["Needs work", "Drafted", "Ready"]
# Roles worth preparing for come first in the page's role picker.
PREP_STATUSES = ("Shortlisted", "Interview", "Offer")

NOTE_FIELDS = ("employer", "role_focus", "questions_to_ask", "talking_points", "risks")
_QUESTION_EDITABLE = ("question", "why_asked", "answer_outline", "evidence", "my_answer", "status")
_ROUND_EDITABLE = ("round_no", "scheduled_at", "format", "interviewers", "notes", "outcome")


def _norm(text: str | None) -> str:
    return re.sub(r"\s+", " ", (text or "").strip().lower())


def _lines(items: Any) -> str:
    return "\n".join(str(x).strip() for x in (items or []) if str(x).strip())


# --- roles -----------------------------------------------------------------

def prep_roles(conn: sqlite3.Connection) -> list[dict]:
    """Active roles for the picker: Shortlisted/Interview/Offer first, then the rest."""
    marks = ",".join("?" for _ in PREP_STATUSES)
    rows = conn.execute(
        f"""SELECT id, title, company, status FROM jobs
            WHERE COALESCE(archived, 0) = 0
            ORDER BY CASE WHEN status IN ({marks}) THEN 0 ELSE 1 END,
                     date_found DESC, id DESC""",
        PREP_STATUSES,
    ).fetchall()
    return [dict(r) for r in rows]


def get_role(conn: sqlite3.Connection, role_id: int) -> dict | None:
    row = conn.execute("SELECT * FROM jobs WHERE id = ?", (role_id,)).fetchone()
    return dict(row) if row else None


# --- notes -----------------------------------------------------------------

def get_notes(conn: sqlite3.Connection, role_id: int) -> dict:
    row = conn.execute("SELECT * FROM prep_notes WHERE role_id = ?", (role_id,)).fetchone()
    notes = {f: "" for f in NOTE_FIELDS}
    if row:
        notes.update({f: row[f] or "" for f in NOTE_FIELDS})
    return notes


def save_notes(conn: sqlite3.Connection, role_id: int, notes: dict) -> None:
    values = [(notes.get(f) or "").strip() for f in NOTE_FIELDS]
    conn.execute(
        f"""INSERT INTO prep_notes (role_id, {', '.join(NOTE_FIELDS)}, updated_at)
            VALUES (?, {', '.join('?' for _ in NOTE_FIELDS)}, datetime('now'))
            ON CONFLICT(role_id) DO UPDATE SET
                {', '.join(f'{f} = excluded.{f}' for f in NOTE_FIELDS)},
                updated_at = datetime('now')""",
        [role_id, *values],
    )


# --- questions -------------------------------------------------------------

def list_questions(conn: sqlite3.Connection, role_id: int) -> list[dict]:
    rows = conn.execute(
        "SELECT * FROM prep_questions WHERE role_id = ? ORDER BY id", (role_id,)
    ).fetchall()
    return [dict(r) for r in rows]


def add_question(
    conn: sqlite3.Connection, role_id: int, question: str, *, source: str = "manual", **fields: str
) -> int | None:
    """Add a question; returns its id, or None if blank or already there for this role."""
    question = (question or "").strip()
    if not question:
        return None
    existing = {_norm(q["question"]) for q in list_questions(conn, role_id)}
    if _norm(question) in existing:
        return None
    cols = [c for c in ("why_asked", "answer_outline", "evidence", "my_answer") if fields.get(c)]
    cur = conn.execute(
        f"INSERT INTO prep_questions (role_id, question, source{''.join(', ' + c for c in cols)}) "
        f"VALUES (?, ?, ?{', ?' * len(cols)})",
        [role_id, question, source, *(fields[c] for c in cols)],
    )
    return int(cur.lastrowid)


def update_question(conn: sqlite3.Connection, question_id: int, **fields: str) -> None:
    cols = [c for c in _QUESTION_EDITABLE if c in fields]
    if "status" in cols and fields["status"] not in QUESTION_STATUSES:
        raise ValueError(f"status must be one of {QUESTION_STATUSES}")
    if not cols:
        return
    conn.execute(
        f"UPDATE prep_questions SET {', '.join(f'{c} = ?' for c in cols)}, "
        "updated_at = datetime('now') WHERE id = ?",
        [*(fields[c] for c in cols), question_id],
    )


def delete_question(conn: sqlite3.Connection, question_id: int) -> None:
    conn.execute("DELETE FROM prep_questions WHERE id = ?", (question_id,))


def readiness(conn: sqlite3.Connection, role_id: int) -> tuple[int, int]:
    """(questions marked Ready, total questions) for a role."""
    row = conn.execute(
        "SELECT SUM(status = 'Ready'), COUNT(*) FROM prep_questions WHERE role_id = ?",
        (role_id,),
    ).fetchone()
    return int(row[0] or 0), int(row[1] or 0)


# --- interview rounds ------------------------------------------------------

def list_rounds(conn: sqlite3.Connection, role_id: int) -> list[dict]:
    rows = conn.execute(
        "SELECT * FROM interview_rounds WHERE role_id = ? ORDER BY round_no, id", (role_id,)
    ).fetchall()
    return [dict(r) for r in rows]


def add_round(conn: sqlite3.Connection, role_id: int, **fields: Any) -> int:
    """Add a round; ``round_no`` defaults to one more than the highest so far."""
    if not fields.get("round_no"):
        top = conn.execute(
            "SELECT MAX(round_no) FROM interview_rounds WHERE role_id = ?", (role_id,)
        ).fetchone()[0]
        fields["round_no"] = (top or 0) + 1
    cols = [c for c in _ROUND_EDITABLE if fields.get(c) not in (None, "")]
    cur = conn.execute(
        f"INSERT INTO interview_rounds (role_id{''.join(', ' + c for c in cols)}) "
        f"VALUES (?{', ?' * len(cols)})",
        [role_id, *(fields[c] for c in cols)],
    )
    return int(cur.lastrowid)


def update_round(conn: sqlite3.Connection, round_id: int, **fields: Any) -> None:
    cols = [c for c in _ROUND_EDITABLE if c in fields]
    if not cols:
        return
    conn.execute(
        f"UPDATE interview_rounds SET {', '.join(f'{c} = ?' for c in cols)}, "
        "updated_at = datetime('now') WHERE id = ?",
        [*(fields[c] for c in cols), round_id],
    )


def delete_round(conn: sqlite3.Connection, round_id: int) -> None:
    conn.execute("DELETE FROM interview_rounds WHERE id = ?", (round_id,))


# --- importing the server's interview_prep result ---------------------------

def ai_prep_results(conn: sqlite3.Connection, role_id: int) -> list[dict]:
    """Succeeded interview_prep jobs for this role, newest first (id, created_at)."""
    rows = conn.execute(
        """SELECT id, created_at FROM ai_jobs
           WHERE role_id = ? AND profile = 'interview_prep' AND status = 'succeeded'
             AND result IS NOT NULL ORDER BY id DESC""",
        (role_id,),
    ).fetchall()
    return [dict(r) for r in rows]


def import_ai_prep(conn: sqlite3.Connection, ai_id: int) -> dict[str, int]:
    """Copy a server ``interview_prep`` result into this role's editable prep rows.

    Safe to repeat: questions already present (same wording) are skipped, and a
    notes field is only filled when it is still empty, so your edits survive.
    """
    row = conn.execute("SELECT * FROM ai_jobs WHERE id = ?", (ai_id,)).fetchone()
    if row is None or row["profile"] != "interview_prep":
        raise ValueError("Not an interview prep result.")
    if row["status"] != "succeeded" or not row["result"]:
        raise ValueError("That interview prep job has no result yet.")
    if row["role_id"] is None:
        raise ValueError("That result is not linked to a role.")
    try:
        result = json.loads(row["result"])
    except ValueError as exc:
        raise ValueError("The stored result is not valid JSON.") from exc
    role_id = int(row["role_id"])

    brief = result.get("employer_brief") or {}
    employer = brief.get("summary", "") or ""
    facts = []
    for f in brief.get("facts") or []:
        if f.get("claim"):
            src = f" ({f['source_url']})" if f.get("source_url") else ""
            facts.append(f"- {f['claim']}{src}")
    incoming = {
        "employer": "\n".join(p for p in (employer.strip(), *facts) if p),
        "role_focus": _lines(result.get("role_focus")),
        "questions_to_ask": _lines(result.get("questions_to_ask")),
        "talking_points": _lines(result.get("talking_points")),
        "risks": _lines(result.get("risks_to_address")),
    }
    notes = get_notes(conn, role_id)
    filled = [f for f in NOTE_FIELDS if not notes[f].strip() and incoming[f]]
    if filled:
        save_notes(conn, role_id, {**notes, **{f: incoming[f] for f in filled}})

    added = skipped = 0
    for q in result.get("likely_questions") or []:
        qid = add_question(
            conn, role_id, q.get("question", ""), source="ai",
            why_asked=q.get("why_asked") or "",
            answer_outline=q.get("answer_outline") or "",
            evidence=q.get("evidence") or "",
        )
        if qid is None:
            skipped += 1
        else:
            added += 1
    return {"questions_added": added, "questions_skipped": skipped, "notes_filled": len(filled)}


# --- export ----------------------------------------------------------------

def export_markdown(conn: sqlite3.Connection, role_id: int) -> str:
    """One Markdown sheet for the role: notes, rounds and every question with your answer."""
    role = get_role(conn, role_id)
    if role is None:
        raise ValueError("Unknown role.")
    out = [f"# Interview prep: {role['title']} at {role.get('company') or '—'}", ""]
    notes = get_notes(conn, role_id)
    for title, key in (
        ("Employer", "employer"), ("What they need to hear", "role_focus"),
        ("Talking points", "talking_points"), ("Handle honestly", "risks"),
        ("Questions to ask them", "questions_to_ask"),
    ):
        if notes[key].strip():
            body = notes[key] if key == "employer" else "\n".join(
                f"- {ln}" for ln in notes[key].splitlines() if ln.strip()
            )
            out += [f"## {title}", body, ""]
    rounds = list_rounds(conn, role_id)
    if rounds:
        out.append("## Interviews")
        for r in rounds:
            bits = [x for x in (r["scheduled_at"], r["format"], r["interviewers"]) if x]
            out.append(f"- Round {r['round_no']}: " + (" · ".join(bits) or "TBC"))
            if r["outcome"]:
                out.append(f"  - Outcome: {r['outcome']}")
        out.append("")
    qs = list_questions(conn, role_id)
    if qs:
        out.append("## Questions")
        for q in qs:
            out += [f"### {q['question']}  _[{q['status']}]_"]
            for label, key in (("Why asked", "why_asked"), ("Outline", "answer_outline"),
                               ("Draw on", "evidence"), ("My answer", "my_answer")):
                if q[key]:
                    out.append(f"**{label}:** {q[key]}")
            out.append("")
    return "\n".join(out).rstrip() + "\n"
