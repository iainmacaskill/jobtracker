"""Interview prep page: questions, notes and rounds for one role (ADR-013).

All data logic lives in prep.py. This page only draws it and saves your edits.
Works fully offline; the "Import" banner appears only when the Claude server has
already returned an interview prep result for the role.
"""

from __future__ import annotations

import datetime as dt

import streamlit as st

import db
import prep

st.set_page_config(page_title="Interview prep", page_icon="🎤", layout="wide")
db.init_db()  # idempotent; this page can be opened before the main one


def _toast(message: str) -> None:
    st.session_state["prep_flash"] = message


def _selected_role(roles: list[dict]) -> dict:
    ids = [r["id"] for r in roles]
    wanted = st.query_params.get("role")
    default = ids.index(int(wanted)) if wanted and wanted.isdigit() and int(wanted) in ids else 0
    return st.selectbox(
        "Role",
        roles,
        index=default,
        format_func=lambda r: (
            f"{r['title'] or '(untitled)'} — {r['company'] or '—'}  [{r['status']}]"
        ),
    )


st.title("🎤 Interview prep")
if msg := st.session_state.pop("prep_flash", None):
    st.toast(msg)

with db.connect() as conn:
    roles = prep.prep_roles(conn)
if not roles:
    st.info("No active roles yet. Add one on the main page first.")
    st.stop()

role = _selected_role(roles)
rid = role["id"]
st.query_params["role"] = str(rid)

with db.connect() as conn:
    ready, total = prep.readiness(conn, rid)
    ai_results = prep.ai_prep_results(conn, rid)
    questions = prep.list_questions(conn, rid)
    notes = prep.get_notes(conn, rid)
    rounds = prep.list_rounds(conn, rid)
    full_role = prep.get_role(conn, rid) or {}

c1, c2, c3 = st.columns(3)
c1.metric("Questions ready", f"{ready} / {total}")
c2.metric("Interview rounds", len(rounds))
c3.metric("Status", role["status"] or "—")
if full_role.get("link"):
    cv = full_role.get("cv_version") or "none yet"
    st.caption(f"[Job posting]({full_role['link']}) · CV: {cv}")

if ai_results:
    with st.container(border=True):
        st.markdown("**The Claude server has interview prep for this role.**")
        choice = st.selectbox(
            "Result", ai_results, format_func=lambda r: f"#{r['id']} · {r['created_at']}",
            key="prep_ai_choice",
        )
        st.caption("Import copies it into editable rows. It never overwrites your own text.")
        if st.button("Import into this role", key="prep_import"):
            try:
                with db.connect() as conn:
                    result = prep.import_ai_prep(conn, choice["id"])
            except ValueError as exc:
                st.error(str(exc))
            else:
                _toast(
                    f"Imported {result['questions_added']} question(s); "
                    f"{result['questions_skipped']} already there; "
                    f"{result['notes_filled']} notes field(s) filled."
                )
                st.rerun()

tab_q, tab_n, tab_r, tab_x = st.tabs(["Questions", "Notes", "Interviews", "Export"])

with tab_q:
    with st.form("prep_add_question", clear_on_submit=True):
        new_q = st.text_input("Add a question you expect")
        if st.form_submit_button("Add question") and new_q.strip():
            with db.connect() as conn:
                added = prep.add_question(conn, rid, new_q)
            _toast("Question added." if added else "That question is already on the list.")
            st.rerun()
    if not questions:
        st.caption("No questions yet. Add one above, or import the server's result.")
    for q in questions:
        mark = {"Ready": "✅", "Drafted": "✏️"}.get(q["status"], "⬜")
        with st.expander(f"{mark} {q['question']}"):
            if q["why_asked"]:
                st.markdown(f"**Why they ask:** {q['why_asked']}")
            if q["answer_outline"]:
                st.markdown(f"**Outline:** {q['answer_outline']}")
            if q["evidence"]:
                st.markdown(f"**Draw on:** {q['evidence']}")
            with st.form(f"prep_q_{q['id']}"):
                answer = st.text_area("My answer (my own words)", q["my_answer"] or "", height=160)
                status = st.selectbox(
                    "Status", prep.QUESTION_STATUSES,
                    index=prep.QUESTION_STATUSES.index(q["status"]),
                )
                save, drop = st.columns(2)
                if save.form_submit_button("Save", type="primary"):
                    with db.connect() as conn:
                        prep.update_question(conn, q["id"], my_answer=answer, status=status)
                    _toast("Saved.")
                    st.rerun()
                if drop.form_submit_button("Delete question"):
                    with db.connect() as conn:
                        prep.delete_question(conn, q["id"])
                    _toast("Question deleted.")
                    st.rerun()

with tab_n:
    with st.form("prep_notes"):
        values = {
            "employer": st.text_area("Employer", notes["employer"], height=140),
            "role_focus": st.text_area(
                "What they need to hear (one per line)", notes["role_focus"]
            ),
            "talking_points": st.text_area(
                "Talking points (one per line)", notes["talking_points"]
            ),
            "risks": st.text_area("Handle honestly: gaps (one per line)", notes["risks"]),
            "questions_to_ask": st.text_area(
                "Questions to ask them (one per line)", notes["questions_to_ask"]
            ),
        }
        if st.form_submit_button("Save notes", type="primary"):
            with db.connect() as conn:
                prep.save_notes(conn, rid, values)
            _toast("Notes saved.")
            st.rerun()

with tab_r:
    with st.form("prep_add_round", clear_on_submit=True):
        a, b, c = st.columns(3)
        day = a.date_input("Date", value=None)
        at = b.time_input("Time", value=None)
        fmt = c.text_input("Format", placeholder="phone / video / on-site / test")
        people = st.text_input("Interviewers")
        if st.form_submit_button("Add round"):
            when = None
            if day and at:
                when = dt.datetime.combine(day, at).isoformat(sep=" ", timespec="minutes")
            elif day:
                when = day.isoformat()
            with db.connect() as conn:
                prep.add_round(
                    conn, rid, scheduled_at=when, format=fmt.strip(), interviewers=people.strip()
                )
            _toast("Round added.")
            st.rerun()
    for r in rounds:
        label = f"Round {r['round_no']} — {r['scheduled_at'] or 'date TBC'}"
        with st.expander(label):
            with st.form(f"prep_r_{r['id']}"):
                x, y = st.columns(2)
                f_when = x.text_input("When", r["scheduled_at"] or "")
                f_fmt = y.text_input("Format", r["format"] or "")
                f_people = st.text_input("Interviewers", r["interviewers"] or "")
                f_notes = st.text_area("Notes after the interview", r["notes"] or "")
                f_out = st.text_input("Outcome", r["outcome"] or "")
                s, d = st.columns(2)
                if s.form_submit_button("Save", type="primary"):
                    with db.connect() as conn:
                        prep.update_round(
                            conn, r["id"], scheduled_at=f_when.strip(), format=f_fmt.strip(),
                            interviewers=f_people.strip(), notes=f_notes,
                            outcome=f_out.strip(),
                        )
                    _toast("Round saved.")
                    st.rerun()
                if d.form_submit_button("Delete round"):
                    with db.connect() as conn:
                        prep.delete_round(conn, r["id"])
                    _toast("Round deleted.")
                    st.rerun()

with tab_x:
    with db.connect() as conn:
        sheet = prep.export_markdown(conn, rid)
    st.download_button(
        "⬇️ Download prep sheet (.md)", sheet,
        file_name=f"Interview prep - {role['company'] or 'role'} - {role['title'] or ''}.md",
    )
    st.markdown(sheet)
