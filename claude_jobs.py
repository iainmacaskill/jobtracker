"""Send work to a Claude Code Web server and file the results back (ADR-012).

Optional. With ``CLAUDE_WEB_URL`` and ``CLAUDE_WEB_API_KEY`` set, the tracker can
ask the server's jobs API to search for roles, review fit, tailor a CV, draft a
cover letter, prepare for an interview, write a follow-up, or turn an uploaded CV
into ``profile.json``. Each request is a *profile-bound job*: the server fixes the
instructions and tools; the tracker only sends validated input. Jobs take from
seconds to several minutes, so they are recorded in the ``ai_jobs`` table and
polled.

Nothing here sends mail or applies for anything. Results are drafts written into
your CV / cover-letter folders and columns for you to review.
"""

from __future__ import annotations

import datetime as dt
import json
import sqlite3
import urllib.error
import urllib.request
import uuid
from pathlib import Path
from typing import Any

import config
import cover_letter
import cv_builder
import cv_upload
import db
import prep
import screening_queue

ACTIVE = ("queued", "running")
FINISHED = ("succeeded", "failed", "cancelled")

# What each server profile is called in the UI.
LABELS = {
    "job_search": "Find roles",
    "job_fit_review": "Fit review",
    "cv_tailor": "Tailored CV",
    "cover_letter": "Cover letter",
    "interview_prep": "Interview prep",
    "follow_up_email": "Follow-up email",
    "cv_extract": "Profile from CV",
}
# Results written back as soon as they arrive. The rest wait for a click:
# a search adds rows you pick, a fit review overwrites fit notes, a profile
# replaces profile.json.
AUTO_APPLY = ("cv_tailor", "cover_letter")

_TIMEOUT = 30
_ROLE_FIELDS = ("title", "company", "location", "type", "rate", "link", "fit_notes")


class ClaudeWebError(RuntimeError):
    """The server refused or couldn't be reached; the message is shown to the user."""

    def __init__(self, message: str, status: int | None = None) -> None:
        super().__init__(message)
        self.status = status


# --------------------------------------------------------------------------- #
# HTTP
# --------------------------------------------------------------------------- #


def enabled() -> bool:
    return bool(config.CLAUDE_WEB_URL and config.CLAUDE_WEB_API_KEY)


def _request(method: str, path: str, body: dict | None = None) -> dict:
    if not enabled():
        raise ClaudeWebError("Claude isn't connected: set CLAUDE_WEB_URL and CLAUDE_WEB_API_KEY.")
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(
        config.CLAUDE_WEB_URL + path,
        data=data,
        method=method,
        headers={
            "Authorization": f"Bearer {config.CLAUDE_WEB_API_KEY}",
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "jobtracker/1",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
            return json.loads(resp.read() or b"{}")
    except urllib.error.HTTPError as exc:
        raise ClaudeWebError(_http_error(exc), exc.code) from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise ClaudeWebError(f"Couldn't reach {config.CLAUDE_WEB_URL}: {exc}") from exc


def _http_error(exc: urllib.error.HTTPError) -> str:
    try:
        detail = json.loads(exc.read() or b"{}").get("detail")
    except ValueError:
        detail = None
    if isinstance(detail, list):  # pydantic validation errors
        detail = "; ".join(
            f"{'.'.join(str(p) for p in d.get('loc', [])[1:])}: {d.get('msg')}" for d in detail[:5]
        )
    hints = {
        401: "the API key was rejected (revoked or mistyped)",
        403: "this key may not do that",
        429: "today's budget for this key is used up",
    }
    return f"Claude server said {exc.code}: {detail or hints.get(exc.code) or exc.reason}"


def server_profiles() -> list[str]:
    """Profiles this key may use on the server."""
    return [p["name"] for p in _request("GET", "/api/v1/profiles").get("profiles", [])]


# --------------------------------------------------------------------------- #
# Inputs
# --------------------------------------------------------------------------- #


def load_candidate() -> tuple[dict | None, str]:
    """What the tools know about you: ``profile.json`` if present, else the text
    of your uploaded CV. Returns ``(candidate, source)``; candidate is None when
    neither exists."""
    try:
        prof = cv_builder.load_profile()
        prof = {k: v for k, v in prof.items() if not str(k).startswith("_")}
        if prof:
            return prof, "profile"
    except (FileNotFoundError, ValueError):
        pass
    cv = cv_upload.current_cv()
    if cv:
        return {"cv_text": cv["text"][:38_000]}, "cv"
    return None, ""


# The server rejects a candidate over this many characters of JSON.
_CANDIDATE_LIMIT = 40_000


def with_story_bank(
    conn: sqlite3.Connection, candidate: dict, limit: int = _CANDIDATE_LIMIT
) -> tuple[dict, int, int]:
    """``candidate`` plus the stories you allowed to leave this machine.

    The server treats everything in ``candidate`` as true facts about you, so only
    stories you wrote are added, under ``story_bank`` (no leading underscore: those
    keys are stripped). If they would push the payload over the server's limit, the
    last ones are dropped. Returns ``(candidate, included, dropped)``; the input is
    never modified.
    """
    stories = prep.story_bank_for_server(conn)
    if not stories:
        return candidate, 0, 0
    kept = list(stories)
    while kept:
        merged = {**candidate, prep.STORY_BANK_KEY: kept}
        if len(json.dumps(merged, ensure_ascii=False)) <= limit:
            return merged, len(kept), len(stories) - len(kept)
        kept.pop()
    return candidate, 0, len(stories)


def text(value: Any) -> str:
    """A cell as text: None and pandas' NaN (which is truthy) become ''."""
    if value is None or (isinstance(value, float) and value != value):
        return ""
    return str(value).strip()


def role_input(row: dict, advert_text: str = "") -> dict:
    """A tracker row as the server's ``role`` object."""
    role = {k: text(row.get(k)) for k in _ROLE_FIELDS}
    role["title"] = role["title"][:200] or "Untitled role"
    for key, limit in (
        ("company", 200),
        ("location", 200),
        ("type", 80),
        ("rate", 120),
        ("link", 2000),
        ("fit_notes", 1000),
    ):
        role[key] = role[key][:limit]
    if advert_text.strip():
        role["description"] = advert_text.strip()[:30_000]
    return role


# --------------------------------------------------------------------------- #
# Jobs
# --------------------------------------------------------------------------- #


def submit(
    conn: sqlite3.Connection, profile: str, payload: dict, role_id: int | None = None
) -> int:
    """Send one job to the server and record it. Returns the ai_jobs id."""
    reply = _request(
        "POST",
        "/api/v1/jobs",
        {
            "profile": profile,
            "input": payload,
            "idempotency_key": f"jobtracker-{uuid.uuid4()}",
        },
    )
    job = reply.get("job") or {}
    cur = conn.execute(
        "INSERT INTO ai_jobs (remote_id, role_id, profile, status, progress, input) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (
            job.get("id"),
            role_id,
            profile,
            job.get("status") or "queued",
            _progress(job),
            json.dumps(payload, ensure_ascii=False),
        ),
    )
    conn.commit()
    return int(cur.lastrowid)


def _progress(job: dict) -> str:
    return str(((job.get("progress") or {}).get("last")) or "")[:300]


def get(conn: sqlite3.Connection, ai_id: int) -> dict | None:
    row = conn.execute("SELECT * FROM ai_jobs WHERE id = ?", (ai_id,)).fetchone()
    return _decode(row) if row else None


def recent(conn: sqlite3.Connection, limit: int = 30) -> list[dict]:
    rows = conn.execute("SELECT * FROM ai_jobs ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
    return [_decode(r) for r in rows]


def has_active(conn: sqlite3.Connection) -> bool:
    return (
        conn.execute(
            f"SELECT 1 FROM ai_jobs WHERE status IN ({','.join('?' * len(ACTIVE))}) LIMIT 1", ACTIVE
        ).fetchone()
        is not None
    )


def _decode(row: sqlite3.Row) -> dict:
    item = dict(row)
    for key in ("input", "result"):
        try:
            item[key] = json.loads(item[key]) if item[key] else None
        except ValueError:
            item[key] = None
    return item


def sync(conn: sqlite3.Connection) -> list[str]:
    """Poll unfinished jobs; store results; auto-apply CVs and cover letters.
    Returns one message per job that finished during this call."""
    messages = []
    rows = conn.execute(
        f"SELECT * FROM ai_jobs WHERE status IN ({','.join('?' * len(ACTIVE))})", ACTIVE
    ).fetchall()
    for row in rows:
        try:
            job = _request("GET", f"/api/v1/jobs/{row['remote_id']}").get("job") or {}
        except ClaudeWebError as exc:
            if exc.status == 404:  # gone from the server: nothing more will come
                job = {"status": "failed", "error": "the server no longer has this job"}
            else:
                raise
        status = job.get("status") or row["status"]
        conn.execute(
            "UPDATE ai_jobs SET status = ?, progress = ?, result = ?, error = ?, cost_usd = ?, "
            "updated_at = datetime('now') WHERE id = ?",
            (
                status,
                _progress(job) or row["progress"],
                json.dumps(job["result"], ensure_ascii=False)
                if job.get("result") is not None
                else row["result"],
                job.get("error"),
                (job.get("usage") or {}).get("cost_usd_estimate"),
                row["id"],
            ),
        )
        conn.commit()
        if status in FINISHED:
            label = LABELS.get(row["profile"], row["profile"])
            if status == "succeeded" and row["profile"] in AUTO_APPLY:
                try:
                    messages.append(f"{label}: {apply(conn, row['id'])}")
                except Exception as exc:  # noqa: BLE001 - surface, don't crash the page
                    messages.append(f"{label} finished, but filing it failed: {exc}")
            else:
                messages.append(
                    f"{label}: {status}" + (f" ({job.get('error')})" if job.get("error") else "")
                )
    return messages


def cancel(conn: sqlite3.Connection, ai_id: int) -> None:
    item = get(conn, ai_id)
    if item and item["status"] in ACTIVE:
        _request("POST", f"/api/v1/jobs/{item['remote_id']}/cancel")
        conn.execute(
            "UPDATE ai_jobs SET status = 'cancelled', updated_at = datetime('now') WHERE id = ?",
            (ai_id,),
        )
        conn.commit()


# --------------------------------------------------------------------------- #
# Writing results back
# --------------------------------------------------------------------------- #


def _claim(conn: sqlite3.Connection, ai_id: int) -> bool:
    """Mark a result as applied, once. Two open browser tabs polling at the same
    time must not write two documents."""
    cur = conn.execute(
        "UPDATE ai_jobs SET applied_at = datetime('now') WHERE id = ? AND applied_at IS NULL "
        "AND status = 'succeeded'",
        (ai_id,),
    )
    conn.commit()
    return cur.rowcount == 1


def _note(conn: sqlite3.Connection, ai_id: int, note: str) -> str:
    conn.execute("UPDATE ai_jobs SET applied_note = ? WHERE id = ?", (note, ai_id))
    conn.commit()
    return note


def _role_row(conn: sqlite3.Connection, role_id: int | None) -> dict | None:
    if role_id is None:
        return None
    row = conn.execute("SELECT * FROM jobs WHERE id = ?", (role_id,)).fetchone()
    return dict(row) if row else None


def apply(conn: sqlite3.Connection, ai_id: int, **options: Any) -> str:
    """Write a finished job's result into the tracker. Returns what was done.

    cv_tailor → a .docx in the CV folder, recorded as the role's CV version (a
    role queued as 'Draft CV' settles to 'CV Drafted'). cover_letter → a .docx in
    the cover-letter folder, recorded on the role. job_fit_review → the role's
    fit notes. job_search → adds the roles listed in ``options['links']``.
    cv_extract → saves profile.json (the previous one is kept as a backup).
    """
    item = get(conn, ai_id)
    if item is None or item["status"] != "succeeded" or not isinstance(item["result"], dict):
        raise ValueError("this job has no result to use")
    if item["applied_at"] and item["profile"] != "job_search":
        return item["applied_note"] or "already done"
    if item["profile"] != "job_search" and not _claim(conn, ai_id):
        return get(conn, ai_id)["applied_note"] or "already done"
    result, profile = item["result"], item["profile"]
    role = _role_row(conn, item["role_id"])

    if profile in ("cv_tailor", "cover_letter", "job_fit_review") and role is None:
        return _note(conn, ai_id, "the role was deleted, so nothing was filed")
    if profile == "cv_tailor":
        cand, _ = load_candidate()
        path = cv_builder.generate_tailored_cv(
            role, result, cand if cand and "cv_text" not in cand else None
        )
        if (role.get("status") or "") in screening_queue.CV_QUEUE_STATUSES:
            screening_queue.record_result(conn, role["id"], path.name)
        else:
            db.update_job(conn, role["id"], {"cv_version": path.name})
        conn.commit()
        return _note(conn, ai_id, f"saved {path.name}")
    if profile == "cover_letter":
        path = cover_letter.write_ai_cover_letter(role, result)
        db.update_job(conn, role["id"], {"cover_letter": path.name})
        conn.commit()
        return _note(conn, ai_id, f"saved {path.name}")
    if profile == "job_fit_review":
        score = f"{result.get('fit_score', '?')}/100 {result.get('recommendation', '')}"
        note = f"{score}: {result.get('fit_notes', '')}"
        db.update_job(conn, role["id"], {"fit_notes": note.strip()})
        conn.commit()
        return _note(conn, ai_id, "fit notes updated")
    if profile == "job_search":
        added = add_search_results(conn, result, set(options.get("links") or ()))
        conn.execute("UPDATE ai_jobs SET applied_at = datetime('now') WHERE id = ?", (ai_id,))
        return _note(conn, ai_id, f"added {added} role(s)")
    if profile == "cv_extract":
        path = save_profile({k: v for k, v in result.items() if k != "warnings"})
        return _note(conn, ai_id, f"saved {path.name}")
    return _note(conn, ai_id, "nothing to file for this kind of job")


def add_search_results(conn: sqlite3.Connection, result: dict, links: set[str]) -> int:
    """Insert the chosen roles from a job_search result as 'Found'. Roles already
    tracked (same job-id or link) are skipped, never overwritten."""
    known_links = {r[0] for r in conn.execute("SELECT link FROM jobs WHERE link IS NOT NULL")}
    known_ids = {
        r[0] for r in conn.execute("SELECT source_job_id FROM jobs WHERE source_job_id IS NOT NULL")
    }
    added = 0
    for role in result.get("roles") or []:
        link = str(role.get("link") or "").strip()
        sid = str(role.get("source_job_id") or "").strip() or None
        if link not in links or link in known_links or (sid and sid in known_ids):
            continue
        fit = str(role.get("fit_notes") or "").strip()
        db.insert_job(
            conn,
            {
                "date_found": dt.date.today().isoformat(),
                "title": str(role.get("title") or "Untitled role").strip(),
                "company": role.get("company") or None,
                "type": role.get("type") or None,
                "rate": role.get("rate") or None,
                "location": role.get("location") or None,
                "posted": role.get("posted") or None,
                "link": link or None,
                "fit_notes": f"{role.get('fit_score', '?')}/100: {fit}" if fit else None,
                "status": "Found",
                "source_job_id": sid,
            },
        )
        known_links.add(link)
        if sid:
            known_ids.add(sid)
        added += 1
    conn.commit()
    return added


def save_profile(profile: dict, path: Path | None = None) -> Path:
    """Write profile.json, keeping the previous version as a timestamped backup."""
    path = Path(path or config.PROFILE_PATH)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
        path.rename(path.with_name(f"{path.stem}.{stamp}.bak{path.suffix}"))
    path.write_text(json.dumps(profile, indent=2, ensure_ascii=False), encoding="utf-8")
    return path


def tracked_keys(conn: sqlite3.Connection, limit: int = 1000) -> tuple[list[str], list[str]]:
    """Links and job-ids already in the tracker (newest first), so a search skips them."""
    rows = conn.execute(
        "SELECT link, source_job_id FROM jobs ORDER BY id DESC LIMIT ?", (limit,)
    ).fetchall()
    links = [r["link"][:2000] for r in rows if r["link"]]
    ids = [str(r["source_job_id"]) for r in rows if r["source_job_id"]]
    return links, ids
