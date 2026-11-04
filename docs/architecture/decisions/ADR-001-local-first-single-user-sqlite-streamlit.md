# ADR-001 — Local-first, single-user (SQLite + Streamlit)

**Status:** Accepted

**Context.** A personal job-search tool. Privacy matters; infrastructure is
overhead.
**Decision.** Store everything in one local SQLite file; render with Streamlit;
no auth, no hosting by default.
**Consequences.** Zero setup and full privacy, but no multi-user access control
and a single writer. A shared/hosted instance is possible later (see the
deployment backlog) but is out of scope for the default app.
