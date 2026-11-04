# ADR-013 — Interview prep as per-role data on its own page

**Status:** Accepted (Phase 1). Phases 2 and 3 are proposed, not built.

**Context.** ADR-012 added an "Interview prep" job: the Claude server returns
employer research, likely questions and answer outlines. The result lives only
as JSON in `ai_jobs.result` and a one-off Markdown view, so it cannot be edited,
tracked or reused, and it needs the server. Preparing for an interview also
involves things no generator knows: your own wording, which answers are ready,
and when each round is.
**Decision.** Keep prep as ordinary per-role rows in three new tables
(`prep_notes`, `prep_questions`, `interview_rounds`, all `ON DELETE CASCADE` from
`jobs`), with all logic in `prep.py` (plain sqlite3, no Streamlit) and the UI on a
separate Streamlit page, `pages/Interview_Prep.py`, so `app.py` does not grow.
The page works fully offline. When the server has already returned an
`interview_prep` result for the role, an **Import** button copies it into
editable rows. Import is idempotent and never overwrites your text: questions
are de-duplicated on normalised wording and a notes field is filled only if it
is still empty. Interview rounds are a table, not new statuses, so the existing
pipeline statuses and metrics are unchanged.
**Consequences.** Prep is stored, editable and exportable (`export_markdown`)
without the server, in line with ADR-001 and ADR-002. The generated answer
outlines stay clearly separate from `my_answer`, which is yours. Deleting a role
deletes its prep (archive instead, per ADR-011, to keep it).

## Planned: story bank (Phase 2) — open design point

A `stories` table of STAR examples drawn from your real experience, linked to
questions. The requirement is that the bank is **also available to the remote
server**. The server's jobs API sends only validated input per profile, so the
likely design is: the bank is the source of truth locally, exported as JSON, and
either (a) sent as input to `interview_prep` / answer-feedback jobs so the server
can only cite stories you wrote, or (b) copied to the server by hand. Which of
these the server's profiles actually accept is **not yet checked** and must be
confirmed before building. Either way, stories are marked as yours so a generated
answer can never invent one, and the bank is kept out of git like `profile.json`.

## Planned: practice mode (Phase 3)

Questions one at a time with your typed answer, a rule-based offline checklist
(STAR structure, length) and optional server feedback. Not started.
