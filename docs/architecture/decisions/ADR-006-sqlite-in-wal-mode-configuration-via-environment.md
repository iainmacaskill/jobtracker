# ADR-006 — SQLite in WAL mode; configuration via environment

**Status:** Accepted

**Context.** A script may write while the app is open, and paths differ per
machine.
**Decision.** Open the database in WAL mode with a busy-timeout (concurrent reads
+ a serialized write, no whole-file lock); read all machine-specific paths from
environment variables (optionally a git-ignored `.env`).
**Consequences.** Safe concurrent use, and a portable, shareable repo with
nothing machine-specific committed.
