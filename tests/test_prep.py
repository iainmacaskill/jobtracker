import json

import pytest

import db
import prep

AI_RESULT = {
    "employer_brief": {
        "summary": "Calibration and test equipment supplier.",
        "facts": [{"claim": "Founded 2001", "source_url": "https://example.com/about"}],
    },
    "role_focus": ["Secure PHP", "REST APIs"],
    "likely_questions": [
        {"question": "How do you secure a Laravel API?", "why_asked": "Security",
         "answer_outline": "AuthN/Z, validation", "evidence": "Sadorect hosting work"},
        {"question": "Describe a database migration you owned.", "why_asked": "Data",
         "answer_outline": "Plan, test, roll back", "evidence": "Datasure"},
    ],
    "questions_to_ask": ["How is the team structured?"],
    "talking_points": ["Own features end to end"],
    "risks_to_address": ["No .NET experience"],
}


@pytest.fixture
def conn(tmp_path):
    path = tmp_path / "t.db"
    db.init_db(path)
    with db.connect(path) as c:
        yield c


def _role(conn, title="Full Stack Developer", status="Interview"):
    rid = db.insert_job(conn, {"title": title, "company": "PASS", "status": status})
    conn.commit()
    return rid


def _ai_job(conn, role_id, result=AI_RESULT, status="succeeded", profile="interview_prep"):
    cur = conn.execute(
        "INSERT INTO ai_jobs (role_id, profile, status, result) VALUES (?, ?, ?, ?)",
        (role_id, profile, status, json.dumps(result) if result is not None else None),
    )
    conn.commit()
    return cur.lastrowid


def test_init_db_is_idempotent_and_adds_prep_tables(conn):
    db.init_db(conn.execute("PRAGMA database_list").fetchone()[2])
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"prep_notes", "prep_questions", "interview_rounds"} <= tables


def test_add_question_dedupes_case_and_whitespace(conn):
    rid = _role(conn)
    assert prep.add_question(conn, rid, "Why PASS?") is not None
    assert prep.add_question(conn, rid, "  why   pass? ") is None
    assert prep.add_question(conn, rid, "   ") is None
    assert len(prep.list_questions(conn, rid)) == 1


def test_update_question_rejects_unknown_status(conn):
    rid = _role(conn)
    qid = prep.add_question(conn, rid, "Why PASS?")
    prep.update_question(conn, qid, my_answer="Local, and the stack fits.", status="Ready")
    assert prep.readiness(conn, rid) == (1, 1)
    with pytest.raises(ValueError):
        prep.update_question(conn, qid, status="Done")


def test_notes_round_trip_and_upsert(conn):
    rid = _role(conn)
    assert prep.get_notes(conn, rid)["employer"] == ""
    prep.save_notes(conn, rid, {"employer": "  Tees-based  ", "talking_points": "a\nb"})
    prep.save_notes(conn, rid, {"employer": "Tees-based", "talking_points": "a\nb\nc"})
    notes = prep.get_notes(conn, rid)
    assert notes["employer"] == "Tees-based"
    assert notes["talking_points"] == "a\nb\nc"
    assert conn.execute("SELECT COUNT(*) FROM prep_notes").fetchone()[0] == 1


def test_rounds_auto_number_and_update(conn):
    rid = _role(conn)
    r1 = prep.add_round(conn, rid, format="phone", scheduled_at="2026-11-10 10:00")
    r2 = prep.add_round(conn, rid, format="on-site")
    rounds = prep.list_rounds(conn, rid)
    assert [r["round_no"] for r in rounds] == [1, 2]
    prep.update_round(conn, r1, outcome="Passed")
    assert prep.list_rounds(conn, rid)[0]["outcome"] == "Passed"
    prep.delete_round(conn, r2)
    assert len(prep.list_rounds(conn, rid)) == 1


def test_import_ai_prep_fills_questions_and_notes(conn):
    rid = _role(conn)
    result = prep.import_ai_prep(conn, _ai_job(conn, rid))
    assert result == {"questions_added": 2, "questions_skipped": 0, "notes_filled": 5}
    notes = prep.get_notes(conn, rid)
    assert "Founded 2001 (https://example.com/about)" in notes["employer"]
    assert notes["role_focus"] == "Secure PHP\nREST APIs"
    assert all(q["source"] == "ai" for q in prep.list_questions(conn, rid))


def test_import_twice_adds_nothing_and_keeps_user_edits(conn):
    rid = _role(conn)
    ai_id = _ai_job(conn, rid)
    prep.import_ai_prep(conn, ai_id)
    q = prep.list_questions(conn, rid)[0]
    prep.update_question(conn, q["id"], my_answer="My own answer", status="Ready")
    prep.save_notes(conn, rid, {**prep.get_notes(conn, rid), "employer": "My own notes"})

    again = prep.import_ai_prep(conn, ai_id)
    assert again == {"questions_added": 0, "questions_skipped": 2, "notes_filled": 0}
    assert len(prep.list_questions(conn, rid)) == 2
    assert prep.list_questions(conn, rid)[0]["my_answer"] == "My own answer"
    assert prep.get_notes(conn, rid)["employer"] == "My own notes"


@pytest.mark.parametrize("kwargs, message", [
    ({"profile": "cv_tailor"}, "Not an interview prep"),
    ({"status": "running", "result": None}, "no result yet"),
])
def test_import_rejects_bad_jobs(conn, kwargs, message):
    rid = _role(conn)
    with pytest.raises(ValueError, match=message):
        prep.import_ai_prep(conn, _ai_job(conn, rid, **kwargs))


def test_import_rejects_unlinked_result(conn):
    ai_id = _ai_job(conn, None)
    with pytest.raises(ValueError, match="not linked"):
        prep.import_ai_prep(conn, ai_id)


def test_ai_prep_results_lists_only_this_roles_succeeded_jobs(conn):
    a, b = _role(conn), _role(conn, "Other")
    good = _ai_job(conn, a)
    _ai_job(conn, a, status="failed", result=None)
    _ai_job(conn, b)
    assert [r["id"] for r in prep.ai_prep_results(conn, a)] == [good]


def test_prep_roles_puts_interview_stages_first_and_hides_archived(conn):
    found = _role(conn, "Found one", "Found")
    interview = _role(conn, "Interview one", "Interview")
    archived = _role(conn, "Archived", "Interview")
    conn.execute("UPDATE jobs SET archived = 1 WHERE id = ?", (archived,))
    conn.commit()
    ids = [r["id"] for r in prep.prep_roles(conn)]
    assert ids == [interview, found]


def test_deleting_a_role_cascades_prep_data(conn):
    rid = _role(conn)
    prep.add_question(conn, rid, "Why PASS?")
    prep.save_notes(conn, rid, {"employer": "x"})
    prep.add_round(conn, rid)
    db.delete_job(conn, rid)
    conn.commit()
    for table in ("prep_questions", "prep_notes", "interview_rounds"):
        assert conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 0


def test_export_markdown_includes_my_answer_and_rounds(conn):
    rid = _role(conn)
    prep.import_ai_prep(conn, _ai_job(conn, rid))
    q = prep.list_questions(conn, rid)[0]
    prep.update_question(conn, q["id"], my_answer="Policies, then tests.", status="Drafted")
    prep.add_round(conn, rid, format="video", scheduled_at="2026-11-10")
    md = prep.export_markdown(conn, rid)
    assert md.startswith("# Interview prep: Full Stack Developer at PASS")
    assert "**My answer:** Policies, then tests." in md
    assert "Round 1: 2026-11-10 · video" in md
    assert "- No .NET experience" in md
