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


# Markers left on purpose by the story drafter ([add: ...]) and by the server's
# answer_draft ([FILL IN: ...]) where a fact is still missing.
_PLACEHOLDER = re.compile(r"\[(?:FILL IN|add)\b[^\]]*\]", re.IGNORECASE)


def has_placeholders(text: str | None) -> bool:
    return bool(_PLACEHOLDER.search(text or ""))


def update_question(conn: sqlite3.Connection, question_id: int, **fields: str) -> None:
    cols = [c for c in _QUESTION_EDITABLE if c in fields]
    if "status" in cols and fields["status"] not in QUESTION_STATUSES:
        raise ValueError(f"status must be one of {QUESTION_STATUSES}")
    if fields.get("status") == "Ready":
        if "my_answer" in fields:
            answer = fields["my_answer"]
        else:
            row = conn.execute(
                "SELECT my_answer FROM prep_questions WHERE id = ?", (question_id,)
            ).fetchone()
            answer = row["my_answer"] if row else ""
        if has_placeholders(answer):
            raise ValueError("Fill in the [FILL IN] / [add] gaps before marking it Ready.")
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


# --- story bank (phase 2) ---------------------------------------------------
# Stories are yours: nothing in this section generates text. ``compose_answer``
# only rearranges what you wrote, so an answer built from it cannot claim more.

STORY_FIELDS = ("title", "employer", "situation", "task", "action", "result", "figures", "tags")
_STORY_STAR = (("Situation", "situation"), ("Task", "task"), ("Action", "action"),
               ("Result", "result"))
STORY_BANK_KEY = "story_bank"  # key in the ``candidate`` dict sent to the server


def list_stories(conn: sqlite3.Connection, tag: str | None = None) -> list[dict]:
    rows = [dict(r) for r in conn.execute("SELECT * FROM stories ORDER BY title COLLATE NOCASE")]
    if tag:
        want = _norm(tag)
        rows = [r for r in rows if want in {_norm(t) for t in (r["tags"] or "").split(",")}]
    return rows


def add_story(conn: sqlite3.Connection, title: str, **fields: Any) -> int | None:
    """Add a story; returns its id, or None if blank or the title already exists."""
    title = (title or "").strip()
    if not title:
        return None
    if _norm(title) in {_norm(s["title"]) for s in list_stories(conn)}:
        return None
    cols = [c for c in STORY_FIELDS[1:] if (fields.get(c) or "").strip()]
    share = 0 if fields.get("share_with_server") is False else 1
    cur = conn.execute(
        f"INSERT INTO stories (title, share_with_server{''.join(', ' + c for c in cols)}) "
        f"VALUES (?, ?{', ?' * len(cols)})",
        [title, share, *(fields[c].strip() for c in cols)],
    )
    return int(cur.lastrowid)


def update_story(conn: sqlite3.Connection, story_id: int, **fields: Any) -> None:
    cols = [c for c in (*STORY_FIELDS, "share_with_server") if c in fields]
    if "title" in cols and not (fields["title"] or "").strip():
        raise ValueError("A story needs a title.")
    if not cols:
        return
    values = [int(bool(fields[c])) if c == "share_with_server" else (fields[c] or "").strip()
              for c in cols]
    conn.execute(
        f"UPDATE stories SET {', '.join(f'{c} = ?' for c in cols)}, "
        "updated_at = datetime('now') WHERE id = ?",
        [*values, story_id],
    )


def delete_story(conn: sqlite3.Connection, story_id: int) -> None:
    conn.execute("DELETE FROM stories WHERE id = ?", (story_id,))


def set_question_stories(conn: sqlite3.Connection, question_id: int, story_ids: list[int]) -> None:
    """Replace the stories linked to a question."""
    conn.execute("DELETE FROM question_stories WHERE question_id = ?", (question_id,))
    conn.executemany(
        "INSERT OR IGNORE INTO question_stories (question_id, story_id) VALUES (?, ?)",
        [(question_id, int(s)) for s in story_ids],
    )


def stories_for_question(conn: sqlite3.Connection, question_id: int) -> list[dict]:
    rows = conn.execute(
        """SELECT s.* FROM stories s JOIN question_stories qs ON qs.story_id = s.id
           WHERE qs.question_id = ? ORDER BY s.title COLLATE NOCASE""",
        (question_id,),
    ).fetchall()
    return [dict(r) for r in rows]


def compose_answer(stories: list[dict]) -> str:
    """A first draft of an answer, laid out as STAR from the stories you linked.

    Uses your own words, unchanged. Empty parts are left as a visible ``[add: ...]``
    prompt, never filled in, so you can see exactly what is still missing.
    """
    blocks = []
    for s in stories:
        lines = [s["title"]]
        for label, key in _STORY_STAR:
            value = (s.get(key) or "").strip()
            lines.append(f"{label}: {value}" if value else f"{label}: [add: {label.lower()}]")
        if (s.get("figures") or "").strip():
            lines.append(f"Figures: {s['figures'].strip()}")
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks)


def story_gaps(story: dict) -> list[str]:
    """STAR parts still empty, plus 'figures' when there are none: what to add next."""
    gaps = [label.lower() for label, key in _STORY_STAR if not (story.get(key) or "").strip()]
    if not (story.get("figures") or "").strip():
        gaps.append("figures")
    return gaps


def export_stories_json(conn: sqlite3.Connection, *, shared_only: bool = False) -> str:
    """The bank as JSON, to copy to another machine or back it up."""
    stories = list_stories(conn)
    if shared_only:
        stories = [s for s in stories if s["share_with_server"]]
    keep = ("id", *STORY_FIELDS)
    return json.dumps(
        {"version": 1, "stories": [{k: s[k] for k in keep} for s in stories]},
        ensure_ascii=False, indent=2,
    )


def import_stories_json(conn: sqlite3.Connection, text: str) -> dict[str, int]:
    """Add stories from ``export_stories_json`` output. Existing titles are kept as they are."""
    try:
        data = json.loads(text)
        items = data["stories"]
    except (ValueError, KeyError, TypeError) as exc:
        raise ValueError("That is not a story bank export.") from exc
    added = skipped = 0
    for item in items:
        if not isinstance(item, dict):
            skipped += 1
            continue
        fields = {k: item.get(k) or "" for k in STORY_FIELDS[1:]}
        if add_story(conn, item.get("title", ""), **fields) is None:
            skipped += 1
        else:
            added += 1
    return {"stories_added": added, "stories_skipped": skipped}


def story_bank_for_server(conn: sqlite3.Connection) -> list[dict]:
    """The stories you allowed to leave this machine, trimmed to what a prompt needs."""
    out = []
    for s in list_stories(conn):
        if not s["share_with_server"]:
            continue
        item = {k: s[k] for k in ("id", *STORY_FIELDS) if s[k]}
        out.append(item)
    return out


# --- Claude answer drafts (server profile ``answer_draft``) --------------------

def answer_draft_payload(
    conn: sqlite3.Connection, question_id: int, candidate: dict, role: dict,
    *, spoken_minutes: int = 2,
) -> dict:
    """Input for an ``answer_draft`` job: the question, your own draft and linked stories.

    ``candidate`` should already carry the story bank (``claude_jobs.with_story_bank``).
    Only stories you allowed to leave this machine can be named, and the server's
    length limits are respected. The server rejects unknown fields, so nothing else goes in.
    """
    q = conn.execute("SELECT * FROM prep_questions WHERE id = ?", (question_id,)).fetchone()
    if q is None:
        raise ValueError("Unknown question.")
    payload: dict[str, Any] = {
        "candidate": candidate,
        "role": role,
        "question": q["question"][:500],
        "spoken_minutes": max(1, min(3, int(spoken_minutes))),
    }
    for key, field, limit in (("why_asked", "why_asked", 500),
                              ("answer_outline", "answer_outline", 2000),
                              ("current_answer", "my_answer", 4000)):
        if (q[field] or "").strip():
            payload[key] = q[field].strip()[:limit]
    ids = [s["id"] for s in stories_for_question(conn, question_id) if s["share_with_server"]]
    if ids:
        payload["story_ids"] = ids[:6]
    return payload


def record_draft_job(conn: sqlite3.Connection, ai_id: int, question_id: int) -> None:
    conn.execute(
        "INSERT OR REPLACE INTO prep_drafts (ai_job_id, question_id) VALUES (?, ?)",
        (ai_id, question_id),
    )


def list_answer_drafts(conn: sqlite3.Connection, role_id: int) -> list[dict]:
    """Answer-draft jobs for this role's questions, newest first, with the result decoded."""
    rows = conn.execute(
        """SELECT a.id, a.status, a.progress, a.error, a.result, a.applied_at,
                  a.created_at, q.id AS question_id, q.question
           FROM prep_drafts d
           JOIN ai_jobs a ON a.id = d.ai_job_id
           JOIN prep_questions q ON q.id = d.question_id
           WHERE q.role_id = ? ORDER BY a.id DESC""",
        (role_id,),
    ).fetchall()
    out = []
    for r in rows:
        item = dict(r)
        try:
            item["result"] = json.loads(item["result"]) if item["result"] else None
        except ValueError:
            item["result"] = None
        out.append(item)
    return out


def apply_answer_draft(conn: sqlite3.Connection, ai_id: int) -> dict[str, Any]:
    """Add a finished draft under the question's answer. Never replaces your text.

    The draft keeps its ``[FILL IN: ...]`` markers, so the question cannot be marked
    Ready until you have supplied the real details. Each draft is applied once.
    """
    row = conn.execute(
        """SELECT a.status, a.result, a.applied_at, d.question_id
           FROM ai_jobs a JOIN prep_drafts d ON d.ai_job_id = a.id WHERE a.id = ?""",
        (ai_id,),
    ).fetchone()
    if row is None:
        raise ValueError("That is not an answer draft.")
    if row["applied_at"]:
        raise ValueError("That draft was already added.")
    if row["status"] != "succeeded" or not row["result"]:
        raise ValueError("That draft has no result yet.")
    try:
        result = json.loads(row["result"])
        draft = (result.get("answer") or "").strip()
    except (ValueError, AttributeError) as exc:
        raise ValueError("The stored result is not valid.") from exc
    if not draft:
        raise ValueError("The draft is empty.")

    qid = int(row["question_id"])
    current = conn.execute(
        "SELECT my_answer, status FROM prep_questions WHERE id = ?", (qid,)
    ).fetchone()
    mine = (current["my_answer"] or "").strip()
    merged = f"{mine}\n\n---\nClaude draft:\n{draft}" if mine else draft
    status = current["status"]
    if status == "Needs work" or has_placeholders(merged):
        status = "Drafted"
    update_question(conn, qid, my_answer=merged, status=status)
    conn.execute(
        "UPDATE ai_jobs SET applied_at = datetime('now'), applied_note = ? WHERE id = ?",
        ("Added to the question's answer", ai_id),
    )
    known = {s["id"] for s in list_stories(conn)}
    unknown = [i for i in result.get("stories_used") or [] if i not in known]
    return {
        "question_id": qid,
        "fill_ins": len(result.get("fill_ins") or []),
        "unknown_story_ids": unknown,
    }
