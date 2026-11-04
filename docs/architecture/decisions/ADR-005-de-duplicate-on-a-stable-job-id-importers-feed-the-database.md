# ADR-005 — De-duplicate on a stable job-id; importers feed the database

**Status:** Accepted

**Context.** The same role can be seen more than once, and an external automation
(the job-hunt skill, which runs sandboxed) produces roles the app must absorb
without duplicating.
**Decision.** Parse the numeric job-id from each link as the dedupe key (title +
company as a fallback). External tools write their own SQLite database;
`import_jobs.py` merges new rows into the canonical database and never overwrites
edits made in the app.
**Consequences.** Re-running searches and imports is safe and idempotent; the
canonical tracker stays authoritative.
