"""Streamlit frontend for the local job application tracker.

Run with:  streamlit run app.py
Data lives in jobs.db (SQLite); see migrate.py for the initial import.
"""

from __future__ import annotations

import datetime as dt
from urllib.parse import quote

import pandas as pd
import streamlit as st

import ai_panel
import config
import cv_preview
import db
import followup_queue

st.set_page_config(page_title="Job Application Tracker", page_icon="🎯", layout="wide")

DISPLAY_COLS = ["id", *db.FIELDS]


# --------------------------------------------------------------------------- #
# Data access
# --------------------------------------------------------------------------- #
# ttl keeps the view live: rows written by an external script (e.g. import_jobs)
# surface within a few seconds on the next interaction/rerun.
@st.cache_data(ttl=5)
def load_df() -> pd.DataFrame:
    db.init_db()
    with db.connect() as conn:
        rows = [dict(r) for r in db.fetch_all(conn)]
    cols = [*DISPLAY_COLS, *db.APP_COLUMNS]
    df = pd.DataFrame(rows, columns=[*cols, "source_job_id", "created_at", "updated_at"])
    return df[cols].copy()


def refresh() -> None:
    load_df.clear()


def _norm(v) -> str | None:
    """Normalise a cell for comparison / storage: blanks -> None."""
    if v is None:
        return None
    if isinstance(v, float) and pd.isna(v):
        return None
    s = str(v).strip()
    return s or None


def persist_changes(edited: pd.DataFrame, shown_ids: set[int]) -> dict[str, int]:
    """Diff the edited grid against the DB and apply inserts/updates/deletes."""
    counts = {"added": 0, "updated": 0, "deleted": 0}
    with db.connect() as conn:
        originals = {r["id"]: dict(r) for r in db.fetch_all(conn)}
        edited_ids: set[int] = set()

        for _, row in edited.iterrows():
            rid = row.get("id")
            data = {f: _norm(row.get(f)) for f in db.FIELDS}
            if not data.get("title"):
                continue  # ignore empty trailing rows
            data.setdefault("status", None)
            data["status"] = data["status"] or "Found"
            data["source_job_id"] = _parse_job_id(data.get("link"))

            if rid is None or (isinstance(rid, float) and pd.isna(rid)):
                db.insert_job(conn, data)
                counts["added"] += 1
            else:
                rid = int(rid)
                edited_ids.add(rid)
                orig = originals.get(rid)
                if orig is None:
                    continue
                if any(_norm(orig.get(f)) != data.get(f) for f in db.FIELDS):
                    db.update_job(conn, rid, data)
                    counts["updated"] += 1

        # A row that was displayed but is now gone from the grid was deleted.
        for rid in shown_ids - edited_ids:
            db.delete_job(conn, rid)
            counts["deleted"] += 1
        conn.commit()
    return counts


def _parse_job_id(link: str | None) -> str | None:
    import re

    if not link:
        return None
    m = re.search(r"/(\d{6,})", link)
    return m.group(1) if m else None


DRAFT_CV = "Draft CV"
DRAFT_CV_CL = "Draft CV & Cover Letter"


def persist_status_changes(edited: pd.DataFrame) -> dict:
    """Apply To-action status edits.

    'Draft CV' / 'Draft CV & Cover Letter' are a *queue only* — the app writes no
    document (it has no LLM and can't read the job description). Claude later reads
    each queued role's JD and writes the optimised screening CV, then settles the
    role to 'CV Drafted' (see screening_queue.py and ADR-008). All status changes
    are written through as-is.
    """
    result = {"updated": 0, "queued": 0, "errors": []}
    with db.connect() as conn:
        originals = {r["id"]: dict(r) for r in db.fetch_all(conn)}
        for _, row in edited.iterrows():
            rid = row.get("id")
            if rid is None or (isinstance(rid, float) and pd.isna(rid)):
                continue
            rid = int(rid)
            orig = originals.get(rid)
            if orig is None or _norm(orig.get("status")) == (_norm(row.get("status")) or "Found"):
                continue
            new_status = _norm(row.get("status")) or "Found"
            db.update_job(conn, rid, {"status": new_status})
            if new_status in (DRAFT_CV, DRAFT_CV_CL):
                result["queued"] += 1
            else:
                result["updated"] += 1
        conn.commit()
    return result


# --------------------------------------------------------------------------- #
# UI
# --------------------------------------------------------------------------- #
df = load_df()

# Archived roles ("Ended"/closed) drop out of every active view below and live in
# the 📦 Archive section — still searchable if a recruiter calls about a closed role.
_all_df = df
_arch_mask = df["archived"].fillna(0).astype(int) == 1
archived_df = df[_arch_mask].sort_values("date_found", ascending=False, na_position="last")
df = df[~_arch_mask].copy()

st.title("🎯 Job Application Tracker")
st.caption("Local SQLite + Streamlit · your job applications, tracked on your machine")

# --- Metrics --------------------------------------------------------------- #
today = dt.date.today()
week_ago = today - dt.timedelta(days=7)


def _applied_recently(s: pd.Series) -> int:
    dates = pd.to_datetime(s, errors="coerce").dt.normalize()
    lo, hi = pd.Timestamp(week_ago), pd.Timestamp(today)
    return int(((dates >= lo) & (dates <= hi)).sum())


def _follow_up_due_mask(d: pd.DataFrame) -> pd.Series:
    """Applied roles with a recruiter contact, ≥2 working days since applying,
    follow-up not yet sent. The due rule itself lives in followup_queue so the
    app and the agent can never disagree."""
    return (
        (d["status"] == "Applied")
        & (d["contact_email"].fillna("").astype(str).str.strip() != "")
        & ~d["follow_up_status"].fillna("").astype(str).str.strip()
            .str.lower().str.startswith("sent")
        & d["date_applied"].map(followup_queue.is_due)
    )


# "To action" = found but not yet applied to or passed — the work queue.
ACTIONED_STATUSES = {
    "Applied", "Shortlisted", "Interview", "Offer", "Pass", "Rejected",
    "Expired", "Not Applicable", "Not Applying",
}
to_action = df[~df["status"].isin(ACTIONED_STATUSES)].sort_values(
    "date_found", ascending=False, na_position="last"
)

m1, m2, m3, m4, m5, m6 = st.columns(6)
m1.metric("Active roles", len(df),
          help=f"{len(archived_df)} archived (Ended) — see the Archive section")
m2.metric("Applied", int((df["status"] == "Applied").sum()))
m3.metric(
    "Shortlisted / Interview",
    int(df["status"].isin(["Shortlisted", "Interview", "Offer"]).sum()),
)
m4.metric("🆕 To action", len(to_action))
m5.metric("Applied this week", _applied_recently(df["date_applied"]))
_fu_due = df[_follow_up_due_mask(df)].copy()
m6.metric(
    "📮 Follow-ups due",
    int((_fu_due["follow_up"].fillna(0).astype(int) != 2).sum()),
    help=(
        "Applied roles with a recruiter contact where 2+ working days have "
        "passed since applying, not yet sent or opted out — see the "
        "Follow-ups section."
    ),
)

# --- Screening-CV queue banner (persistent) ------------------------------- #
# Roles set to Draft CV are a queue only — the app writes nothing; Claude drafts
# them (ADR-008). Surface the queue and the exact prompt to copy into Cowork.
_cv_queued = df[df["status"].isin(["Draft CV", "Draft CV & Cover Letter"])]
if not _cv_queued.empty:
    with st.container(border=True):
        st.markdown(f"#### 🤖 {len(_cv_queued)} role(s) queued for a screening CV")
        st.caption(
            "Set to **Draft CV** but not yet written — the app queues, Claude drafts. "
            "Copy the prompt below into Claude (Cowork); it reads each job description and "
            "writes the optimised screening CV, then settles the role to **CV Drafted**."
        )
        st.code("draft the queued screening CVs", language=None)
        ai_panel.queue_button(_cv_queued)

# --- Contact-resolver queue ("Needs a contact") --------------------------- #
# A follow-up email needs a recruiter address. Live roles (Applied+) with no
# contact_email are queued here; the app can't reach Gmail/web/LinkedIn (ADR-002),
# so Claude resolves a *verified* address (inbox → LinkedIn → company site, never
# a guess) and files it via contact_queue.record_contact. Roles resolved to 'none'
# (no reachable email) drop out so the queue doesn't nag.
_needs_contact = df[
    df["status"].isin(["Applied", "Shortlisted", "Interview", "Offer"])
    & (df["contact_email"].fillna("").astype(str).str.strip() == "")
    & (df["contact_source"].fillna("").astype(str).str.strip() != "none")
]
if not _needs_contact.empty:
    with st.container(border=True):
        st.markdown(f"#### 📇 {len(_needs_contact)} live role(s) need a recruiter contact")
        st.caption(
            "Live applications with no recruiter email yet — needed before a follow-up "
            "can be drafted. The app can't reach Gmail or the web; copy the prompt into "
            "Claude (Cowork) and it resolves a **verified** address "
            "(your inbox → LinkedIn → company site), never a guess."
        )
        st.code("resolve contacts for the follow-up queue", language=None)
        with st.expander(f"Show the {len(_needs_contact)} role(s)", expanded=False):
            st.dataframe(
                _needs_contact[["id", "date_applied", "title", "company", "status", "link"]],
                column_config={
                    "date_applied": st.column_config.TextColumn("Applied", width="small"),
                    "link": st.column_config.LinkColumn(
                        "Link", display_text="open", width="small",
                    ),
                },
                hide_index=True,
                width="stretch",
            )

# --- Follow-ups due -------------------------------------------------------- #
# Applied roles with a verified contact, 2+ working days old, follow-up not yet
# sent. Everything starts ticked (opt-out) — untick to skip, Save, then copy the
# prompt. Claude sweeps Gmail for replies first (a reply beats a nudge), writes
# a short contextual Gmail DRAFT per ticked role (it never sends), and files the
# draft link here. You review and hit Send in Gmail, then mark the row sent.
if not _fu_due.empty:
    fu_df = _fu_due.copy()
    fu_df["send"] = fu_df["follow_up"].fillna(0).astype(int) != 2
    _fu_applied = pd.to_datetime(fu_df["date_applied"], errors="coerce").dt.date
    fu_df["days"] = _fu_applied.map(lambda d_: (today - d_).days if pd.notna(d_) else None)
    fu_df = fu_df.sort_values("date_applied", na_position="last")
    _orig_send = dict(zip(fu_df["id"].astype(int), fu_df["send"]))

    with st.container(border=True):
        st.markdown(
            f"#### 📮 Follow-ups due — {int(fu_df['send'].sum())} ticked of {len(fu_df)} due"
        )
        st.caption(
            "Untick any role you'd rather not chase and **Save selections**. Then copy the "
            "prompt into Claude (Cowork): it checks Gmail for replies first, writes a short "
            "**draft** per ticked role (it never sends), and links each draft below. "
            "Open the draft, edit, hit **Send** in Gmail — then mark it sent here."
        )
        fu_edited = st.data_editor(
            fu_df[[
                "send", "id", "days", "date_applied", "title", "company",
                "contact_email", "contact_source", "follow_up_status", "follow_up_draft",
            ]],
            column_config={
                "send": st.column_config.CheckboxColumn(
                    "Send", help="Untick to skip this role", width="small",
                ),
                "id": st.column_config.NumberColumn("id", disabled=True, width="small"),
                "days": st.column_config.NumberColumn(
                    "Days", disabled=True, width="small",
                    help="Days since you applied",
                ),
                "date_applied": st.column_config.TextColumn(
                    "Applied", disabled=True, width="small",
                ),
                "title": st.column_config.TextColumn("Title", disabled=True, width="large"),
                "company": st.column_config.TextColumn(
                    "Company / Recruiter", disabled=True, width="medium",
                ),
                "contact_email": st.column_config.TextColumn(
                    "Contact", disabled=True, width="medium",
                ),
                "contact_source": st.column_config.TextColumn(
                    "Source", disabled=True, width="small",
                    help="How the contact was verified — named-inbox / named-verified / "
                         "dept-inbox (never guessed)",
                ),
                "follow_up_status": st.column_config.TextColumn(
                    "Status", disabled=True, width="small",
                ),
                "follow_up_draft": st.column_config.LinkColumn(
                    "Draft", display_text="open draft", disabled=True, width="small",
                ),
            },
            num_rows="fixed",
            hide_index=True,
            width="stretch",
            key="followup_grid",
        )

        fc1, fc2 = st.columns([1, 2.4])
        with fc1:
            if st.button("💾 Save selections", key="save_followups", width="stretch"):
                changed = 0
                with db.connect() as conn:
                    for _, row in fu_edited.iterrows():
                        rid = int(row["id"])
                        new = bool(row["send"])
                        if new != bool(_orig_send.get(rid)):
                            db.update_job(conn, rid, {"follow_up": 1 if new else 2})
                            changed += 1
                    conn.commit()
                refresh()
                st.success(f"Saved — {changed} selection change(s).")
                st.rerun()
        with fc2:
            st.code("draft the due follow-up emails", language=None)

        _drafted = fu_df[
            fu_df["follow_up_status"].fillna("").str.lower().str.startswith("draft")
        ]
        if not _drafted.empty:
            sent_opts = {
                f"{int(r['id'])} · {r['title']} — {r['company']}": int(r["id"])
                for _, r in _drafted.iterrows()
            }
            sc1, sc2 = st.columns([3, 1])
            sent_pick = sc1.selectbox(
                "Mark a follow-up as sent", list(sent_opts),
                key="fu_sent_pick", label_visibility="collapsed",
            )
            if sc2.button("✅ Mark sent", key="fu_mark_sent", width="stretch"):
                with db.connect() as conn:
                    followup_queue.mark_sent(conn, sent_opts[sent_pick])
                    conn.commit()
                refresh()
                st.rerun()

# --- To action: found, not yet applied or passed -------------------------- #
if not to_action.empty:
    _ta_status_opts = list(dict.fromkeys([*db.STATUSES, *sorted(df["status"].dropna().unique())]))
    with st.container(border=True):
        st.markdown(f"#### 🆕 To action — {len(to_action)} role(s) not yet applied to or passed")
        st.caption(
            "Set a **Status** and click **Save actions**. Choosing **Draft CV** *queues* "
            "the role — Claude later reads its job description and writes an optimised "
            "screening CV. Applied / Pass / … drop the role off this queue."
        )
        ta_edited = st.data_editor(
            to_action[[
                "id", "date_found", "title", "company", "type", "rate", "location",
                "link", "fit_notes", "cv_version", "status",
            ]],
            column_config={
                "id": st.column_config.NumberColumn("id", disabled=True, width="small"),
                "date_found": st.column_config.TextColumn("Found", disabled=True, width="small"),
                "title": st.column_config.TextColumn("Title", disabled=True, width="large"),
                "company": st.column_config.TextColumn(
                    "Company / Recruiter", disabled=True, width="medium",
                ),
                "type": st.column_config.TextColumn("Type", disabled=True, width="small"),
                "rate": st.column_config.TextColumn("Rate", disabled=True, width="small"),
                "location": st.column_config.TextColumn("Location", disabled=True, width="medium"),
                "link": st.column_config.LinkColumn(
                    "Link", display_text="open", disabled=True, width="small",
                ),
                "fit_notes": st.column_config.TextColumn("Fit notes", disabled=True, width="large"),
                "cv_version": st.column_config.TextColumn(
                    "CV draft", disabled=True, width="medium",
                    help="Drafted CV filename — open it from your CVs folder",
                ),
                "status": st.column_config.SelectboxColumn(
                    "Status", options=_ta_status_opts, width="small", required=True,
                ),
            },
            num_rows="fixed",
            hide_index=True,
            width="stretch",
            key="to_action_grid",
        )
        if st.button("✅ Save actions", type="primary", key="save_to_action"):
            res = persist_status_changes(ta_edited)
            refresh()
            parts = []
            if res["updated"]:
                parts.append(f"{res['updated']} status update(s)")
            if res["queued"]:
                parts.append(f"{res['queued']} role(s) queued for CV drafting")
            st.success("Saved — " + (", ".join(parts) if parts else "no changes") + ".")
            if res["queued"]:
                st.info(
                    "🤖 Queued for a screening CV — ask Claude in Cowork to "
                    "“draft the queued screening CVs”. It reads each job description "
                    "and writes the optimised draft (you review before sending)."
                )
            for err in res["errors"]:
                st.warning(err)
            if not res["errors"]:
                st.rerun()

# --- Claude assistant: CV upload, profile, AI drafting (ADR-012) ---------- #
ai_panel.render(df)

# --- Filters --------------------------------------------------------------- #
_found_dates = pd.to_datetime(df["date_found"], errors="coerce").dt.date.dropna()
_min_found = _found_dates.min() if not _found_dates.empty else today
_max_found = _found_dates.max() if not _found_dates.empty else today

with st.sidebar:
    if st.button("🔄 Refresh data", width="stretch"):
        refresh()
        st.rerun()
    if st.button("⬇️ Import new roles", width="stretch",
                 help="Pull new roles from the external database set in JOBTRACKER_IMPORT_DB"):
        import import_jobs

        result = import_jobs.import_jobs()
        refresh()
        if not result["source_exists"]:
            st.warning(
                "No import source found. Set JOBTRACKER_IMPORT_DB in .env to an "
                "external SQLite database, then try again."
            )
        else:
            st.success(
                f"Imported {result['inserted']} new role(s); "
                f"{result['skipped']} already in the tracker."
            )
            st.rerun()
    st.caption("Live view · auto-refreshes every few seconds")
    st.divider()

    st.header("Filters")
    all_statuses = sorted(s for s in df["status"].dropna().unique())
    status_opts = list(dict.fromkeys([*db.STATUSES, *all_statuses]))
    status_sel = st.multiselect("Status", status_opts, default=[])
    type_opts = sorted(t for t in df["type"].dropna().unique())
    type_sel = st.multiselect("Type", type_opts, default=[])
    company_opts = sorted(c for c in df["company"].dropna().unique())
    company_sel = st.multiselect("Recruiter / company", company_opts, default=[])
    date_range = st.date_input(
        "Found between",
        value=(_min_found, _max_found),
        min_value=_min_found,
        max_value=_max_found,
        help="Filters on Date Found",
    )
    search = st.text_input("Search title / company / notes", "")
    st.divider()
    st.caption(
        "Edit cells inline, add a role in the blank bottom row, or select a "
        "row and press ⌫ to delete. Click **Save changes** to persist."
    )

view = df.copy()
if status_sel:
    view = view[view["status"].isin(status_sel)]
if type_sel:
    view = view[view["type"].isin(type_sel)]
if company_sel:
    view = view[view["company"].isin(company_sel)]
if isinstance(date_range, (tuple, list)) and len(date_range) == 2:
    lo, hi = date_range
    found = pd.to_datetime(view["date_found"], errors="coerce").dt.normalize()
    view = view[(found.isna()) | ((found >= pd.Timestamp(lo)) & (found <= pd.Timestamp(hi)))]
if search.strip():
    q = search.strip().lower()
    hay = (
        view["title"].fillna("").str.lower()
        + " " + view["company"].fillna("").str.lower()
        + " " + view["fit_notes"].fillna("").str.lower()
    )
    view = view[hay.str.contains(q, regex=False)]

st.subheader(f"Roles ({len(view)})")

# --- Status breakdown ------------------------------------------------------ #
with st.expander("📊 Status breakdown", expanded=False):
    counts = df["status"].fillna("(none)").value_counts()
    st.bar_chart(counts)

# --- Editable grid --------------------------------------------------------- #
status_options = list(dict.fromkeys([*db.STATUSES, *all_statuses]))
type_options = list(dict.fromkeys(["Contract", "Permanent", *type_opts]))

column_config = {
    "id": st.column_config.NumberColumn("id", disabled=True, width="small"),
    "date_found": st.column_config.TextColumn("Found", help="YYYY-MM-DD", width="small"),
    "title": st.column_config.TextColumn("Title", width="large", required=True),
    "company": st.column_config.TextColumn("Company / Recruiter", width="medium"),
    "type": st.column_config.SelectboxColumn("Type", options=type_options, width="small"),
    "rate": st.column_config.TextColumn("Rate / Salary", width="small"),
    "location": st.column_config.TextColumn("Location", width="medium"),
    "posted": st.column_config.TextColumn("Posted", help="YYYY-MM-DD", width="small"),
    "link": st.column_config.LinkColumn("Link", display_text="open", width="small"),
    "fit_notes": st.column_config.TextColumn("Fit notes", width="large"),
    "status": st.column_config.SelectboxColumn("Status", options=status_options, width="small"),
    "cv_version": st.column_config.TextColumn("CV version", width="medium"),
    "cover_letter": st.column_config.TextColumn(
        "Cover letter", width="medium", disabled=True,
        help="Generated draft filename — use the Generate cover letter button below",
    ),
    "date_applied": st.column_config.TextColumn("Applied", help="YYYY-MM-DD", width="small"),
    "outcome": st.column_config.TextColumn("Outcome / Next step", width="large"),
}

edited = st.data_editor(
    view[DISPLAY_COLS],
    column_config=column_config,
    column_order=DISPLAY_COLS,
    num_rows="dynamic",
    hide_index=True,
    width="stretch",
    key="grid",
)

shown_ids = {int(i) for i in view["id"].dropna().tolist()}

# Gmail deep-link: open Gmail searched for recent mail about active applications.
_active = df[df["status"].isin(["Applied", "Shortlisted", "Interview", "Offer"])]
_companies = [c for c in _active["company"].dropna().unique().tolist() if str(c).strip()][:15]
if _companies:
    _query = "newer_than:90d (" + " OR ".join(f'"{c}"' for c in _companies) + ")"
else:
    _query = (
        'newer_than:30d (subject:(application OR interview OR role OR vacancy) '
        'OR "your application" OR "next steps")'
    )
gmail_url = "https://mail.google.com/mail/u/0/#search/" + quote(_query)

col_save, col_export, col_gmail, _ = st.columns([1, 1, 1.4, 2.6])
with col_save:
    if st.button("💾 Save changes", type="primary", width="stretch"):
        result = persist_changes(edited, shown_ids)
        refresh()
        st.success(
            f"Saved · {result['added']} added, {result['updated']} updated, "
            f"{result['deleted']} deleted."
        )
        st.rerun()
with col_export:
    st.download_button(
        "⬇️ Export CSV",
        data=_all_df.to_csv(index=False).encode("utf-8"),
        file_name=f"job_tracker_{today.isoformat()}.csv",
        help="Full export, including archived roles.",
        mime="text/csv",
        width="stretch",
    )
with col_gmail:
    st.link_button(
        "📧 Search Gmail for replies", gmail_url, width="stretch",
        help=(
            "Opens Gmail in a new browser tab, pre-searched for emails from the last "
            "90 days mentioning the recruiters/companies you've applied to. It only "
            "opens a search — it does not read your inbox or change the tracker."
        ),
    )

# --- CV preview ------------------------------------------------------------ #
# Content preview of a drafted .docx (headings/bullets/bold), not page layout —
# see cv_preview.py. The download button gives the real file.
st.divider()
st.subheader("📄 CV preview")
_with_cv = _all_df[_all_df["cv_version"].fillna("").astype(str).str.strip() != ""]
if _with_cv.empty:
    st.caption("No roles have a CV version recorded yet.")
else:
    _cv_map: dict[str, tuple[str, int]] = {}
    for _, r in _with_cv.sort_values("date_found", ascending=False, na_position="last").iterrows():
        _label = f"{int(r['id'])} · {r['title'] or '(untitled)'} — {r['company'] or '—'}"
        _cv_map[_label] = (str(r["cv_version"]).strip(), int(r["id"]))
    _cv_pick_col, _cv_dl_col = st.columns([3, 1])
    _cv_choice = _cv_pick_col.selectbox(
        "Role", list(_cv_map), key="cv_preview_role", label_visibility="collapsed",
    )
    _cv_name, _ = _cv_map[_cv_choice]
    _cv_path = cv_preview.find_cv(_cv_name)
    if _cv_path is None:
        _cv_dl_col.button("⬇️ Download .docx", disabled=True, width="stretch")
        st.warning(
            f"`{_cv_name}` not found in "
            + " or ".join(f"`{d}`" for d in cv_preview.SEARCH_DIRS)
            + ". Check the CV version column matches the file on disk."
        )
    else:
        _cv_dl_col.download_button(
            "⬇️ Download .docx",
            data=_cv_path.read_bytes(),
            file_name=_cv_path.name,
            mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            width="stretch",
            key=f"cv_dl_{_cv_path.name}",
        )
        try:
            _cv_md = cv_preview.docx_to_markdown(_cv_path)
        except Exception as exc:  # corrupt / non-docx file
            st.error(f"Couldn't read `{_cv_path.name}`: {exc}")
        else:
            with st.container(border=True, height=520):
                st.markdown(_cv_md)
            st.caption(
                f"`{_cv_path}` · content preview only — fonts, margins and page "
                "breaks aren't shown; open the .docx to check it fits on two pages."
            )

# --- Archive --------------------------------------------------------------- #
st.divider()
with st.expander(f"📦 Archive — {len(archived_df)} ended / closed role(s)", expanded=False):
    st.caption(
        "Roles whose vacancy has **ended** (closed). They're off your active lists, "
        "but kept here — searchable if a recruiter follows up on a closed role. "
        "Un-archive any that come back to life."
    )
    if archived_df.empty:
        st.write("Nothing archived yet.")
    else:
        a_search = st.text_input("Search the archive", "", key="arch_search")
        a_view = archived_df
        if a_search.strip():
            q = a_search.strip().lower()
            hay = (a_view["title"].fillna("").str.lower() + " "
                   + a_view["company"].fillna("").str.lower())
            a_view = a_view[hay.str.contains(q, regex=False)]
        st.dataframe(
            a_view[["id", "date_found", "title", "company", "status", "contact_email", "link"]],
            column_config={
                "link": st.column_config.LinkColumn("Link", display_text="open", width="small"),
                "contact_email": st.column_config.TextColumn("Recruiter contact", width="medium"),
            },
            hide_index=True,
            width="stretch",
        )
        unarch = {f"{int(r['id'])} · {r['title']} — {r['company']}": int(r["id"])
                  for _, r in a_view.iterrows()}
        if unarch:
            uc1, uc2 = st.columns([3, 1])
            pick = uc1.selectbox("Un-archive", list(unarch), key="unarch_pick",
                                 label_visibility="collapsed")
            if uc2.button("♻️ Un-archive", width="stretch"):
                with db.connect() as conn:
                    db.update_job(conn, unarch[pick], {"archived": 0})
                    conn.commit()
                refresh()
                st.rerun()

# --- Cover letters --------------------------------------------------------- #
st.divider()
st.subheader("✍️ Cover letters")
if df.empty:
    st.caption("Add a role first, then generate a cover-letter draft for it.")
else:
    role_map = {}
    for _, r in df.iterrows():
        company = r["company"] if pd.notna(r["company"]) else "—"
        title = r["title"] if pd.notna(r["title"]) else "(untitled)"
        role_map[f"{int(r['id'])} · {title} — {company}"] = int(r["id"])

    cl_pick, cl_btn = st.columns([3, 1])
    chosen = cl_pick.selectbox("Role", list(role_map), key="cl_role", label_visibility="collapsed")
    if cl_btn.button("✍️ Generate cover letter", width="stretch"):
        import cover_letter

        with db.connect() as conn:
            row = conn.execute("SELECT * FROM jobs WHERE id = ?", (role_map[chosen],)).fetchone()
            path = cover_letter.generate_cover_letter(dict(row))
            db.update_job(conn, role_map[chosen], {"cover_letter": path.name})
            conn.commit()
        refresh()
        st.success(f"Draft saved → {path}")
        st.rerun()
    st.caption(
        f"Drafts are saved to `{config.COVER_LETTER_DIR}` and the filename is "
        "recorded in the **Cover letter** column. It's a starting draft — finish "
        "the bracketed parts, or ask Claude for a fully tailored version."
    )
