# ADR-013 — Interview prep as per-role data on its own page

**Status:** Accepted (Phases 1 and 2). Phase 3 is proposed, not built.

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

## Story bank (Phase 2)

A `stories` table of STAR examples you type yourself (plus real figures and tags),
reused across roles, and a `question_stories` link to prep questions. Its own page
(`pages/Story_Bank.py`); each question can pick stories, and **Draft from stories**
lays them out as STAR in your own words. `compose_answer` only rearranges what you
wrote and leaves any empty part as a visible `[add: ...]` prompt, so a draft cannot
claim more than the story does. It adds to a non-empty answer rather than replacing it.

**Server access.** The live server (checked 2026-11-04) is stateless about you: every
job carries your profile in `candidate`, which is an open object limited to 40,000
characters of JSON, and the job input rejects any other unknown field. So the bank
is sent as `candidate["story_bank"]` on `interview_prep` jobs
(`claude_jobs.with_story_bank`), needing no server change. Only stories with
*Share with the Claude server* ticked are sent; the last ones are dropped if the
payload would exceed the limit. The bank can also be exported and imported as JSON
to back it up or copy it between machines. A server-side store was rejected: it
would put personal data at rest on a public deployment and break the stateless design.

**Known limit.** The server's prompts and output schema do not know about
`story_bank`, so it may cite a story in an answer outline but is not guaranteed to,
and cannot return a story id. A typed `stories` input and story-aware output would
need a small change to `claude_web/jobs/jobhunt.py`; that is left until practice mode.

## Planned: practice mode (Phase 3)

Questions one at a time with your typed answer, a rule-based offline checklist
(STAR structure, length) and optional server feedback. Not started.
