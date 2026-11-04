"""Streamlit section: your CV and profile, plus the Claude tools (ADR-012).

The CV upload and profile editor work without Claude. Everything else appears
only when ``claude_jobs.enabled()``.
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import streamlit as st

import claude_jobs as cj
import config
import cover_letter
import cv_upload
import db

_PREFS = "search_prefs.json"
_STAGES = {
    "after_application": "Just applied: confirm interest",
    "chasing_feedback": "Chasing feedback",
    "after_interview": "Thank you after interview",
    "accept_offer": "Accept an offer",
    "decline": "Decline / withdraw",
}


def _lines(text: str) -> list[str]:
    return [line.strip() for line in (text or "").splitlines() if line.strip()]


def _role_label(r) -> str:
    return (
        f"{int(r['id'])} · {cj.text(r['title']) or '(untitled)'} — {cj.text(r['company']) or '—'}"
    )


def _flash(message: str) -> None:
    """Show ``message`` after the rerun that follows (a plain st.success would vanish)."""
    st.session_state["ai_flash"] = message


def _refresh_app() -> None:
    st.cache_data.clear()  # app.load_df caches the roles table
    st.rerun(scope="app")


def _submit(profile: str, payload: dict, role_id: int | None = None) -> None:
    try:
        with db.connect() as conn:
            cj.submit(conn, profile, payload, role_id)
    except cj.ClaudeWebError as exc:
        st.error(str(exc))
        return
    st.success(f"{cj.LABELS.get(profile, profile)} requested. Follow it in the **Results** tab.")


# --------------------------------------------------------------------------- #
# Entry points called from app.py
# --------------------------------------------------------------------------- #


def render(df: pd.DataFrame) -> None:
    """The whole section. ``df`` = active (non-archived) roles."""
    st.divider()
    st.subheader("🤖 Claude assistant")
    if not cj.enabled():
        st.caption(
            "Upload your CV and keep your profile here. To have Claude tailor CVs, write "
            "cover letters and search for roles, set `CLAUDE_WEB_URL` and `CLAUDE_WEB_API_KEY` "
            "(see ADR-012)."
        )
        _cv_and_profile(enabled=False)
        return
    tabs = st.tabs(["📎 Your CV & profile", "🎯 Role tools", "🔎 Find roles", "📋 Results"])
    with tabs[0]:
        _cv_and_profile(enabled=True)
    with tabs[1]:
        _role_tools(df)
    with tabs[2]:
        _find_roles()
    with tabs[3]:
        _results()


def queue_button(queued: pd.DataFrame) -> None:
    """Under the 'queued for a screening CV' banner: draft them now with Claude."""
    if not cj.enabled() or queued.empty:
        return
    candidate, _ = cj.load_candidate()
    if candidate is None:
        st.caption(
            "Upload your CV in **Claude assistant → Your CV & profile** to draft these with Claude."
        )
        return
    with db.connect() as conn:
        pending = {
            r["role_id"]
            for r in conn.execute(
                "SELECT role_id FROM ai_jobs WHERE profile IN ('cv_tailor', 'cover_letter') "
                f"AND status IN ({','.join('?' * len(cj.ACTIVE))})",
                cj.ACTIVE,
            )
        }
    todo = queued[~queued["id"].astype(int).isin(pending)]
    if todo.empty:
        st.caption("🤖 Claude is drafting these now; see **Claude assistant → Results**.")
        return
    if st.button(f"🤖 Draft {len(todo)} with Claude now", key="ai_draft_queue"):
        sent = 0
        try:
            with db.connect() as conn:
                for _, row in todo.iterrows():
                    role = cj.role_input(row.to_dict())
                    cj.submit(
                        conn, "cv_tailor", {"candidate": candidate, "role": role}, int(row["id"])
                    )
                    if row["status"] == "Draft CV & Cover Letter":
                        cj.submit(
                            conn,
                            "cover_letter",
                            {"candidate": candidate, "role": role},
                            int(row["id"]),
                        )
                    sent += 1
        except cj.ClaudeWebError as exc:
            st.error(f"{exc} ({sent} sent before the error)")
            return
        st.success(
            f"Sent {sent} role(s) to Claude. Each CV lands in your CV folder and the role "
            "settles to **CV Drafted** when it's done."
        )


# --------------------------------------------------------------------------- #
# Tab: your CV & profile
# --------------------------------------------------------------------------- #


def _cv_and_profile(enabled: bool) -> None:
    current = cv_upload.current_cv()
    up = st.file_uploader(
        "Upload your CV",
        type=[s.lstrip(".") for s in cv_upload.ALLOWED_SUFFIXES],
        help="Word, text-based PDF, or plain text, up to 5 MB. Kept on this server only.",
        key="cv_file",
    )
    if up is not None and st.session_state.get("cv_saved_id") != up.file_id:
        try:
            current = cv_upload.save_upload(up.name, up.getvalue())
        except cv_upload.CvUploadError as exc:
            st.error(str(exc))
        else:
            st.session_state["cv_saved_id"] = up.file_id
            st.success(
                f"Saved **{up.name}** as your current CV ({current['chars']:,} characters of text)."
            )
            current = cv_upload.current_cv()

    if current:
        c1, c2 = st.columns([3, 1])
        c1.caption(
            f"Current CV: **{current['original_name']}**, "
            f"uploaded {current['uploaded_at'].replace('T', ' ')}"
        )
        if current.get("path") and Path(current["path"]).is_file():
            c2.download_button(
                "⬇️ Original",
                data=Path(current["path"]).read_bytes(),
                file_name=current["original_name"],
                width="stretch",
                key="cv_orig_dl",
            )
        with st.expander("Text read from your CV"):
            st.text(current["text"][:20_000])
        if enabled and st.button(
            "🤖 Build my profile from this CV",
            key="ai_cv_extract",
            help="Claude copies your CV into profile.json: the facts every "
            "tailored CV and letter is built from. You review it before saving.",
        ):
            _submit(
                "cv_extract",
                {"cv_text": current["text"][:60_000], "filename": current["original_name"][:200]},
            )
    else:
        st.caption("No CV uploaded yet.")

    st.markdown("##### Your profile")
    path = Path(config.PROFILE_PATH)
    existing = path.read_text(encoding="utf-8") if path.is_file() else ""
    if existing:
        try:
            prof = json.loads(existing)
            st.caption(
                f"`{path.name}`: {prof.get('name') or '(no name)'} · "
                f"{len(prof.get('jobs') or [])} job(s) · "
                f"{len(prof.get('competencies') or [])} competencies. "
                "Every Claude draft uses only these facts."
            )
        except ValueError:
            st.warning(f"`{path}` isn't valid JSON; fix it below.")
    else:
        st.caption(
            "No profile yet. "
            + (
                "Build one from your CV above, or paste JSON below."
                if enabled
                else "Paste JSON below (see profile.example.json)."
            )
        )
    with st.expander("Edit profile.json"):
        text = st.text_area(
            "profile.json",
            existing or _example_profile(),
            height=360,
            label_visibility="collapsed",
            key="profile_json",
        )
        if st.button("💾 Save profile", key="save_profile"):
            try:
                data = json.loads(text)
                if not isinstance(data, dict):
                    raise ValueError("the profile must be a JSON object")
            except ValueError as exc:
                st.error(f"Not saved: {exc}")
            else:
                saved = cj.save_profile(data)
                st.success(f"Saved {saved} (the previous version was kept as a backup).")


def _example_profile() -> str:
    example = config.PROJECT_ROOT / "profile.example.json"
    return example.read_text(encoding="utf-8") if example.is_file() else "{}"


# --------------------------------------------------------------------------- #
# Tab: role tools
# --------------------------------------------------------------------------- #


def _role_tools(df: pd.DataFrame) -> None:
    candidate, source = cj.load_candidate()
    if candidate is None:
        st.info("Upload your CV (first tab) so Claude has something true to work from.")
        return
    if source == "cv":
        st.caption("Using your uploaded CV's text. Build a profile from it for steadier results.")
    if df.empty:
        st.caption("Add a role first.")
        return
    rows = {_role_label(r): r.to_dict() for _, r in df.iterrows()}
    choice = st.selectbox("Role", list(rows), key="ai_role")
    row = rows[choice]
    if cj.text(row.get("link")):
        st.caption(f"[Open the advert]({cj.text(row.get('link'))})")
    advert = st.text_area(
        "Advert text (optional)",
        height=120,
        key=f"ai_advert_{row['id']}",
        help="Paste the job description if the board blocks automated reading (LinkedIn often "
        "does). Otherwise Claude reads the link.",
    )
    role = cj.role_input(row, advert)
    base = {"candidate": candidate, "role": role}
    rid = int(row["id"])
    if not advert.strip() and not role["link"]:
        st.warning("This role has no link: paste the advert text so Claude knows what it's about.")

    c1, c2, c3, c4 = st.columns(4)
    if c1.button(
        "🎯 Fit review",
        width="stretch",
        key="ai_fit",
        help="Score 0-100, apply / maybe / skip, matched requirements and gaps. ~1-3 min.",
    ):
        _submit("job_fit_review", base, rid)
    if c2.button(
        "📄 Tailor CV",
        width="stretch",
        key="ai_cv",
        help="A .docx tailored to this role, saved to your CV folder. ~1 min.",
    ):
        _submit("cv_tailor", base, rid)
    if c3.button(
        "✍️ Cover letter",
        width="stretch",
        key="ai_cl",
        help="A .docx in your cover-letter folder. ~1-2 min.",
    ):
        _submit(
            "cover_letter",
            {
                **base,
                "tone": st.session_state.get("ai_tone", "direct"),
                "max_words": st.session_state.get("ai_words", 300),
            },
            rid,
        )
    if c4.button(
        "🎤 Interview prep",
        width="stretch",
        key="ai_iv",
        help="Employer research, likely questions with answer outlines. ~3-8 min.",
    ):
        with db.connect() as conn:
            iv_candidate, _, n_dropped = cj.with_story_bank(conn, base["candidate"])
        if n_dropped:
            st.warning(f"{n_dropped} stor(ies) left out: the profile would be too large to send.")
        _submit(
            "interview_prep",
            {
                **base,
                "candidate": iv_candidate,
                "interview_format": st.session_state.get("ai_iv_format", ""),
                "interviewers": _lines(st.session_state.get("ai_iv_people", ""))[:6],
            },
            rid,
        )

    with st.expander("Options: cover letter and interview"):
        o1, o2 = st.columns(2)
        o1.selectbox("Cover letter tone", ["direct", "warm", "formal"], key="ai_tone")
        o2.number_input("Max words", 120, 600, 300, step=20, key="ai_words")
        st.text_input(
            "Interview format",
            key="ai_iv_format",
            placeholder="e.g. 45-min video call with the hiring manager, competency-based",
        )
        st.text_area("Interviewers (one per line, if known)", key="ai_iv_people", height=68)

    with st.expander("📮 Follow-up email"):
        stage = st.selectbox("Stage", list(_STAGES), format_func=_STAGES.get, key="ai_stage")
        contact = st.text_input("Contact name", key=f"ai_contact_{rid}")
        history = st.text_area("What's happened so far (optional)", key=f"ai_hist_{rid}", height=68)
        if st.button("Draft follow-up", key="ai_fu"):
            _submit(
                "follow_up_email",
                {
                    **base,
                    "stage": stage,
                    "contact_name": contact[:120],
                    "date_applied": cj.text(row.get("date_applied"))[:40],
                    "history": history[:3000],
                },
                rid,
            )


# --------------------------------------------------------------------------- #
# Tab: find roles
# --------------------------------------------------------------------------- #


def _prefs_path() -> Path:
    return Path(config.PROFILE_PATH).with_name(_PREFS)


def _find_roles() -> None:
    candidate, _ = cj.load_candidate()
    if candidate is None:
        st.info("Upload your CV (first tab) so Claude can judge which roles fit.")
        return
    try:
        prefs = json.loads(_prefs_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        prefs = {}
    st.caption(
        "Claude searches the web for new adverts, reads them, checks your filters and "
        "scores each one. Roles already in the tracker are skipped. Takes 3-10 minutes."
    )
    with st.form("ai_search"):
        queries = st.text_area(
            "Search for (one per line)",
            prefs.get("queries", ""),
            height=90,
            placeholder="senior business analyst contract London",
        )
        boards = st.text_area(
            "Prefer these boards (optional, one per line)",
            prefs.get("boards", ""),
            height=68,
            placeholder="reed.co.uk\ncwjobs.co.uk",
        )
        c1, c2, c3, c4 = st.columns(4)
        location = c1.text_input("Location", prefs.get("location", ""))
        remote_ok = c2.checkbox("Remote is fine", prefs.get("remote_ok", True))
        days = c3.number_input("Posted within (days)", 1, 30, int(prefs.get("days", 7)))
        max_results = c4.number_input("Max roles", 1, 25, int(prefs.get("max_results", 10)))
        hard = st.text_area(
            "Must-haves: skip a role that fails any (one per line)",
            prefs.get("hard", ""),
            height=68,
            placeholder="day rate below £500\nrequires SC clearance",
        )
        soft = st.text_area(
            "Preferences (one per line)",
            prefs.get("soft", ""),
            height=68,
            placeholder="insurance or banking\nhybrid, 2 days or fewer in office",
        )
        go = st.form_submit_button("🔎 Search now", type="primary")
    if go:
        if not _lines(queries):
            st.error("Add at least one search line.")
            return
        _prefs_path().parent.mkdir(parents=True, exist_ok=True)
        _prefs_path().write_text(
            json.dumps(
                {
                    "queries": queries,
                    "boards": boards,
                    "location": location,
                    "remote_ok": remote_ok,
                    "days": int(days),
                    "max_results": int(max_results),
                    "hard": hard,
                    "soft": soft,
                },
                indent=1,
            ),
            encoding="utf-8",
        )
        with db.connect() as conn:
            links, ids = cj.tracked_keys(conn)
        _submit(
            "job_search",
            {
                "candidate": candidate,
                "queries": _lines(queries)[:10],
                "boards": _lines(boards)[:10],
                "location": location[:200],
                "remote_ok": bool(remote_ok),
                "posted_within_days": int(days),
                "hard_filters": _lines(hard)[:15],
                "preferences": _lines(soft)[:15],
                "exclude_links": links,
                "exclude_job_ids": ids,
                "max_results": int(max_results),
            },
        )


# --------------------------------------------------------------------------- #
# Tab: results
# --------------------------------------------------------------------------- #


def _results() -> None:
    if st.session_state.get("ai_flash"):
        st.success(st.session_state.pop("ai_flash"))
    with db.connect() as conn:
        active = cj.has_active(conn)
    st.fragment(run_every="5s" if active else None)(_jobs_table)()
    with db.connect() as conn:
        items = cj.recent(conn, 30)
    done = [i for i in items if i["status"] in cj.FINISHED]
    if not done:
        return
    labels = {
        f"#{i['id']} · {cj.LABELS.get(i['profile'], i['profile'])} · {_subject(i)}": i["id"]
        for i in done
    }
    pick = st.selectbox("Open a result", list(labels), key="ai_open")
    with db.connect() as conn:
        _detail(cj.get(conn, labels[pick]))


def _subject(item: dict) -> str:
    inp = item.get("input") or {}
    if isinstance(inp.get("role"), dict):
        return f"{inp['role'].get('title', '')} — {inp['role'].get('company') or '—'}"
    if inp.get("queries"):
        return "; ".join(inp["queries"][:2])
    return inp.get("filename") or ""


def _jobs_table() -> None:
    try:
        with db.connect() as conn:
            finished = cj.sync(conn)
            items = cj.recent(conn, 30)
    except cj.ClaudeWebError as exc:
        st.warning(f"Couldn't check on running jobs: {exc}")
        return
    for msg in finished:
        st.toast(msg)
    if not items:
        st.caption("Nothing requested yet.")
        return
    table = pd.DataFrame(
        [
            {
                "#": i["id"],
                "What": cj.LABELS.get(i["profile"], i["profile"]),
                "For": _subject(i),
                "Status": i["status"],
                "Now": i["progress"] if i["status"] in cj.ACTIVE else (i["error"] or ""),
                "Filed": i["applied_note"] or "",
                "Cost $": i["cost_usd"],
                "When": i["created_at"],
            }
            for i in items
        ]
    )
    st.dataframe(
        table,
        hide_index=True,
        width="stretch",
        column_config={"Cost $": st.column_config.NumberColumn(format="%.3f")},
    )
    if any(i["status"] in cj.ACTIVE for i in items):
        st.caption("⏳ Updates every few seconds while jobs run.")
    if finished:  # roles, CV versions and the result picker below changed
        _refresh_app()


def _apply_button(item: dict, label: str, **options) -> None:
    if st.button(label, key=f"ai_apply_{item['id']}", type="primary"):
        with db.connect() as conn:
            try:
                _flash(cj.apply(conn, item["id"], **options))
            except (ValueError, OSError) as exc:
                st.error(str(exc))
                return
        _refresh_app()


def _detail(item: dict | None) -> None:
    if not item:
        return
    r = item.get("result") or {}
    if item["status"] != "succeeded":
        st.error(f"{item['status']}: {item['error'] or 'no result'}")
        return
    if item["applied_note"]:
        st.caption(f"✅ {item['applied_note']}")
    kind = item["profile"]
    with st.container(border=True):
        if kind == "job_fit_review":
            c1, c2 = st.columns(2)
            c1.metric("Fit", f"{r.get('fit_score', '?')}/100")
            c2.metric("Recommendation", str(r.get("recommendation", "?")).title())
            st.write(r.get("summary", ""))
            if r.get("matched"):
                st.markdown("**Matched**")
                st.dataframe(pd.DataFrame(r["matched"]), hide_index=True, width="stretch")
            if r.get("gaps"):
                st.markdown("**Gaps**")
                st.dataframe(pd.DataFrame(r["gaps"]), hide_index=True, width="stretch")
            if r.get("keywords"):
                st.caption("Keywords to echo: " + ", ".join(r["keywords"]))
            for flag in r.get("red_flags") or []:
                st.warning(flag)
            if not item["applied_at"]:
                _apply_button(item, "Use as this role's fit notes")
        elif kind == "cv_tailor":
            st.markdown(f"**{r.get('headline', '')}**")
            st.write(r.get("summary", ""))
            if r.get("changes"):
                st.markdown("**What changed**")
                st.dataframe(pd.DataFrame(r["changes"]), hide_index=True, width="stretch")
            for gap in r.get("gaps") or []:
                st.warning(f"Not claimed: {gap}")
            st.info(r.get("honesty_check", ""))
            _file_download(item, config.CV_DIR)
        elif kind == "cover_letter":
            st.markdown(f"**{r.get('subject', '')}**")
            st.text(cover_letter.letter_text(r))
            for fact in r.get("employer_facts_used") or []:
                st.caption(f"• {fact.get('claim')} — {fact.get('source_url')}")
            _file_download(item, config.COVER_LETTER_DIR)
        elif kind == "interview_prep":
            md = _interview_markdown(r)
            st.markdown(md)
            st.download_button(
                "⬇️ Download (.md)",
                md,
                file_name=f"Interview prep - {_subject(item)}.md",
                key=f"ai_md_{item['id']}",
            )
        elif kind == "follow_up_email":
            st.markdown(f"**Subject:** {r.get('subject', '')}  ·  send: {r.get('send_after', '')}")
            st.code(r.get("body", ""), language=None, wrap_lines=True)
            st.caption(
                "Copy it into your email and check it before sending; nothing is sent from here."
            )
        elif kind == "job_search":
            _search_results(item, r)
        elif kind == "cv_extract":
            for w in r.get("warnings") or []:
                st.warning(w)
            st.json({k: v for k, v in r.items() if k != "warnings"}, expanded=False)
            note = "Save as my profile" + (
                " (replaces the current one; it's kept as a backup)"
                if Path(config.PROFILE_PATH).is_file()
                else ""
            )
            if not item["applied_at"]:
                _apply_button(item, note)
    st.caption(f"Cost ≈ ${item['cost_usd'] or 0:.3f} · requested {item['created_at']} UTC")


def _file_download(item: dict, folder: Path) -> None:
    name = (item.get("applied_note") or "").removeprefix("saved ").strip()
    path = Path(folder) / name if name else None
    if path and path.is_file():
        st.download_button(
            "⬇️ Download .docx",
            path.read_bytes(),
            file_name=path.name,
            mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            key=f"ai_dl_{item['id']}",
        )
    elif not item["applied_at"]:
        _apply_button(item, "Save the .docx")


def _search_results(item: dict, r: dict) -> None:
    st.write(r.get("summary", ""))
    roles = r.get("roles") or []
    if not roles:
        st.caption("No new roles passed your filters.")
    else:
        with db.connect() as conn:
            links, _ = cj.tracked_keys(conn, 5000)
        known = set(links)
        table = pd.DataFrame(
            [
                {
                    "Add": ro.get("link") not in known,
                    "Score": ro.get("fit_score"),
                    "Title": ro.get("title"),
                    "Company": ro.get("company"),
                    "Rate": ro.get("rate"),
                    "Location": ro.get("location"),
                    "Posted": ro.get("posted"),
                    "Fit notes": ro.get("fit_notes"),
                    "Link": ro.get("link"),
                    "Tracked": ro.get("link") in known,
                }
                for ro in roles
            ]
        )
        edited = st.data_editor(
            table,
            hide_index=True,
            width="stretch",
            key=f"ai_search_{item['id']}",
            disabled=[c for c in table.columns if c != "Add"],
            column_config={
                "Link": st.column_config.LinkColumn("Link", display_text="open"),
                "Score": st.column_config.ProgressColumn(
                    "Score", min_value=0, max_value=100, format="%d"
                ),
            },
        )
        chosen = [row["Link"] for _, row in edited.iterrows() if row["Add"] and not row["Tracked"]]
        if st.button(
            f"➕ Add {len(chosen)} to the tracker",
            key=f"ai_add_{item['id']}",
            type="primary",
            disabled=not chosen,
        ):
            with db.connect() as conn:
                _flash(cj.apply(conn, item["id"], links=chosen))
            _refresh_app()
    if r.get("skipped"):
        with st.expander(f"Skipped ({len(r['skipped'])})"):
            st.dataframe(pd.DataFrame(r["skipped"]), hide_index=True, width="stretch")


def _interview_markdown(r: dict) -> str:
    brief = r.get("employer_brief") or {}
    out = ["### Employer", brief.get("summary", "")]
    out += [
        f"- {f.get('claim')} ([source]({f.get('source_url')}))" for f in brief.get("facts") or []
    ]
    if r.get("role_focus"):
        out += ["", "### What they need to hear", *[f"- {x}" for x in r["role_focus"]]]
    out += ["", "### Likely questions"]
    for q in r.get("likely_questions") or []:
        out += [
            f"**{q.get('question')}**",
            f"_Why:_ {q.get('why_asked')}",
            f"_Outline:_ {q.get('answer_outline')}",
            f"_Draw on:_ {q.get('evidence')}",
            "",
        ]
    for title, key in (
        ("Questions to ask", "questions_to_ask"),
        ("Talking points", "talking_points"),
        ("Handle honestly", "risks_to_address"),
    ):
        if r.get(key):
            out += ["", f"### {title}", *[f"- {x}" for x in r[key]]]
    return "\n".join(out)
