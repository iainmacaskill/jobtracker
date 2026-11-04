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


# --- story bank (phase 2) ----------------------------------------------------

def _story(conn, title="Rebuilt invoicing", **kw):
    fields = {"situation": "Invoices were slow", "task": "Own the rewrite",
              "action": "Added indexes and cached totals", "result": "Pages load faster",
              "tags": "laravel, mysql", **kw}
    sid = prep.add_story(conn, title, **fields)
    conn.commit()
    return sid


def test_story_crud_and_title_dedupe(conn):
    sid = _story(conn)
    assert prep.add_story(conn, "  rebuilt   INVOICING ") is None
    assert prep.add_story(conn, "   ") is None
    prep.update_story(conn, sid, figures="Query time 4s to 0.4s")
    assert prep.list_stories(conn)[0]["figures"] == "Query time 4s to 0.4s"
    with pytest.raises(ValueError):
        prep.update_story(conn, sid, title="  ")
    prep.delete_story(conn, sid)
    assert prep.list_stories(conn) == []


def test_list_stories_filters_by_tag(conn):
    _story(conn, "A", tags="laravel, mysql")
    _story(conn, "B", tags="security")
    assert [s["title"] for s in prep.list_stories(conn, "MySQL")] == ["A"]
    assert [s["title"] for s in prep.list_stories(conn, "security")] == ["B"]
    assert prep.list_stories(conn, "nothing") == []


def test_story_gaps_flag_missing_parts_and_figures(conn):
    sid = prep.add_story(conn, "Thin story", situation="Something happened")
    story = prep.list_stories(conn)[0]
    assert story["id"] == sid
    assert prep.story_gaps(story) == ["task", "action", "result", "figures"]


def test_compose_answer_uses_only_your_words_and_marks_gaps(conn):
    full = _story(conn, "Full", figures="40% faster")
    thin = prep.add_story(conn, "Thin", action="Wrote a script")
    conn.commit()
    stories = [s for s in prep.list_stories(conn) if s["id"] in (full, thin)]
    text = prep.compose_answer(stories)
    assert "Action: Added indexes and cached totals" in text
    assert "Figures: 40% faster" in text
    # missing parts stay visible as prompts, never filled in
    assert "Situation: [add: situation]" in text
    assert "Result: [add: result]" in text
    assert text.count("Figures:") == 1  # the thin story has no figures line


def test_question_story_links_replace_and_cascade(conn):
    rid = _role(conn)
    qid = prep.add_question(conn, rid, "Walk us through a PHP app")
    a, b = _story(conn, "A"), _story(conn, "B")
    prep.set_question_stories(conn, qid, [a, b])
    assert [s["title"] for s in prep.stories_for_question(conn, qid)] == ["A", "B"]
    prep.set_question_stories(conn, qid, [b])
    assert [s["title"] for s in prep.stories_for_question(conn, qid)] == ["B"]
    prep.delete_story(conn, b)
    conn.commit()
    assert prep.stories_for_question(conn, qid) == []
    prep.set_question_stories(conn, qid, [a])
    prep.delete_question(conn, qid)
    conn.commit()
    assert conn.execute("SELECT COUNT(*) FROM question_stories").fetchone()[0] == 0


def test_export_import_round_trip_skips_existing(conn, tmp_path):
    _story(conn, "A", figures="x")
    _story(conn, "B", share_with_server=False)
    blob = prep.export_stories_json(conn)
    assert [s["title"] for s in json.loads(blob)["stories"]] == ["A", "B"]
    shared = json.loads(prep.export_stories_json(conn, shared_only=True))["stories"]
    assert [s["title"] for s in shared] == ["A"]

    other = tmp_path / "other.db"
    db.init_db(other)
    with db.connect(other) as c2:
        assert prep.import_stories_json(c2, blob) == {"stories_added": 2, "stories_skipped": 0}
        assert prep.import_stories_json(c2, blob) == {"stories_added": 0, "stories_skipped": 2}
        assert prep.list_stories(c2)[0]["figures"] == "x"
    with pytest.raises(ValueError):
        prep.import_stories_json(conn, "not json")


def test_story_bank_for_server_respects_share_flag(conn):
    _story(conn, "Shared")
    _story(conn, "Private", share_with_server=False)
    bank = prep.story_bank_for_server(conn)
    assert [s["title"] for s in bank] == ["Shared"]
    assert "share_with_server" not in bank[0]


def test_with_story_bank_adds_key_without_mutating_candidate(conn):
    import claude_jobs as cj

    _story(conn, "Shared")
    candidate = {"name": "T", "jobs": []}
    merged, included, dropped = cj.with_story_bank(conn, candidate)
    assert (included, dropped) == (1, 0)
    assert merged[prep.STORY_BANK_KEY][0]["title"] == "Shared"
    assert prep.STORY_BANK_KEY not in candidate
    assert not prep.STORY_BANK_KEY.startswith("_")  # server strips underscore keys


def test_with_story_bank_noop_when_empty_and_drops_to_fit(conn):
    import claude_jobs as cj

    candidate = {"name": "T"}
    assert cj.with_story_bank(conn, candidate) == (candidate, 0, 0)
    for i in range(5):
        _story(conn, f"Story {i}", action="x" * 400)
    merged, included, dropped = cj.with_story_bank(conn, candidate, limit=1500)
    assert included + dropped == 5 and dropped > 0
    assert len(json.dumps(merged)) <= 1500
    assert cj.with_story_bank(conn, candidate, limit=10) == (candidate, 0, 5)


# --- Claude answer drafts ----------------------------------------------------

SERVER_FIELDS = {"candidate", "role", "question", "why_asked", "answer_outline", "story_ids",
                 "current_answer", "spoken_minutes", "locale", "notes"}  # server rejects others


def _draft_job(conn, role_id, question_id, result=None, status="succeeded"):
    cur = conn.execute(
        "INSERT INTO ai_jobs (role_id, profile, status, result) VALUES (?, 'answer_draft', ?, ?)",
        (role_id, status, json.dumps(result) if result is not None else None),
    )
    prep.record_draft_job(conn, cur.lastrowid, question_id)
    conn.commit()
    return cur.lastrowid


def test_placeholders_block_ready_but_not_drafted(conn):
    rid = _role(conn)
    qid = prep.add_question(conn, rid, "Tell me about a hard bug")
    assert prep.has_placeholders("It took [FILL IN: how long] to fix.")
    assert prep.has_placeholders("Result: [add: result]")
    assert not prep.has_placeholders("It took two days to fix.")
    # in the same call
    with pytest.raises(ValueError, match="gaps"):
        prep.update_question(conn, qid, my_answer="Took [FILL IN: time]", status="Ready")
    prep.update_question(conn, qid, my_answer="Took [FILL IN: time]", status="Drafted")
    # already stored in the row
    with pytest.raises(ValueError, match="gaps"):
        prep.update_question(conn, qid, status="Ready")
    prep.update_question(conn, qid, my_answer="Took two days.", status="Ready")
    assert prep.readiness(conn, rid) == (1, 1)


def test_answer_draft_payload_only_sends_what_the_server_accepts(conn):
    rid = _role(conn)
    qid = prep.add_question(conn, rid, "Q" * 600, why_asked="W" * 700, my_answer="mine")
    shared = _story(conn, "Shared")
    private = _story(conn, "Private", share_with_server=False)
    prep.set_question_stories(conn, qid, [shared, private])
    payload = prep.answer_draft_payload(
        conn, qid, {"name": "T"}, {"title": "Dev"}, spoken_minutes=9
    )
    assert set(payload) <= SERVER_FIELDS
    assert len(payload["question"]) == 500 and len(payload["why_asked"]) == 500
    assert payload["current_answer"] == "mine"
    assert payload["story_ids"] == [shared]  # the private story never leaves
    assert payload["spoken_minutes"] == 3
    assert "answer_outline" not in payload  # empty optional parts are left out


def test_answer_draft_payload_rejects_unknown_question(conn):
    with pytest.raises(ValueError):
        prep.answer_draft_payload(conn, 999, {"name": "T"}, {"title": "Dev"})


DRAFT = {
    "answer": "I rebuilt invoicing. It cut load time by [FILL IN: the real figure].",
    "stories_used": [1, 99], "fill_ins": [{"marker": "[FILL IN: the real figure]", "needed": "x"}],
    "gaps": [], "honesty_check": "From the story.", "word_count": 12, "evidence_used": [],
}


def test_apply_draft_appends_under_my_answer_and_blocks_ready(conn):
    rid = _role(conn)
    qid = prep.add_question(conn, rid, "Walk us through a PHP app", my_answer="My words.")
    prep.update_question(conn, qid, status="Ready")
    _story(conn, "Rebuilt invoicing")  # id 1
    ai_id = _draft_job(conn, rid, qid, DRAFT)
    info = prep.apply_answer_draft(conn, ai_id)
    conn.commit()
    assert info == {"question_id": qid, "fill_ins": 1, "unknown_story_ids": [99]}
    q = prep.list_questions(conn, rid)[0]
    assert q["my_answer"].startswith("My words.\n\n---\nClaude draft:\nI rebuilt invoicing.")
    assert q["status"] == "Drafted"  # a Ready answer with gaps is demoted
    with pytest.raises(ValueError, match="already added"):
        prep.apply_answer_draft(conn, ai_id)
    assert prep.list_answer_drafts(conn, rid)[0]["applied_at"]


def test_apply_draft_into_empty_answer_and_status(conn):
    rid = _role(conn)
    qid = prep.add_question(conn, rid, "Why PASS?")
    clean = {**DRAFT, "answer": "Because the stack fits.", "fill_ins": []}
    prep.apply_answer_draft(conn, _draft_job(conn, rid, qid, clean))
    q = prep.list_questions(conn, rid)[0]
    assert q["my_answer"] == "Because the stack fits."
    assert q["status"] == "Drafted"  # from Needs work


@pytest.mark.parametrize("kwargs, message", [
    ({"status": "running", "result": None}, "no result yet"),
    ({"result": {"answer": "  "}}, "empty"),
])
def test_apply_draft_rejects_unfinished_or_empty(conn, kwargs, message):
    rid = _role(conn)
    qid = prep.add_question(conn, rid, "Why PASS?")
    with pytest.raises(ValueError, match=message):
        prep.apply_answer_draft(conn, _draft_job(conn, rid, qid, **kwargs))


def test_apply_draft_rejects_non_draft_job(conn):
    rid = _role(conn)
    with pytest.raises(ValueError, match="not an answer draft"):
        prep.apply_answer_draft(conn, _ai_job(conn, rid))


def test_draft_links_cascade_with_the_question_and_claude_label_exists(conn):
    import claude_jobs as cj

    rid = _role(conn)
    qid = prep.add_question(conn, rid, "Why PASS?")
    _draft_job(conn, rid, qid, DRAFT)
    assert len(prep.list_answer_drafts(conn, rid)) == 1
    prep.delete_question(conn, qid)
    conn.commit()
    assert prep.list_answer_drafts(conn, rid) == []
    assert conn.execute("SELECT COUNT(*) FROM prep_drafts").fetchone()[0] == 0
    assert cj.LABELS["answer_draft"] == "Answer draft"
