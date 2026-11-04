"""Story bank page: your real examples (STAR), reused across roles (ADR-013).

Everything here is typed by you. Nothing is generated, so an answer built from a
story can only say what you wrote. Stories marked "share" travel to the Claude
server inside interview prep jobs; unticked ones never leave this machine.
"""

from __future__ import annotations

import streamlit as st

import db
import prep

st.set_page_config(page_title="Story bank", page_icon="📚", layout="wide")
db.init_db()


def _toast(message: str) -> None:
    st.session_state["story_flash"] = message


st.title("📚 Story bank")
st.caption(
    "Real examples from your work, in STAR form. Link them to interview questions on the "
    "Interview prep page. Add real figures only; the app never invents them."
)
if msg := st.session_state.pop("story_flash", None):
    st.toast(msg)

tag = st.text_input("Filter by tag", placeholder="security, laravel, leadership").strip()
with db.connect() as conn:
    stories = prep.list_stories(conn)
    shown = prep.list_stories(conn, tag) if tag else stories

with st.expander("➕ Add a story", expanded=not stories):
    with st.form("story_add", clear_on_submit=True):
        title = st.text_input("Title", placeholder="Rebuilt the client invoicing module")
        a, b = st.columns(2)
        employer = a.text_input("Employer / project")
        tags = b.text_input("Tags (comma-separated)", placeholder="laravel, mysql, performance")
        situation = st.text_area("Situation: what was going on?", height=80)
        task = st.text_area("Task: what were you responsible for?", height=80)
        action = st.text_area("Action: what did you do, specifically?", height=100)
        result = st.text_area("Result: what changed?", height=80)
        figures = st.text_input("Figures (real numbers only, optional)")
        share = st.checkbox("Share with the Claude server in interview prep jobs", value=True)
        if st.form_submit_button("Add story", type="primary"):
            with db.connect() as conn:
                sid = prep.add_story(
                    conn, title, employer=employer, tags=tags, situation=situation, task=task,
                    action=action, result=result, figures=figures, share_with_server=share,
                )
            _toast("Story added." if sid else "Needs a new title (that one exists or is blank).")
            st.rerun()

st.subheader(f"Stories ({len(shown)})")
if not shown:
    st.caption("No stories yet." if not stories else "No stories match that tag.")
for s in shown:
    gaps = prep.story_gaps(s)
    flag = "" if not gaps else f"  ·  missing: {', '.join(gaps)}"
    with st.expander(f"{s['title']}{flag}"):
        with st.form(f"story_{s['id']}"):
            t = st.text_input("Title", s["title"])
            a, b = st.columns(2)
            emp = a.text_input("Employer / project", s["employer"] or "")
            tg = b.text_input("Tags", s["tags"] or "")
            sit = st.text_area("Situation", s["situation"] or "", height=80)
            tk = st.text_area("Task", s["task"] or "", height=80)
            ac = st.text_area("Action", s["action"] or "", height=100)
            rs = st.text_area("Result", s["result"] or "", height=80)
            fg = st.text_input("Figures", s["figures"] or "")
            sh = st.checkbox("Share with the Claude server", value=bool(s["share_with_server"]))
            save, drop = st.columns(2)
            if save.form_submit_button("Save", type="primary"):
                try:
                    with db.connect() as conn:
                        prep.update_story(
                            conn, s["id"], title=t, employer=emp, tags=tg, situation=sit,
                            task=tk, action=ac, result=rs, figures=fg, share_with_server=sh,
                        )
                except ValueError as exc:
                    st.error(str(exc))
                else:
                    _toast("Saved.")
                    st.rerun()
            if drop.form_submit_button("Delete story"):
                with db.connect() as conn:
                    prep.delete_story(conn, s["id"])
                _toast("Story deleted.")
                st.rerun()

st.divider()
st.subheader("Back up or copy the bank")
with db.connect() as conn:
    shared_json = prep.export_stories_json(conn, shared_only=True)
    all_json = prep.export_stories_json(conn)
c1, c2 = st.columns(2)
c1.download_button("⬇️ Export all stories (.json)", all_json, file_name="story-bank.json")
c2.download_button("⬇️ Export shared only (.json)", shared_json, file_name="story-bank-shared.json")
upload = st.file_uploader("Import a story bank (.json)", type="json")
if upload is not None and st.button("Import stories"):
    try:
        with db.connect() as conn:
            res = prep.import_stories_json(conn, upload.getvalue().decode("utf-8"))
    except (ValueError, UnicodeDecodeError) as exc:
        st.error(str(exc))
    else:
        _toast(f"Imported {res['stories_added']}; {res['stories_skipped']} already there.")
        st.rerun()
