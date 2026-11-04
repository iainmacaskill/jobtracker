# ADR-011 — Archive for ended/closed roles (not deletion)

**Status:** Accepted

**Context.** Vacancies close, and roles get passed on, but they should not vanish:
a recruiter may call back about a closed role, so the record must stay
searchable. Meanwhile the active views (grid, To-action queue, metrics) fill with
dead roles and lose signal. Deleting loses history; leaving everything active
loses focus.
**Decision.** Add an `archived` flag (one of the app-managed `APP_COLUMNS`, kept
out of the importable `FIELDS`). Archiving is a soft, reversible state, never a
delete. On load the app splits active from archived: the grid, To-action queue and
metrics operate on **active only**, while a searchable **📦 Archive** expander
lists archived roles with a per-row **un-archive** control. CSV export still
includes everything. Roles are archived when their vacancy has ended (confirmed on
the source's applications page) or the pipeline status is already terminal
(Pass/Rejected/Expired); live-stage roles (Shortlisted/Interview/Offer) are kept
active even if the advert closed.
**Consequences.** The active list stays focused on live opportunities without
losing any history, and everything is one click from coming back. The flag is a
plain column, so filters and the importer ignore it by default; only the app's
active/archived split reads it.
