# ADR-009 — Interview CV: a designed HTML→PDF, built in-house

**Status:** Accepted

**Context.** ADR-008 split the CV into a plain screening CV and a designed
"interview" CV for human readers, but deferred building the latter. Recruiters
increasingly AI-screen even the CVs sent directly to them, so the interview CV must
look polished **and** preserve keyword coverage.
**Decision.** Build it in-house (`interview_cv.py`): render a self-contained,
print-styled HTML and convert to PDF via the locally-installed **headless Chrome**
(`--headless --print-to-pdf`) — no pip/system dependencies, and nothing leaves the
machine. It renders the **same keyword-optimised `screening` payload** as
`screening_cv`, so the designed PDF carries identical AI-screening coverage
(verified with `keyword_coverage`); with no payload it falls back to the
sector-aware profile (ADR-007). Each role therefore has a plain `.docx` (pure-ATS
stage) **and** a designed `.pdf` (human / AI-screened recruiter stage).
**Considered and rejected — external builders (Manus, Lovable).** Manus is an MCP
*client* (can't be called to generate anything). Lovable exposes a server but
builds React *web apps* (a hosted URL, not a document), is OAuth-only (can't be
connected from a non-interactive session) and is gated behind a paid plan — so
neither is automatable here, and both would send personal data off-machine.
**Consequences.** Styling is free, private, repeatable and honest (same content,
just laid out well); the two-format output keeps ATS parsing clean while giving
humans a polished PDF. Requires Chrome/Chromium installed for the PDF export.
