# ADR-007 — Draft CVs on demand, not during the sweep

**Status:** Accepted

**Context.** Generating a tailored CV for *every* role a job-hunt sweep turns up
is the most expensive step, and most of those roles are never applied to.
**Decision.** The sweep logs roles as `Found` only — no CVs. CV (and cover-letter)
drafting is triggered **per role, on demand**, by setting its status to
`Draft CV` or `Draft CV & Cover Letter` in the To-action queue; on save the app
generates the document(s), records the filenames, and settles the role to
`CV Drafted`. The in-app draft is a fast, **sector-aware** first cut: a rule-based
engine (`cv_builder.detect_sector`) reads the role's title/fit-notes and picks a
sector-appropriate profile paragraph and competency order (FS / AI / public /
default) — no LLM. Deep JD-tailoring on the few roles actually submitted stays an
agent task (ask Claude). The CV builder reads a **git-ignored `profile.json`**
(the single profile source for the app) so the shareable repo carries no personal
data.
**Consequences.** Effort is spent only on roles the user chooses to pursue;
the job-hunt skill was updated to stop auto-drafting in the sweep.
